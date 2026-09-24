"""One function per hook event, built from small steps.

Each router step runs through guarded(), so a failing router step never
removes the output of an earlier step, such as the protocol or the reminder.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional

from . import payload as hook_payload
from . import gate, records, rules, state, transcript
from .agent_result import log_agent_result
from .client import Answer, RouterClient
from .config import Config, current_dir
from .daemon import start_router
from .guard import guarded
from .messages import COUNTER_TEXT, HINT_TEXT, PROTOCOL_FALLBACK, REMINDER_FALLBACK, REMINDER_MARK
from .model_pick import model_pick
from .output import PREFIX, HookResult, block_stderr, lines, pre_tool_use, pre_tool_use_deny


def run(event: str, payload: Dict[str, Any], env: Mapping[str, str]) -> HookResult:
    """Handle one hook event. Unknown events and the off switch give no output."""
    handler = HANDLERS.get(event)
    if handler is None:
        return HookResult()
    config = Config.from_env(env)
    if config.off:
        return HookResult()
    return handler(payload, env, config)


def debug_capture(event: str, raw: str, env: Mapping[str, str]) -> None:
    """Append the raw agent-call payload to the ORCHESTRATOR_DEBUG file, as the bash gate did."""
    config = Config.from_env(env)
    if event != "agent-call" or config.off or not config.debug_file:
        return
    try:
        with open(config.debug_file, "a", encoding="utf-8") as handle:
            handle.write(raw + "\n")
    except Exception:
        pass


# Session start: load protocol, router start.

def session_start(payload: Dict[str, Any], env: Mapping[str, str], config: Config) -> HookResult:
    protocol = config.protocol_text()
    out = PROTOCOL_FALLBACK + "\n" if protocol is None else protocol
    if not config.router_off:
        started = guarded(lambda: start_router(config), None)
        if started:
            out += ("" if out.endswith("\n") or not out else "\n") + started + "\n"
    return HookResult(stdout=out)


# Prompt: reminder, finalise previous turn, route verdict, effective route, new state, log prompt, hint.

def prompt(payload: Dict[str, Any], env: Mapping[str, str], config: Config) -> HookResult:
    prompt_text = hook_payload.field_text(payload, "prompt")
    if rules.is_worker_report(prompt_text):
        if not config.router_off:
            guarded(lambda: _reopen_finalized_turn(payload, config), None)
        return HookResult()
    out = [reminder_line(config)]
    if not config.router_off:
        hint = guarded(lambda: _route_prompt(payload, env, config), None)
        if hint:
            out.append(hint)
    return lines(out)


def _reopen_finalized_turn(payload: Dict[str, Any], config: Config) -> None:
    """A worker report never starts a turn. If Stop already finalized this one, reopen it so the
    next Stop writes a fresh prompt_outcome with the updated counts."""
    path, current = state.load_for(config.state_dir, payload)
    if current is not None and current.finalized:
        current.finalized = False
        state.save(path, current)


def reminder_line(config: Config) -> str:
    """The protocol's "> Before you start:" line, or the fallback sentence."""
    for line in (config.protocol_text() or "").splitlines():
        if line.startswith(REMINDER_MARK):
            return PREFIX + line[2:]
    return PREFIX + REMINDER_FALLBACK


def _route_prompt(payload: Dict[str, Any], env: Mapping[str, str], config: Config) -> Optional[str]:
    session = hook_payload.session_id(payload)
    path, last = state.load_for(config.state_dir, payload)
    prompt_text = hook_payload.field_text(payload, "prompt")
    # The context now is the end of the previous turn and the start of this one.
    tokens = transcript.context_tokens(hook_payload.value(payload, "transcript_path"))
    previous = guarded(lambda: _finalise_previous(last, tokens, config), 0)
    answer = guarded(lambda: RouterClient.from_config(config).route(prompt_text), Answer())
    verdict = rules.parse_route_verdict(answer.body)
    route, route_conf, tier = rules.effective_route(verdict, config.route_margin), verdict.route_conf, verdict.tier
    carried = _carry_source(last, verdict, prompt_text, config)
    if carried is not None:
        route, route_conf, tier = carried.route, carried.route_conf, carried.tier
    now = records.now_iso()
    record = state.TurnState(
        session_id=session, turn=previous + 1, turn_started=now, prompt=records.truncate(prompt_text),
        route=route, route_conf=route_conf, tier=tier, threshold=rules.threshold_for(route, env),
        server=answer.server, context_tokens_start=tokens)
    guarded(lambda: state.save(path, record), False)
    cwd = hook_payload.field_text(payload, "cwd") or current_dir()
    guarded(lambda: records.append(config.log_file, records.PromptRecord(
        session_id=session, turn=record.turn, cwd=cwd, text=prompt_text, verdict=verdict.to_dict(),
        latency_ms=answer.latency_ms, server=answer.server, route_effective=route,
        margin=rules.route_margin(verdict.route_probs), carried_from_turn=carried.turn if carried else None,
        ts=now), config.log_off), None)
    if route != "delegate":
        return None
    return HINT_TEXT.format(conf=route_conf, tier=tier)


def _carry_source(last: Optional[state.TurnState], verdict: rules.RouteVerdict, text: str,
                  config: Config) -> Optional[state.TurnState]:
    """The previous turn when a short follow-up such as "continue" takes its route. A slash command never does."""
    if last is None or last.route not in rules.EFFECTIVE_ROUTES or verdict.by_regex:
        return None
    return last if rules.is_short(text, config.carry_words) else None


