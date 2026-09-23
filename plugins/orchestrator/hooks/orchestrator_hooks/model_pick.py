"""The model pick: the router picks the model for every worker call.

Claude's own choice stands only when the user's prompt named that subagent.
A fork is logged and left alone, because it ignores the model field. An
upgrade to a stronger tier is free. A downgrade to a weaker tier is applied
only when the router is confident, so a review never drops to haiku on a
close call. A judgement task never ends up on haiku either way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from . import payload as hook_payload
from . import records, rules, state
from .client import Answer, RouterClient
from .config import Config
from .guard import guarded
from .messages import FLOOR_TEXT, REPLACED_TEXT, SET_TEXT
from .output import PREFIX


@dataclass
class Pick:
    updated_input: Optional[Dict[str, Any]] = None
    message: str = ""
    # True when the message also goes to Claude as additionalContext.
    tell_claude: bool = False


def model_pick(payload: Dict[str, Any], config: Config) -> Optional[Pick]:
    """Ask the router for a tier, log the call, and return the change to make, if any."""
    session = hook_payload.session_id(payload)
    path, current = state.load_for(config.state_dir, payload)
    if current is not None:
        current.n_agent += 1
        guarded(lambda: state.save(path, current), False)
    tool_input = hook_payload.tool_input(payload)
    subagent_type = hook_payload.field_text(payload, "tool_input", "subagent_type")
    description = hook_payload.field_text(payload, "tool_input", "description")
    task = hook_payload.field_text(payload, "tool_input", "prompt")
    given = tool_input.get("model")
    given = None if given is None or given is False or given == "" else given
    call = records.AgentCallRecord(
        session_id=session, turn=current.turn if current else 0, tool=hook_payload.field_text(payload, "tool_name"),
        subagent_type=subagent_type, description=description, prompt=task, model_given=given,
        user_named_subagent=False, verdict=rules.TierVerdict().to_dict(), model_set=given, action="fork",
        tier_margin=None, reason="fork", latency_ms=0, server="none")
    pick = None
    if subagent_type != "fork":
        call.user_named_subagent = rules.user_named_subagent(current.prompt if current else "", subagent_type)
        answer = guarded(lambda: RouterClient.from_config(config).tier(description + "\n" + task), Answer())
        verdict = rules.parse_tier_verdict(answer.body)
        call.verdict, call.latency_ms, call.server = verdict.to_dict(), answer.latency_ms, answer.server
        if call.user_named_subagent:
            call.action, call.reason = "kept", "user_named_subagent"
        elif verdict.tier == "none":
            call.action, call.reason = ("kept" if given is not None else "none"), "router_down"
        else:
            judgement = rules.names_judgement_work(" ".join((description, subagent_type, task[:200])))
            tier, reason, margin = rules.pick_tier(given, verdict.tier, verdict.tier_probs, config.tier_margin,
                                                    judgement)
            call.tier_margin, call.reason = margin, reason
            if tier is None:
                call.action = "kept"
            else:
                call.action, call.model_set = "set", tier
                pick = _set_model(tool_input, given, tier)
                if reason == "judgement_floor":
                    pick = _add_floor_note(pick)
    guarded(lambda: records.append(config.log_file, call, config.log_off), None)
    return pick


def _set_model(tool_input: Dict[str, Any], given: Any, tier: str) -> Pick:
    updated = dict(tool_input, model=tier)
    if given is None or rules.model_text(given).lower() == tier:
        return Pick(updated, PREFIX + SET_TEXT.format(tier=tier))
    return Pick(updated, PREFIX + REPLACED_TEXT.format(tier=tier, given=rules.model_text(given)), tell_claude=True)


def _add_floor_note(pick: Pick) -> Pick:
    """Tell Claude the judgement floor, not just the router, kept this worker off haiku."""
    return Pick(pick.updated_input, (pick.message + " " + FLOOR_TEXT).strip(), tell_claude=True)