def _finalise_previous(previous: Optional[state.TurnState], tokens_end: Optional[int], config: Config) -> int:
    """Log the outcome of the last turn when the stop hook did not. Its turn number."""
    if previous is None:
        return 0
    if not previous.finalized:
        _log_outcome(previous, "next_prompt", tokens_end, config)
    return previous.turn


def _log_outcome(record: state.TurnState, source: str, tokens_end: Optional[int], config: Config) -> None:
    seconds = transcript.seconds_between(record.turn_started, records.now_iso())
    records.append(config.log_file, records.PromptOutcomeRecord(
        session_id=record.session_id, turn=record.turn, n_exploratory=record.n_exploratory,
        n_agent=record.n_agent, n_tool=record.n_tool, warned=record.warned, source=source, n_edit=record.n_edit,
        duration_s=None if seconds is None else int(seconds), context_tokens_start=record.context_tokens_start,
        context_tokens_end=tokens_end), config.log_off)


# Agent call: gate, model pick.

def agent_call(payload: Dict[str, Any], env: Mapping[str, str], config: Config) -> HookResult:
    if payload.get("tool_name") not in ("Agent", "Task"):
        return HookResult()
    verdict = gate.check(hook_payload.tool_input(payload), config.models)
    if verdict.deny:
        return block_stderr(verdict.deny)
    pick = None
    if not config.router_off and not hook_payload.field_text(payload, "agent_id"):
        pick = guarded(lambda: model_pick(payload, config), None)
    model_set = pick is not None and pick.updated_input is not None
    messages: List[str] = []
    contexts: List[str] = []
    # The missing-model and unknown-model warnings are stale when the router set a model. A fork warning stands.
    if verdict.warning and not (verdict.about_model and model_set):
        messages.append(verdict.warning)
        contexts.append(verdict.warning)
    if pick and pick.message:
        messages.append(pick.message)
        if pick.tell_claude:
            contexts.append(pick.message)
    return pre_tool_use(messages, contexts, pick.updated_input if pick else None)


# Tool call: exploration counter.

def tool_call(payload: Dict[str, Any], env: Mapping[str, str], config: Config) -> HookResult:
    if config.router_off or hook_payload.field_text(payload, "agent_id"):
        return HookResult()
    return guarded(lambda: _count(payload, config), HookResult())


def _count(payload: Dict[str, Any], config: Config) -> HookResult:
    path, current = state.load_for(config.state_dir, payload)
    if current is None:
        return HookResult()
    tool = hook_payload.field_text(payload, "tool_name")
    current.n_tool += 1
    if rules.is_exploratory(tool, hook_payload.field_text(payload, "tool_input", "command")):
        current.n_exploratory += 1
    if current.n_exploratory <= current.threshold or current.warned:
        state.save(path, current)
        return HookResult()
    current.warned = True
    if not state.save(path, current):
        return HookResult()
    message = COUNTER_TEXT.format(count=current.n_exploratory, threshold=current.threshold, route=current.route)
    guarded(lambda: records.append(config.log_file, records.ExplorationWarningRecord(
        session_id=current.session_id, turn=current.turn, n_exploratory=current.n_exploratory,
        threshold=current.threshold, tool=tool, blocked=config.block), config.log_off), None)
    if config.block:
        return pre_tool_use_deny(message)
    return pre_tool_use([message], [message])


# Edit call: count the main thread's own edits. No router call and no warning.

def edit_call(payload: Dict[str, Any], env: Mapping[str, str], config: Config) -> HookResult:
    if not config.router_off and not hook_payload.field_text(payload, "agent_id"):
        guarded(lambda: _count_edit(payload, config), None)
    return HookResult()


def _count_edit(payload: Dict[str, Any], config: Config) -> None:
    path, current = state.load_for(config.state_dir, payload)
    if current is not None and hook_payload.field_text(payload, "tool_name") in rules.EDIT_TOOLS:
        current.n_edit += 1
        state.save(path, current)


# Stop: finalise turn.

def stop(payload: Dict[str, Any], env: Mapping[str, str], config: Config) -> HookResult:
    if not config.router_off:
        guarded(lambda: _finalise(payload, config), None)
    return HookResult()


def _finalise(payload: Dict[str, Any], config: Config) -> None:
    path, current = state.load_for(config.state_dir, payload)
    if current is None or current.finalized:
        return
    current.finalized = True
    # Mark first, so a failed write never leads to a second outcome record.
    if state.save(path, current):
        _log_outcome(current, "stop", transcript.context_tokens(hook_payload.value(payload, "transcript_path")), config)


# Subagent stop: log the worker's outcome. Prints nothing, so it never keeps a worker running.

def subagent_stop(payload: Dict[str, Any], env: Mapping[str, str], config: Config) -> HookResult:
    if not config.router_off:
        guarded(lambda: log_agent_result(payload, config), None)
    return HookResult()


HANDLERS: Dict[str, Callable[[Dict[str, Any], Mapping[str, str], Config], HookResult]] = {
    "session-start": session_start, "prompt": prompt, "agent-call": agent_call, "tool-call": tool_call,
    "edit-call": edit_call, "stop": stop, "subagent-stop": subagent_stop,
}
