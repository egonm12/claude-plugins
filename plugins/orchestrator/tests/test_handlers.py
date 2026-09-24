"""Unit tests for every hook event, run in-process through handlers.run."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "hooks"))

from orchestrator_hooks import __version__, handlers  # noqa: E402
from orchestrator_hooks.output import HookResult  # noqa: E402

STUB_DELEGATE = json.dumps({
    "route": "delegate", "route_conf": 0.123, "route_probs": {"delegate": 0.66, "self": 0.34},
    "tier": "sonnet", "tier_conf": 0.2, "tier_probs": {"opus": 0.3, "sonnet": 0.5, "haiku": 0.2},
    "latency_ms": 114.2, "by_regex": False})
STUB_SELF = json.dumps({
    "route": "self", "route_conf": 0.3, "route_probs": {"delegate": 0.35, "self": 0.65},
    "tier": "haiku", "tier_conf": 0.1, "tier_probs": {}, "latency_ms": 101.0, "by_regex": False})
STUB_SKILL = json.dumps({
    "route": "skill", "route_conf": 1.0, "route_probs": {}, "tier": "none", "tier_conf": 0.0,
    "tier_probs": {}, "latency_ms": 0.0, "by_regex": True})
STUB_TIER = json.dumps({"tier": "haiku", "tier_conf": 0.4,
                        "tier_probs": {"opus": 0.05, "sonnet": 0.15, "haiku": 0.8}, "latency_ms": 90.1})
# A downgrade candidate whose top two tier probabilities are too close to apply it.
STUB_TIER_CLOSE_HAIKU = json.dumps({"tier": "haiku", "tier_conf": 0.3764,
                                    "tier_probs": {"opus": 0.3317, "sonnet": 0.292, "haiku": 0.3764},
                                    "latency_ms": 90.1})

REMINDER = ("orchestrator: Before you start: if this needs more than two exploratory commands, or it is an "
            "open question such as \"any risks?\", delegate the research to workers. Keep actions and "
            "decisions in the main thread.")
REMINDER_FALLBACK = ("orchestrator: Before you start, decide whether this needs workers. "
                     "Delegate research, keep actions and decisions.")
PROTOCOL_FALLBACK = ("orchestrator is active. Delegate reading and searching to workers, state a model on "
                     "every Agent call, never use fable, and require verified evidence in every worker report.\n")
HINT = ("orchestrator router: this prompt looks like an investigation (delegate, confidence 0.12, tier sonnet). "
        "Delegate the research to a worker before running commands.")
SET_HAIKU = 'orchestrator: the router set model "haiku" for this worker.'
REPLACED_OPUS = 'orchestrator: the router set model "haiku" for this worker, replacing "opus".'
WARN_3_2 = ("orchestrator router: 3 exploratory commands this turn, threshold 2 (verdict delegate). "
            "Hand the rest of the research to a worker.")
TS_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"


def route_stub(route: str, delegate: float, self_: float, by_regex: bool = False, tier: str = "opus") -> str:
    return json.dumps({"route": route, "route_conf": 0.05, "route_probs": {"delegate": delegate, "self": self_},
                       "tier": tier, "tier_conf": 0.3, "tier_probs": {}, "latency_ms": 99.0, "by_regex": by_regex})


# The real verdict that motivated the unsure route: a clear investigation scored as self.
STUB_CLOSE_SELF = route_stub("self", 0.4721, 0.5279)
STUB_CLOSE_DELEGATE = route_stub("delegate", 0.55, 0.45)


class HandlerCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.data = self.tmp / "data"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def env(self, **extra: str) -> Dict[str, str]:
        base = {"CLAUDE_PLUGIN_DATA": str(self.data), "HOME": str(self.tmp),
                "CLAUDE_PLUGIN_ROOT": str(PLUGIN), "ORCHESTRATOR_ROUTER_URL": "http://127.0.0.1:1"}
        base.update(extra)
        return base

    def run_event(self, event: str, payload: Dict[str, Any], **env: str) -> HookResult:
        return handlers.run(event, payload, self.env(**env))

    def state(self, session: str) -> Optional[Dict[str, Any]]:
        try:
            return json.loads((self.data / "state" / (session + ".json")).read_text())
        except OSError:
            return None

    def log(self, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        path = self.data / "router-log.jsonl"
        if not path.exists():
            return []
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        return [row for row in rows if kind is None or row["kind"] == kind]

    def start_turn(self, session: str, stub: str, prompt: str = "look into this for me", **env: str) -> HookResult:
        payload = {"session_id": session, "prompt": prompt, "cwd": "/work"}
        return self.run_event("prompt", payload, ORCHESTRATOR_ROUTER_STUB=stub, **env)

    def agent(self, tool_input: Dict[str, Any], session: str = "s1", tool: str = "Agent",
              **env: str) -> HookResult:
        payload = {"session_id": session, "tool_name": tool, "tool_input": tool_input}
        return self.run_event("agent-call", payload, **env)

    def tool(self, session: str, tool: str, tool_input: Dict[str, Any], **env: str) -> HookResult:
        payload = {"session_id": session, "tool_name": tool, "tool_input": tool_input}
        return self.run_event("tool-call", payload, **env)

    def bash(self, session: str, command: str, **env: str) -> HookResult:
        return self.tool(session, "Bash", {"command": command}, **env)

    def read(self, session: str, **env: str) -> HookResult:
        return self.tool(session, "Read", {"file_path": "/x"}, **env)

    def assert_empty(self, result: HookResult) -> None:
        self.assertEqual((result.stdout, result.stderr, result.exit_code), ("", "", 0))

    def output(self, result: HookResult) -> Dict[str, Any]:
        self.assertEqual((result.stderr, result.exit_code), ("", 0))
        return json.loads(result.stdout)


class SwitchTest(HandlerCase):
    def test_off_switch_silences_every_event(self) -> None:
        payloads = {
            "session-start": {}, "prompt": {"session_id": "s1", "prompt": "x"},
            "agent-call": {"tool_name": "Agent", "tool_input": {"model": "fable"}},
            "tool-call": {"session_id": "s1", "tool_name": "Read", "tool_input": {}},
            "stop": {"session_id": "s1"},
        }
        for event, payload in payloads.items():
            self.assert_empty(self.run_event(event, payload, ORCHESTRATOR_OFF="1",
                                             ORCHESTRATOR_ROUTER_STUB=STUB_DELEGATE))
        self.assertFalse(self.data.exists())

    def test_unknown_event(self) -> None:
        self.assert_empty(self.run_event("nonsense", {"prompt": "x"}))

    def test_router_off(self) -> None:
        off = {"ORCHESTRATOR_ROUTER_OFF": "1", "ORCHESTRATOR_ROUTER_STUB": STUB_DELEGATE}
        start = self.run_event("session-start", {}, **off)
        self.assertEqual(start.stdout, (PLUGIN / "references" / "orchestrator-protocol.md").read_text())
        self.assertEqual(self.start_turn("s1", STUB_DELEGATE, ORCHESTRATOR_ROUTER_OFF="1").stdout,
                         REMINDER + "\n")
        warned = self.output(self.agent({"description": "x"}, ORCHESTRATOR_ROUTER_OFF="1",
                                        ORCHESTRATOR_ROUTER_STUB=STUB_TIER))
        self.assertIn("sets no model", warned["systemMessage"])
        self.assertNotIn("updatedInput", warned["hookSpecificOutput"])
        self.assert_empty(self.read("s1", **off))
        self.assert_empty(self.run_event("stop", {"session_id": "s1"}, **off))
        self.assertFalse(self.data.exists())


class ProtocolAndReminderTest(HandlerCase):
    def test_protocol_loaded(self) -> None:
        result = self.run_event("session-start", {"source": "startup"}, ORCHESTRATOR_ROUTER_STUB="down")
        self.assertEqual(result.stdout, (PLUGIN / "references" / "orchestrator-protocol.md").read_text())

    def test_protocol_fallback(self) -> None:
        for root in (str(self.tmp / "missing"), ""):
            result = self.run_event("session-start", {}, ORCHESTRATOR_ROUTER_STUB="down", CLAUDE_PLUGIN_ROOT=root)
            self.assertEqual(result.stdout, PROTOCOL_FALLBACK)

    def test_reminder_line(self) -> None:
        self.assertEqual(self.start_turn("s1", STUB_SELF).stdout, REMINDER + "\n")

    def test_reminder_fallback(self) -> None:
        result = self.start_turn("s1", STUB_SELF, CLAUDE_PLUGIN_ROOT=str(self.tmp / "missing"))
        self.assertEqual(result.stdout, REMINDER_FALLBACK + "\n")

    def test_broken_router_keeps_reminder_and_protocol(self) -> None:
        with mock.patch("orchestrator_hooks.client.RouterClient.route", side_effect=RuntimeError("boom")):
            self.assertEqual(self.start_turn("s1", STUB_DELEGATE).stdout, REMINDER + "\n")
        self.assertEqual(self.state("s1")["server"], "down")
        with mock.patch("orchestrator_hooks.handlers.start_router", side_effect=RuntimeError("boom")):
            result = self.run_event("session-start", {})
        self.assertTrue(result.stdout.startswith("# "))
        with mock.patch("orchestrator_hooks.client.RouterClient.tier", side_effect=RuntimeError("boom")):
            result = self.agent({"description": "x"}, ORCHESTRATOR_ROUTER_STUB=STUB_TIER)
        self.assertIn("sets no model", self.output(result)["systemMessage"])


class GateTest(HandlerCase):
    def test_fable_denied_in_every_form(self) -> None:
        self.start_turn("s1", STUB_SELF)
        cases = [({"model": "fable", "description": "x"}, "Agent", {}),
                 ({"model": "claude-fable-5-1"}, "Agent", {}),
                 ({"model": "FABLE"}, "Agent", {}),
                 ({"model": "fable"}, "Task", {}),
                 ({"model": "fable"}, "Agent", {"ORCHESTRATOR_MODELS": "opus,fable"}),
                 ({"model": {"name": "fable"}}, "Agent", {})]
        for tool_input, tool, env in cases:
            result = self.agent(tool_input, tool=tool, ORCHESTRATOR_ROUTER_STUB=STUB_TIER, **env)
            self.assertEqual((result.stdout, result.exit_code), ("", 2), tool_input)
            self.assertTrue(result.stderr.startswith(
                "Blocked by orchestrator: this Agent call asks for Fable"), result.stderr)
        self.assertEqual(self.log("agent_call"), [])
        self.assertEqual(self.state("s1")["n_agent"], 0)

    def test_deny_text(self) -> None:
        result = self.agent({"model": "Fable", "description": "count files"})
        self.assertEqual(result.stderr, (
            'Blocked by orchestrator: this Agent call asks for Fable (model "Fable").\n\n'
            "Fable workers are not allowed. Re-issue the call with one of: opus, sonnet, haiku.\n"
            "The orchestrator protocol says which model fits which work.\n\n"
            "Task was: count files\n"))
        self.assertIn("Task was: <no description>\n", self.agent({"model": "fable"}).stderr)

    def test_fable_denied_inside_a_worker(self) -> None:
        payload = {"tool_name": "Agent", "agent_id": "a1", "tool_input": {"model": "fable"}}
        self.assertEqual(self.run_event("agent-call", payload).exit_code, 2)

    def test_warnings_when_router_is_down(self) -> None:
        cases = [({"model": "sonet"}, {}, "not in the allowed list (opus, sonnet, haiku)"),
                 ({"model": "gpt-5"}, {}, "not in the allowed list"),
                 ({"model": "claude-sonnetx"}, {}, "not in the allowed list"),
                 ({"subagent_type": "fork", "model": "opus"}, {}, "This is a fork."),
                 ({"model": "sonnet"}, {"ORCHESTRATOR_MODELS": "opus"}, "allowed list (opus)"),
                 ({"description": "x"}, {}, "This Agent call sets no model.")]
        for tool_input, env, text in cases:
            data = self.output(self.agent(tool_input, ORCHESTRATOR_ROUTER_STUB="down", **env))
            self.assertTrue(data["systemMessage"].startswith("orchestrator: "))
            self.assertIn(text, data["systemMessage"])
            self.assertEqual(data["hookSpecificOutput"]["additionalContext"], data["systemMessage"])
            self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "PreToolUse")
            self.assertNotIn("updatedInput", data["hookSpecificOutput"])

    def test_allowed_models_pass_silently_when_router_is_down(self) -> None:
        for model in ("opus", "claude-sonnet-5", "claude-haiku-4-5-20251001", "claude-opus-5-5[1m]", "Sonnet"):
            self.assert_empty(self.agent({"model": model}, ORCHESTRATOR_ROUTER_STUB="down"))

    def test_other_tool_passes(self) -> None:
        payload = {"tool_name": "Bash", "tool_input": {"model": "fable"}}
        self.assert_empty(self.run_event("agent-call", payload, ORCHESTRATOR_ROUTER_STUB=STUB_TIER))
        self.assert_empty(self.run_event("agent-call", {}, ORCHESTRATOR_ROUTER_STUB=STUB_TIER))

    def test_debug_capture(self) -> None:
        target = self.tmp / "debug.jsonl"
        raw = '{"tool_name":"Agent","tool_input":{"model":"opus"}}'
        handlers.debug_capture("agent-call", raw, self.env(ORCHESTRATOR_DEBUG=str(target)))
        handlers.debug_capture("prompt", "other", self.env(ORCHESTRATOR_DEBUG=str(target)))
        handlers.debug_capture("agent-call", "off", self.env(ORCHESTRATOR_DEBUG=str(target), ORCHESTRATOR_OFF="1"))
        self.assertEqual(target.read_text(), raw + "\n")


class ModelPickTest(HandlerCase):
    task = {"subagent_type": "general-purpose", "description": "count files", "prompt": "count the files in src"}

    def last_call(self) -> Dict[str, Any]:
        return self.log("agent_call")[-1]

    def test_sets_model_on_a_call_without_one(self) -> None:
        self.start_turn("s1", STUB_DELEGATE)
        data = self.output(self.agent(self.task, ORCHESTRATOR_ROUTER_STUB=STUB_TIER))
        self.assertEqual(data["systemMessage"], SET_HAIKU)
        self.assertEqual(data["hookSpecificOutput"], {
            "hookEventName": "PreToolUse", "updatedInput": dict(self.task, model="haiku")})
        call = self.last_call()
        self.assertEqual((call["action"], call["model_given"], call["model_set"], call["server"], call["turn"],
                          call["tool"], call["verdict"]["tier"], call["user_named_subagent"]),
                         ("set", None, "haiku", "stub", 1, "Agent", "haiku", False))
        self.assertEqual((call["description"], call["prompt"]), ("count files", "count the files in src"))
        self.assertEqual(self.state("s1")["n_agent"], 1)

    def test_same_model_gets_the_short_message(self) -> None:
        data = self.output(self.agent({"model": "haiku"}, ORCHESTRATOR_ROUTER_STUB=STUB_TIER))
        self.assertEqual(data["systemMessage"], SET_HAIKU)
        self.assertNotIn("additionalContext", data["hookSpecificOutput"])

    def test_replaces_a_different_model(self) -> None:
        data = self.output(self.agent(dict(self.task, model="opus"), ORCHESTRATOR_ROUTER_STUB=STUB_TIER))
        self.assertEqual(data["systemMessage"], REPLACED_OPUS)
        self.assertEqual(data["hookSpecificOutput"]["additionalContext"], REPLACED_OPUS)
        self.assertEqual(data["hookSpecificOutput"]["updatedInput"]["model"], "haiku")
        self.assertNotIn("permissionDecision", data["hookSpecificOutput"])
        self.assertEqual((self.last_call()["action"], self.last_call()["model_given"]), ("set", "opus"))

    def test_replacement_drops_the_unknown_model_warning(self) -> None:
        stub = json.dumps({"tier": "sonnet", "tier_conf": 0.5, "tier_probs": {}})
        data = self.output(self.agent({"model": "sonet"}, ORCHESTRATOR_ROUTER_STUB=stub))
        replaced = 'orchestrator: the router set model "sonnet" for this worker, replacing "sonet".'
        self.assertEqual(data["hookSpecificOutput"]["updatedInput"]["model"], "sonnet")
        self.assertEqual(data["systemMessage"], replaced)
        self.assertEqual(data["hookSpecificOutput"]["additionalContext"], replaced)
        self.assertNotIn("allowed list", json.dumps(data))

    def test_fork_warning_stands_next_to_the_pick(self) -> None:
        data = self.output(self.agent({"subagent_type": "fork"}, ORCHESTRATOR_ROUTER_STUB=STUB_TIER))
        self.assertIn("This is a fork.", data["systemMessage"])
        self.assertNotIn("sets no model", data["systemMessage"])

    def test_word_inside_another_word_does_not_name_the_subagent(self) -> None:
        self.start_turn("s1", STUB_DELEGATE, prompt="give an explanation of the failing test")
        data = self.output(self.agent({"subagent_type": "Plan", "model": "opus", "description": "x"},
                                      ORCHESTRATOR_ROUTER_STUB=STUB_TIER))
        self.assertEqual(data["hookSpecificOutput"]["updatedInput"]["model"], "haiku")
        call = self.last_call()
        self.assertEqual((call["action"], call["user_named_subagent"], call["model_set"]), ("set", False, "haiku"))

    def test_keeps_model_when_prompt_names_full_type(self) -> None:
        self.start_turn("s1", STUB_DELEGATE, prompt="Please use orchestrator:verifying-worker for this")
        tool_input = {"subagent_type": "orchestrator:verifying-worker", "model": "opus", "description": "x"}
        self.assert_empty(self.agent(tool_input, ORCHESTRATOR_ROUTER_STUB=STUB_TIER))
        call = self.last_call()
        self.assertEqual((call["action"], call["model_set"], call["user_named_subagent"], call["verdict"]["tier"]),
                         ("kept", "opus", True, "haiku"))

    def test_keeps_call_when_prompt_names_last_segment(self) -> None:
        self.start_turn("s1", STUB_DELEGATE, prompt="use the verifying-worker to check it")
        data = self.output(self.agent({"subagent_type": "orchestrator:verifying-worker", "description": "x"},
                                      ORCHESTRATOR_ROUTER_STUB=STUB_TIER))
        self.assertIn("sets no model", data["systemMessage"])
        self.assertNotIn("updatedInput", data["hookSpecificOutput"])
        self.assertEqual((self.last_call()["action"], self.last_call()["model_set"]), ("kept", None))

    def test_fork_is_logged_and_unchanged(self) -> None:
        self.start_turn("s1", STUB_DELEGATE)
        data = self.output(self.agent({"subagent_type": "fork", "model": "opus"}, ORCHESTRATOR_ROUTER_STUB=STUB_TIER))
        self.assertIn("This is a fork.", data["systemMessage"])
        self.assertNotIn("updatedInput", data["hookSpecificOutput"])
        call = self.last_call()
        self.assertEqual((call["action"], call["model_set"], call["server"], call["verdict"]["tier"]),
                         ("fork", "opus", "none", "none"))
        self.assertEqual(self.state("s1")["n_agent"], 1)

    def test_router_down_leaves_the_call_alone(self) -> None:
        self.assert_empty(self.agent({"model": "opus"}, ORCHESTRATOR_ROUTER_STUB="down"))
        self.assertEqual((self.last_call()["action"], self.last_call()["model_set"]), ("kept", "opus"))
        data = self.output(self.agent({"description": "x"}, ORCHESTRATOR_ROUTER_STUB="down"))
        self.assertIn("sets no model", data["systemMessage"])
        call = self.last_call()
        self.assertEqual((call["action"], call["model_set"], call["server"], call["verdict"]),
                         ("none", None, "down", {"tier": "none", "tier_conf": 0, "tier_probs": {}, "tier_wording": None}))
        self.output(self.agent({"description": "x"}, ORCHESTRATOR_ROUTER_STUB='{"tier":"none"}'))
        self.assertEqual((self.last_call()["action"], self.last_call()["server"]), ("none", "stub"))

    def test_worker_calls_are_ignored(self) -> None:
        self.start_turn("s1", STUB_DELEGATE)
        payload = {"session_id": "s1", "tool_name": "Agent", "agent_id": "a3", "tool_input": {"model": "opus"}}
        self.assert_empty(self.run_event("agent-call", payload, ORCHESTRATOR_ROUTER_STUB=STUB_TIER))
        self.assertEqual((self.log("agent_call"), self.state("s1")["n_agent"]), ([], 0))

    def test_without_state(self) -> None:
        data = self.output(self.agent({"description": "x"}, session="t9", ORCHESTRATOR_ROUTER_STUB=STUB_TIER))
        self.assertEqual(data["hookSpecificOutput"]["updatedInput"]["model"], "haiku")
        self.assertEqual(self.last_call()["turn"], 0)
        self.assertIsNone(self.state("t9"))


class ModelPickDowngradeGuardTest(HandlerCase):
    """The downgrade guard, the judgement floor, and the reasons logged for each outcome."""

    def last_call(self) -> Dict[str, Any]:
        return self.log("agent_call")[-1]

    def test_downgrade_is_blocked_on_a_close_margin(self) -> None:
        # The real case: opus 0.3317, sonnet 0.292, haiku 0.3764. Claude gave opus, and it must stay.
        task = {"description": "Spec review of notifier diff",
                "prompt": "Read-only spec-conformance review. Do not change any files.", "model": "opus"}
        self.assert_empty(self.agent(task, ORCHESTRATOR_ROUTER_STUB=STUB_TIER_CLOSE_HAIKU))
        call = self.last_call()
        self.assertEqual((call["action"], call["model_given"], call["model_set"], call["reason"]),
                         ("kept", "opus", "opus", "downgrade_blocked"))
        self.assertEqual(call["tier_margin"], 0.0447)

    def test_downgrade_setting_widens_the_margin_needed(self) -> None:
        self.assert_empty(self.agent(
            {"description": "x", "model": "opus"}, ORCHESTRATOR_ROUTER_STUB=STUB_TIER_CLOSE_HAIKU,
            ORCHESTRATOR_TIER_MARGIN="0.5"))
        self.assertEqual(self.last_call()["reason"], "downgrade_blocked")

    def test_downgrade_guard_disabled_by_zero(self) -> None:
        data = self.output(self.agent({"description": "x", "model": "opus"},
                                      ORCHESTRATOR_ROUTER_STUB=STUB_TIER_CLOSE_HAIKU, ORCHESTRATOR_TIER_MARGIN="0"))
        self.assertEqual(data["hookSpecificOutput"]["updatedInput"]["model"], "haiku")
        self.assertEqual(self.last_call()["reason"], "downgrade")

    def test_upgrade_is_free_regardless_of_margin(self) -> None:
        stub = json.dumps({"tier": "opus", "tier_conf": 0.34, "tier_probs": {"opus": 0.34, "sonnet": 0.33,
                                                                             "haiku": 0.33}})
        data = self.output(self.agent({"model": "haiku", "description": "x"}, ORCHESTRATOR_ROUTER_STUB=stub))
        self.assertEqual(data["hookSpecificOutput"]["updatedInput"]["model"], "opus")
        call = self.last_call()
        self.assertEqual((call["action"], call["reason"]), ("set", "upgrade"))
        self.assertEqual(call["tier_margin"], 0.01)

    def test_no_change_reason_when_the_router_agrees(self) -> None:
        data = self.output(self.agent({"model": "haiku", "description": "x"}, ORCHESTRATOR_ROUTER_STUB=STUB_TIER))
        self.assertEqual(data["hookSpecificOutput"]["updatedInput"]["model"], "haiku")
        self.assertEqual((self.last_call()["action"], self.last_call()["reason"]), ("set", "no_change"))

    def test_no_model_given_reason(self) -> None:
        data = self.output(self.agent({"description": "count files"}, ORCHESTRATOR_ROUTER_STUB=STUB_TIER))
        self.assertEqual(data["hookSpecificOutput"]["updatedInput"]["model"], "haiku")
        self.assertEqual(self.last_call()["reason"], "no_model_given")

    def test_a_model_that_does_not_normalise_counts_as_no_model_given(self) -> None:
        data = self.output(self.agent({"model": "sonet", "description": "x"}, ORCHESTRATOR_ROUTER_STUB=STUB_TIER))
        self.assertEqual(data["hookSpecificOutput"]["updatedInput"]["model"], "haiku")
        self.assertEqual(self.last_call()["reason"], "no_model_given")

    def test_router_down_reason(self) -> None:
        self.output(self.agent({"description": "x"}, ORCHESTRATOR_ROUTER_STUB="down"))
        self.assertEqual(self.last_call()["reason"], "router_down")

    def test_fork_reason(self) -> None:
        self.agent({"subagent_type": "fork"}, ORCHESTRATOR_ROUTER_STUB=STUB_TIER)
        self.assertEqual(self.last_call()["reason"], "fork")

    def test_user_named_subagent_reason(self) -> None:
        self.start_turn("s1", STUB_DELEGATE, prompt="use the verifying-worker for this")
        self.agent({"subagent_type": "orchestrator:verifying-worker", "model": "sonnet", "description": "x"},
                   ORCHESTRATOR_ROUTER_STUB=STUB_TIER)
        self.assertEqual(self.last_call()["reason"], "user_named_subagent")

    def test_judgement_floor_raises_haiku_and_tells_claude(self) -> None:
        data = self.output(self.agent({"description": "security audit of the diff"},
                                      ORCHESTRATOR_ROUTER_STUB=STUB_TIER))
        self.assertEqual(data["hookSpecificOutput"]["updatedInput"]["model"], "sonnet")
        self.assertIn("judgement work", data["systemMessage"])
        self.assertEqual(data["hookSpecificOutput"]["additionalContext"], data["systemMessage"])
        call = self.last_call()
        self.assertEqual((call["action"], call["model_set"], call["reason"]), ("set", "sonnet", "judgement_floor"))

    def test_judgement_floor_reads_the_subagent_type_and_the_prompt_too(self) -> None:
        for changes in ({"subagent_type": "architecture-check"}, {"prompt": "do a security pass, " + "x" * 200}):
            with self.subTest(changes):
                data = self.output(self.agent(dict({"description": "x"}, **changes),
                                              ORCHESTRATOR_ROUTER_STUB=STUB_TIER))
                self.assertEqual(data["hookSpecificOutput"]["updatedInput"]["model"], "sonnet")

    def test_judgement_floor_does_not_fire_past_two_hundred_characters(self) -> None:
        prompt = "x" * 200 + " security review"
        data = self.output(self.agent({"description": "x", "prompt": prompt}, ORCHESTRATOR_ROUTER_STUB=STUB_TIER))
        self.assertEqual(data["hookSpecificOutput"]["updatedInput"]["model"], "haiku")


class PromptTest(HandlerCase):
    def test_hint_on_delegate(self) -> None:
        payload = {"session_id": "s1", "prompt": "why does the build fail", "cwd": "/work"}
        result = self.run_event("prompt", payload, ORCHESTRATOR_ROUTER_STUB=STUB_DELEGATE)
        self.assertEqual(result.stdout, REMINDER + "\n" + HINT + "\n")
        state = self.state("s1")
        self.assertEqual({k: state[k] for k in ("session_id", "turn", "prompt", "route", "route_conf", "tier",
                                                "threshold", "n_exploratory", "n_agent", "n_tool", "warned",
                                                "finalized", "server")},
                         {"session_id": "s1", "turn": 1, "prompt": "why does the build fail", "route": "delegate",
                          "route_conf": 0.123, "tier": "sonnet", "threshold": 2, "n_exploratory": 0, "n_agent": 0,
                          "n_tool": 0, "warned": False, "finalized": False, "server": "stub"})
        self.assertRegex(state["turn_started"], TS_PATTERN)
        record = self.log("prompt")[0]
        self.assertEqual((record["session_id"], record["turn"], record["cwd"], record["text"], record["server"],
                          record["latency_ms"]), ("s1", 1, "/work", "why does the build fail", "stub", 0))
        self.assertEqual(record["verdict"]["route_probs"], {"delegate": 0.66, "self": 0.34})

    def test_silent_on_self_skill_and_down(self) -> None:
        for session, stub, expected in (("a", STUB_SELF, ("self", 5)), ("b", STUB_SKILL, ("skill", 3)),
                                        ("c", "down", ("none", 3)), ("d", "{not json", ("none", 3))):
            self.assertEqual(self.start_turn(session, stub).stdout, REMINDER + "\n")
            state = self.state(session)
            self.assertEqual((state["route"], state["threshold"]), expected)
        self.assertEqual(self.state("c")["server"], "down")
        self.assertEqual(self.log("prompt")[2]["verdict"], {
            "route": "none", "route_conf": 0, "route_probs": {}, "tier": "none", "tier_conf": 0,
            "tier_probs": {}, "by_regex": False, "route_wording": None, "tier_wording": None})

    def test_turn_numbering_and_outcome_on_next_prompt(self) -> None:
        self.start_turn("s1", STUB_DELEGATE)
        self.read("s1")
        self.start_turn("s1", STUB_SELF)
        self.assertEqual((self.state("s1")["turn"], self.state("s1")["threshold"]), (2, 5))
        outcome = self.log("prompt_outcome")
        self.assertEqual([(o["source"], o["turn"], o["n_tool"], o["warned"]) for o in outcome],
                         [("next_prompt", 1, 1, False)])
        self.assertEqual([r["kind"] for r in self.log()], ["prompt", "prompt_outcome", "prompt"])

    def test_payload_edge_cases(self) -> None:
        self.run_event("prompt", {"session_id": "s1", "prompt": "x"}, ORCHESTRATOR_ROUTER_STUB=STUB_SELF)
        self.assertEqual(self.log("prompt")[0]["cwd"], os.getcwd())
        self.run_event("prompt", {"prompt": "x"}, ORCHESTRATOR_ROUTER_STUB=STUB_SELF)
        self.assertEqual(self.state("unknown")["session_id"], "unknown")
        self.start_turn("../../evil", STUB_SELF)
        self.assertEqual(sorted(p.name for p in (self.data / "state").iterdir()),
                         [".._.._evil.json", "s1.json", "unknown.json"])
        self.start_turn("long", STUB_SELF, prompt="a" * 4100)
        self.assertEqual((len(self.log("prompt")[-1]["text"]), len(self.state("long")["prompt"])), (4000, 4000))

    def test_log_off_still_writes_state(self) -> None:
        result = self.start_turn("s1", STUB_DELEGATE, ORCHESTRATOR_LOG_OFF="1")
        self.assertIn(HINT, result.stdout)
        self.assertEqual((self.log(), self.state("s1")["turn"]), ([], 1))

    def test_threshold_overrides(self) -> None:
        self.start_turn("a", STUB_DELEGATE, ORCHESTRATOR_THRESHOLD_DELEGATE="4")
        self.start_turn("b", STUB_SELF, ORCHESTRATOR_THRESHOLD_SELF="7")
        self.start_turn("c", "down", ORCHESTRATOR_THRESHOLD_DEFAULT="1")
        self.start_turn("d", STUB_DELEGATE, ORCHESTRATOR_THRESHOLD_DELEGATE="abc")
        self.assertEqual([self.state(s)["threshold"] for s in "abcd"], [4, 7, 1, 2])

    def test_refused_connection_is_fast(self) -> None:
        start = time.perf_counter()
        payload = {"session_id": "s1", "prompt": "x"}
        self.run_event("prompt", payload, ORCHESTRATOR_ROUTER_TIMEOUT_MS="200")
        self.assertLess(time.perf_counter() - start, 2.0)
        self.assertEqual(self.state("s1")["server"], "down")


class UnsureTest(HandlerCase):
    def effective(self, session: str) -> Dict[str, Any]:
        record = [r for r in self.log("prompt") if r["session_id"] == session][-1]
        return {"route": self.state(session)["route"], "threshold": self.state(session)["threshold"],
                "raw": record["verdict"]["route"], "effective": record["route_effective"],
                "margin": record["margin"], "carried": record["carried_from_turn"]}

    def test_close_verdict_is_unsure_with_the_default_threshold_and_no_hint(self) -> None:
        for session, stub, raw in (("a", STUB_CLOSE_SELF, "self"), ("b", STUB_CLOSE_DELEGATE, "delegate")):
            self.assertEqual(self.start_turn(session, stub).stdout, REMINDER + "\n")
            self.assertEqual(self.effective(session)["route"], "unsure")
            self.assertEqual(self.effective(session)["threshold"], 3)
            self.assertEqual(self.effective(session)["raw"], raw)
            self.assertEqual(self.effective(session)["effective"], "unsure")
        self.assertEqual(self.effective("a")["margin"], 0.0558)
        self.assertEqual(self.effective("a")["carried"], None)

    def test_unsure_threshold_uses_the_default_override(self) -> None:
        self.start_turn("s1", STUB_CLOSE_SELF, ORCHESTRATOR_THRESHOLD_DEFAULT="1", ORCHESTRATOR_THRESHOLD_SELF="9")
        self.assertEqual(self.state("s1")["threshold"], 1)

    def test_clear_verdicts_keep_their_route_and_log_the_margin(self) -> None:
        self.start_turn("a", STUB_DELEGATE)
        self.start_turn("b", STUB_SELF)
        self.assertEqual({k: self.effective("a")[k] for k in ("route", "effective", "margin")},
                         {"route": "delegate", "effective": "delegate", "margin": 0.32})
        self.assertEqual({k: self.effective("b")[k] for k in ("route", "effective", "margin")},
                         {"route": "self", "effective": "self", "margin": 0.3})

    def test_margin_setting(self) -> None:
        cases = (("a", "0.05", "self"), ("b", "0", "self"), ("c", "abc", "unsure"), ("d", "-1", "unsure"),
                 ("e", "", "unsure"), ("f", "nan", "unsure"), ("g", "0.1", "unsure"))
        for session, value, want in cases:
            self.start_turn(session, STUB_CLOSE_SELF, ORCHESTRATOR_ROUTE_MARGIN=value)
            self.assertEqual(self.state(session)["route"], want, value)
        self.start_turn("h", STUB_DELEGATE, ORCHESTRATOR_ROUTE_MARGIN="0.5")
        self.assertEqual(self.state("h")["route"], "unsure")

    def test_regex_verdict_is_never_unsure(self) -> None:
        self.start_turn("s1", route_stub("skill", 0.5, 0.5, by_regex=True), prompt="/commit")
        self.assertEqual((self.state("s1")["route"], self.effective("s1")["effective"]), ("skill", "skill"))

    def test_missing_probs_keep_the_router_route(self) -> None:
        stub = json.dumps({"route": "delegate", "route_conf": 0.123, "tier": "sonnet", "by_regex": False})
        self.assertEqual(self.start_turn("s1", stub).stdout, REMINDER + "\n" + HINT + "\n")
        self.assertEqual((self.state("s1")["route"], self.effective("s1")["margin"]), ("delegate", None))
        self.start_turn("s2", "down")
        self.assertEqual((self.effective("s2")["effective"], self.effective("s2")["margin"]), ("none", None))

    def test_counter_names_the_unsure_route(self) -> None:
        self.start_turn("s1", STUB_CLOSE_SELF)
        for _ in range(3):
            self.assert_empty(self.read("s1"))
        self.assertIn("threshold 3 (verdict unsure)", self.output(self.read("s1"))["systemMessage"])


class CarryTest(HandlerCase):
    def last_prompt(self) -> Dict[str, Any]:
        return self.log("prompt")[-1]

    def test_short_follow_up_carries_a_delegate_verdict_and_its_hint(self) -> None:
        self.start_turn("s1", STUB_DELEGATE, prompt="why does the build fail on main")
        for turn, text in ((2, "continue"), (3, "yes do it"), (4, "go on")):
            result = self.start_turn("s1", STUB_SELF, prompt=text)
            self.assertEqual(result.stdout, REMINDER + "\n" + HINT + "\n", text)
            state = self.state("s1")
            self.assertEqual((state["turn"], state["route"], state["tier"], state["threshold"], state["prompt"]),
                             (turn, "delegate", "sonnet", 2, text))
            record = self.last_prompt()
            self.assertEqual(record["verdict"]["route"], "self")
            self.assertEqual((record["route_effective"], record["carried_from_turn"]), ("delegate", turn - 1))
            self.assertEqual(record["margin"], 0.3)

    def test_longer_prompt_is_judged_on_its_own(self) -> None:
        self.start_turn("s1", STUB_DELEGATE)
        result = self.start_turn("s1", STUB_SELF, prompt="yes, branch and open a PR")
        self.assertEqual(result.stdout, REMINDER + "\n")
        self.assertEqual((self.state("s1")["route"], self.state("s1")["threshold"]), ("self", 5))
        self.assertIsNone(self.last_prompt()["carried_from_turn"])

    def test_first_turn_never_carries(self) -> None:
        self.start_turn("s1", STUB_SELF, prompt="continue")
        self.assertEqual((self.state("s1")["route"], self.last_prompt()["carried_from_turn"]), ("self", None))

    def test_self_and_unsure_carry_without_a_hint(self) -> None:
        self.start_turn("a", STUB_SELF)
        self.start_turn("b", STUB_CLOSE_SELF)
        for session in ("a", "b"):
            self.assertEqual(self.start_turn(session, STUB_DELEGATE, prompt="go on").stdout, REMINDER + "\n")
        self.assertEqual([(self.state(s)["route"], self.state(s)["tier"], self.state(s)["threshold"]) for s in "ab"],
                         [("self", "haiku", 5), ("unsure", "opus", 3)])

    def test_no_carry_after_a_turn_without_a_verdict(self) -> None:
        self.start_turn("s1", "down")
        self.start_turn("s1", STUB_SELF, prompt="continue")
        self.assertEqual((self.state("s1")["route"], self.last_prompt()["carried_from_turn"]), ("self", None))

    def test_slash_command_is_not_carried_over(self) -> None:
        self.start_turn("s1", STUB_DELEGATE)
        self.start_turn("s1", STUB_SKILL, prompt="/commit")
        self.assertEqual((self.state("s1")["route"], self.last_prompt()["carried_from_turn"]), ("skill", None))

    def test_carry_words_setting(self) -> None:
        cases = (("a", "0", "continue", "self"), ("b", "6", "yes, branch and open a PR", "delegate"),
                 ("c", "x", "yes do it", "delegate"), ("d", "x", "please do it now", "self"))
        for session, value, text, want in cases:
            self.start_turn(session, STUB_DELEGATE)
            self.start_turn(session, STUB_SELF, prompt=text, ORCHESTRATOR_CARRY_WORDS=value)
            self.assertEqual(self.state(session)["route"], want, (value, text))

    def test_outcome_of_the_previous_turn_is_still_logged(self) -> None:
        self.start_turn("s1", STUB_DELEGATE)
        self.read("s1")
        self.start_turn("s1", STUB_SELF, prompt="continue")
        self.assertEqual([(o["source"], o["turn"], o["n_tool"]) for o in self.log("prompt_outcome")],
                         [("next_prompt", 1, 1)])
        self.assertEqual([r["kind"] for r in self.log()], ["prompt", "prompt_outcome", "prompt"])


class WorkerReportTest(HandlerCase):
    def report(self, session: str, text: str, **env: str) -> HookResult:
        payload = {"session_id": session, "prompt": text, "cwd": "/work"}
        return self.run_event("prompt", payload, ORCHESTRATOR_ROUTER_STUB=STUB_DELEGATE, **env)

    def test_worker_hand_back_produces_no_output_and_no_prompt_record(self) -> None:
        self.assert_empty(self.report("s1", '<agent-message from="a2c95a8d059e8622e">report</agent-message>'))
        self.assertIsNone(self.state("s1"))
        self.assertEqual(self.log(), [])

    def test_task_notification_produces_no_output(self) -> None:
        self.assert_empty(self.report("s1", "<task-notification>\n<task-id>1</task-id>"))
        self.assertIsNone(self.state("s1"))

    def test_leading_whitespace_is_skipped_before_the_prefix_check(self) -> None:
        self.assert_empty(self.report("s1", '  \n<agent-message from="x">'))

    def test_state_and_counters_are_left_alone(self) -> None:
        self.start_turn("s1", STUB_DELEGATE)
        self.read("s1")
        before = self.state("s1")
        self.assert_empty(self.report("s1", '<agent-message from="x">report</agent-message>'))
        self.assertEqual(self.state("s1"), before)
        self.assertEqual(len(self.log("prompt")), 1)

    def test_reopens_a_finalized_turn(self) -> None:
        self.start_turn("s1", STUB_DELEGATE)
        self.read("s1")
        self.run_event("stop", {"session_id": "s1"})
        self.assertTrue(self.state("s1")["finalized"])
        self.assert_empty(self.report("s1", '<agent-message from="x">report</agent-message>'))
        self.assertFalse(self.state("s1")["finalized"])
        self.assertEqual(len(self.log("prompt_outcome")), 1, "reopening alone must not log an outcome")
        self.read("s1")
        self.run_event("stop", {"session_id": "s1"})
        outcomes = self.log("prompt_outcome")
        self.assertEqual([(o["turn"], o["n_tool"]) for o in outcomes], [(1, 1), (1, 2)])

    def test_router_off_leaves_a_finalized_turn_finalized(self) -> None:
        self.start_turn("s1", STUB_DELEGATE)
        self.run_event("stop", {"session_id": "s1"})
        self.assert_empty(self.report("s1", '<agent-message from="x">report</agent-message>',
                                      ORCHESTRATOR_ROUTER_OFF="1"))
        self.assertTrue(self.state("s1")["finalized"])


class StopTest(HandlerCase):
    def test_outcome_on_stop_without_a_second_record(self) -> None:
        self.start_turn("f1", STUB_DELEGATE)
        self.read("f1")
        self.assert_empty(self.run_event("stop", {"session_id": "f1", "stop_hook_active": False}))
        outcome = self.log("prompt_outcome")
        self.assertEqual([(o["source"], o["turn"], o["n_exploratory"], o["n_agent"], o["n_tool"], o["warned"])
                          for o in outcome], [("stop", 1, 1, 0, 1, False)])
        self.assertTrue(self.state("f1")["finalized"])
        self.assert_empty(self.run_event("stop", {"session_id": "f1"}))
        self.start_turn("f1", STUB_SELF)
        self.assertEqual((len(self.log("prompt_outcome")), self.state("f1")["turn"]), (1, 2))

    def test_missing_state_and_empty_payload(self) -> None:
        self.assert_empty(self.run_event("stop", {"session_id": "nosuch"}))
        self.assert_empty(self.run_event("stop", {}))
        self.assertEqual(self.log(), [])


class CounterTest(HandlerCase):
    def test_worker_payload_and_missing_state_are_ignored(self) -> None:
        self.start_turn("c1", STUB_DELEGATE)
        payload = {"session_id": "c1", "tool_name": "Read", "tool_input": {}, "agent_id": "agent-7"}
        self.assert_empty(self.run_event("tool-call", payload))
        self.assertEqual(self.state("c1")["n_tool"], 0)
        self.assert_empty(self.read("nosuch"))
        self.assertIsNone(self.state("nosuch"))

    def test_counts_and_warns_once(self) -> None:
        self.start_turn("c1", STUB_DELEGATE)
        self.assert_empty(self.read("c1"))
        for command in ("echo hi", "npm test", "git commit -m x"):
            self.assert_empty(self.bash("c1", command))
        self.assertEqual((self.state("c1")["n_tool"], self.state("c1")["n_exploratory"]), (4, 1))
        self.assert_empty(self.bash("c1", "cat a | wc -l"))
        data = self.output(self.bash("c1", "git diff"))
        self.assertEqual(data, {"systemMessage": WARN_3_2, "hookSpecificOutput": {
            "hookEventName": "PreToolUse", "additionalContext": WARN_3_2}})
        self.assertTrue(self.state("c1")["warned"])
        self.assert_empty(self.bash("c1", "cd x && rg foo"))
        self.assertEqual((self.state("c1")["n_tool"], self.state("c1")["n_exploratory"]), (7, 4))
        warnings = self.log("exploration_warning")
        self.assertEqual([(w["turn"], w["n_exploratory"], w["threshold"], w["tool"], w["blocked"]) for w in warnings],
                         [(1, 3, 2, "Bash", False)])
        self.start_turn("c1", STUB_DELEGATE)
        state = self.state("c1")
        self.assertEqual((state["turn"], state["n_tool"], state["n_exploratory"], state["warned"]), (2, 0, 0, False))

    def test_thresholds_after_self_and_down(self) -> None:
        for session, stub, calls, text in (("a", STUB_SELF, 5, "threshold 5 (verdict self)"),
                                           ("b", "down", 3, "threshold 3 (verdict none)")):
            self.start_turn(session, stub)
            for _ in range(calls):
                self.assert_empty(self.read(session))
            self.assertIn(text, self.output(self.read(session))["systemMessage"])

    def test_block_flag_denies(self) -> None:
        self.start_turn("s1", STUB_DELEGATE)
        self.assert_empty(self.read("s1", ORCHESTRATOR_EXPLORATION_BLOCK="1"))
        self.assert_empty(self.read("s1", ORCHESTRATOR_EXPLORATION_BLOCK="1"))
        data = self.output(self.read("s1", ORCHESTRATOR_EXPLORATION_BLOCK="1"))
        self.assertEqual(data, {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": WARN_3_2}})
        self.assertEqual([w["blocked"] for w in self.log("exploration_warning")], [True])

    def test_log_off_writes_no_record_of_any_kind(self) -> None:
        off = {"ORCHESTRATOR_LOG_OFF": "1"}
        self.start_turn("s1", STUB_DELEGATE, **off)
        self.agent({"description": "x"}, ORCHESTRATOR_ROUTER_STUB=STUB_TIER, **off)
        for _ in range(3):
            self.read("s1", **off)
        self.start_turn("s1", STUB_DELEGATE, **off)
        self.run_event("stop", {"session_id": "s1"}, **off)
        self.assertEqual((self.log(), self.state("s1")["finalized"]), ([], True))

    def test_log_off_still_warns(self) -> None:
        self.start_turn("s1", STUB_DELEGATE, ORCHESTRATOR_LOG_OFF="1")
        results = [self.read("s1", ORCHESTRATOR_LOG_OFF="1") for _ in range(3)]
        self.assertIn("additionalContext", results[-1].stdout)
        self.assertEqual(self.log(), [])

    def test_broken_state_fails_open(self) -> None:
        (self.data / "state").mkdir(parents=True)
        (self.data / "state" / "b1.json").write_text("not json")
        self.assert_empty(self.read("b1"))


class LogKindsTest(HandlerCase):
    expected = {
        "prompt": ["kind", "ts", "session_id", "turn", "cwd", "text", "verdict", "route_effective", "margin",
                   "carried_from_turn", "latency_ms", "server", "plugin_version"],
        "prompt_outcome": ["kind", "ts", "session_id", "turn", "n_exploratory", "n_agent", "n_tool", "n_edit",
                           "warned", "source", "duration_s", "context_tokens_start", "context_tokens_end",
                           "plugin_version"],
        "agent_call": ["kind", "ts", "session_id", "turn", "tool", "subagent_type", "description", "prompt",
                       "model_given", "user_named_subagent", "verdict", "model_set", "action", "tier_margin",
                       "reason", "latency_ms", "server", "tool_use_id", "plugin_version"],
        "exploration_warning": ["kind", "ts", "session_id", "turn", "n_exploratory", "threshold", "tool",
                                "blocked", "plugin_version"],
        "agent_result": ["kind", "ts", "session_id", "turn", "agent_id", "agent_type", "tool_use_id", "model",
                         "duration_s", "context_tokens_end", "report_chars", "plugin_version"],
    }

    def test_every_kind_has_the_expected_keys(self) -> None:
        self.start_turn("k1", STUB_DELEGATE)
        self.agent({"description": "x"}, session="k1", ORCHESTRATOR_ROUTER_STUB=STUB_TIER)
        for _ in range(3):
            self.read("k1")
        self.run_event("subagent-stop", {"session_id": "k1", "agent_id": "a1", "agent_type": "Explore"})
        self.run_event("stop", {"session_id": "k1"})
        rows = self.log()
        self.assertEqual([r["kind"] for r in rows],
                         ["prompt", "agent_call", "exploration_warning", "agent_result", "prompt_outcome"])
        for row in rows:
            self.assertEqual(list(row), self.expected[row["kind"]])
            self.assertEqual(row["plugin_version"], __version__)
            self.assertRegex(row["ts"], TS_PATTERN)
            self.assertEqual((row["session_id"], row["turn"]), ("k1", 1))
        self.assertEqual(self.state("k1")["n_agent"], 1)


def transcript_line(ts: str, tokens: tuple, model: str = "claude-opus-5-5", sidechain: bool = False,
                    content: Any = None) -> str:
    usage = {"input_tokens": tokens[0], "cache_read_input_tokens": tokens[1], "cache_creation_input_tokens": tokens[2]}
    return json.dumps({"type": "assistant", "isSidechain": sidechain, "timestamp": ts,
                       "message": {"model": model, "usage": usage, "content": content or []}}) + "\n"


class EditCounterTest(HandlerCase):
    def edit(self, session: str, tool: str = "Edit", agent_id: str = "", **env: str) -> HookResult:
        payload: Dict[str, Any] = {"session_id": session, "tool_name": tool, "tool_input": {"file_path": "/x"}}
        if agent_id:
            payload["agent_id"] = agent_id
        return self.run_event("edit-call", payload, **env)

    def test_counts_every_edit_tool_and_nothing_else(self) -> None:
        self.start_turn("e1", STUB_DELEGATE)
        for tool in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Bash"):
            self.assert_empty(self.edit("e1", tool))
        state = self.state("e1")
        self.assertEqual((state["n_edit"], state["n_tool"], state["n_exploratory"], state["warned"]),
                         (4, 0, 0, False))

    def test_edits_never_warn_and_never_count_as_exploratory(self) -> None:
        self.start_turn("e1", STUB_DELEGATE)
        for _ in range(10):
            self.assert_empty(self.edit("e1"))
        self.assertEqual(self.log("exploration_warning"), [])
        self.assert_empty(self.read("e1"))
        self.assert_empty(self.read("e1"))
        self.assertEqual(self.output(self.read("e1"))["systemMessage"], WARN_3_2)

    def test_skips_workers_router_off_and_no_state(self) -> None:
        self.start_turn("e1", STUB_DELEGATE)
        self.assert_empty(self.edit("e1", agent_id="agent-7"))
        self.assert_empty(self.edit("e1", ORCHESTRATOR_ROUTER_OFF="1"))
        self.assertEqual(self.state("e1")["n_edit"], 0)
        self.assert_empty(self.edit("nosuch"))
        self.assertIsNone(self.state("nosuch"))

    def test_the_outcome_carries_n_edit_and_a_new_turn_resets_it(self) -> None:
        self.start_turn("e1", STUB_DELEGATE)
        self.edit("e1")
        self.edit("e1", "Write")
        self.run_event("stop", {"session_id": "e1"})
        self.assertEqual([o["n_edit"] for o in self.log("prompt_outcome")], [2])
        self.start_turn("e1", STUB_SELF)
        self.assertEqual(self.state("e1")["n_edit"], 0)


class OutcomeMeasuresTest(HandlerCase):
    def setUp(self) -> None:
        super().setUp()
        self.transcript = self.tmp / "session.jsonl"

    def prompt(self, session: str, text: str = "look into this for me") -> HookResult:
        payload = {"session_id": session, "prompt": text, "cwd": "/work", "transcript_path": str(self.transcript)}
        return self.run_event("prompt", payload, ORCHESTRATOR_ROUTER_STUB=STUB_DELEGATE)

    def stop(self, session: str) -> HookResult:
        return self.run_event("stop", {"session_id": session, "transcript_path": str(self.transcript)})

    def add_assistant(self, tokens: tuple) -> None:
        with self.transcript.open("a") as handle:
            handle.write(transcript_line("2026-09-24T08:00:00Z", tokens))

    def test_context_tokens_start_and_end_come_from_the_transcript(self) -> None:
        self.add_assistant((2, 1000, 200))
        self.prompt("m1")
        self.assertEqual(self.state("m1")["context_tokens_start"], 1202)
        self.add_assistant((3, 5000, 400))
        self.stop("m1")
        outcome = self.log("prompt_outcome")[0]
        self.assertEqual((outcome["context_tokens_start"], outcome["context_tokens_end"]), (1202, 5403))

    def test_next_prompt_outcome_reads_the_end_from_the_new_prompt(self) -> None:
        self.add_assistant((0, 100, 0))
        self.prompt("m1")
        self.add_assistant((0, 900, 0))
        self.prompt("m1")
        outcome = self.log("prompt_outcome")[0]
        self.assertEqual((outcome["source"], outcome["context_tokens_start"], outcome["context_tokens_end"]),
                         ("next_prompt", 100, 900))
        self.assertEqual(self.state("m1")["context_tokens_start"], 900)

    def test_no_or_broken_transcript_gives_null(self) -> None:
        self.start_turn("m1", STUB_DELEGATE)
        self.run_event("stop", {"session_id": "m1"})
        self.transcript.write_text("{not json\n")
        self.prompt("m2")
        self.stop("m2")
        for outcome in self.log("prompt_outcome"):
            self.assertEqual((outcome["context_tokens_start"], outcome["context_tokens_end"]), (None, None))
        self.assertIsNone(self.state("m2")["context_tokens_start"])

    def test_duration_is_whole_seconds_from_the_turn_start(self) -> None:
        self.prompt("m1")
        state_file = self.data / "state" / "m1.json"
        state = json.loads(state_file.read_text())
        started = time.gmtime(time.time() - 42)
        state["turn_started"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", started)
        state_file.write_text(json.dumps(state))
        self.stop("m1")
        duration = self.log("prompt_outcome")[0]["duration_s"]
        self.assertIsInstance(duration, int)
        self.assertIn(duration, (42, 43))

    def test_broken_turn_start_gives_null_duration(self) -> None:
        self.prompt("m1")
        state_file = self.data / "state" / "m1.json"
        state = json.loads(state_file.read_text())
        state["turn_started"] = "later"
        state_file.write_text(json.dumps(state))
        self.stop("m1")
        self.assertIsNone(self.log("prompt_outcome")[0]["duration_s"])

    def test_a_reopened_turn_keeps_its_start_values(self) -> None:
        self.add_assistant((0, 100, 0))
        self.prompt("m1")
        started = self.state("m1")["turn_started"]
        self.add_assistant((0, 300, 0))
        self.stop("m1")
        self.add_assistant((0, 700, 0))
        payload = {"session_id": "m1", "prompt": "<task-notification>\n<task-id>1</task-id>",
                   "transcript_path": str(self.transcript)}
        self.assert_empty(self.run_event("prompt", payload, ORCHESTRATOR_ROUTER_STUB=STUB_DELEGATE))
        self.assertEqual((self.state("m1")["context_tokens_start"], self.state("m1")["turn_started"]), (100, started))
        self.add_assistant((0, 900, 0))
        self.stop("m1")
        self.assertEqual([(o["context_tokens_start"], o["context_tokens_end"]) for o in self.log("prompt_outcome")],
                         [(100, 300), (100, 900)])


class SubagentStopTest(HandlerCase):
    def setUp(self) -> None:
        super().setUp()
        self.agent_dir = self.tmp / "session" / "subagents"
        self.agent_dir.mkdir(parents=True)
        self.agent_file = self.agent_dir / "agent-a1.jsonl"

    def stop_payload(self, **extra: Any) -> Dict[str, Any]:
        payload = {"session_id": "s1", "hook_event_name": "SubagentStop", "stop_hook_active": False,
                   "agent_id": "a1", "agent_type": "orchestrator:verifying-worker",
                   "agent_transcript_path": str(self.agent_file), "last_assistant_message": "closing text"}
        payload.update(extra)
        return payload

    def write_agent(self, handback: str = "") -> None:
        rows = [json.dumps({"type": "user", "isSidechain": True, "timestamp": "2026-09-23T20:01:32.000Z"}) + "\n",
                transcript_line("2026-09-23T20:01:40.000Z", (1, 2, 3), "claude-sonnet-5", True)]
        if handback:
            content = [{"type": "tool_use", "name": "SubagentHandback", "input": {"message": handback}}]
            rows.append(transcript_line("2026-09-23T20:05:00.000Z", (2, 45745, 2484), "claude-sonnet-5", True,
                                        content))
        rows.append(transcript_line("2026-09-23T20:05:02.500Z", (2, 46000, 100), "claude-sonnet-5", True))
        self.agent_file.write_text("".join(rows))
        meta = {"agentType": "orchestrator:verifying-worker", "toolUseId": "toolu_01Cc", "model": "sonnet"}
        (self.agent_dir / "agent-a1.meta.json").write_text(json.dumps(meta))

    def test_writes_an_agent_result_and_prints_nothing(self) -> None:
        self.start_turn("s1", STUB_DELEGATE)
        self.write_agent(handback="x" * 3911)
        self.assert_empty(self.run_event("subagent-stop", self.stop_payload()))
        record = self.log("agent_result")[0]
        self.assertEqual({k: record[k] for k in ("session_id", "turn", "agent_id", "agent_type", "tool_use_id",
                                                 "model", "duration_s", "context_tokens_end", "report_chars")},
                         {"session_id": "s1", "turn": 1, "agent_id": "a1",
                          "agent_type": "orchestrator:verifying-worker", "tool_use_id": "toolu_01Cc",
                          "model": "claude-sonnet-5", "duration_s": 210.5, "context_tokens_end": 46102,
                          "report_chars": 3911})
        self.assertRegex(record["ts"], TS_PATTERN)

    def test_without_handback_the_report_is_the_last_message(self) -> None:
        self.write_agent()
        self.run_event("subagent-stop", self.stop_payload())
        self.assertEqual(self.log("agent_result")[0]["report_chars"], len("closing text"))
        self.run_event("subagent-stop", self.stop_payload(last_assistant_message=None))
        self.assertIsNone(self.log("agent_result")[1]["report_chars"])

    def test_internal_agent_without_transcript_or_state(self) -> None:
        self.assert_empty(self.run_event("subagent-stop", {"session_id": "s9", "agent_id": "a9", "agent_type": ""}))
        record = self.log("agent_result")[0]
        self.assertEqual((record["turn"], record["agent_type"], record["model"], record["duration_s"],
                          record["context_tokens_end"], record["tool_use_id"], record["report_chars"]),
                         (0, "", None, None, None, None, None))

    def test_bad_payloads_never_break_the_hook(self) -> None:
        for payload in ({}, {"agent_transcript_path": 3, "last_assistant_message": ["x"]},
                        {"agent_transcript_path": str(self.agent_dir)}):
            with self.subTest(repr(payload)):
                self.assert_empty(self.run_event("subagent-stop", payload))

    def test_switches(self) -> None:
        self.assert_empty(self.run_event("subagent-stop", self.stop_payload(), ORCHESTRATOR_ROUTER_OFF="1"))
        self.assert_empty(self.run_event("subagent-stop", self.stop_payload(), ORCHESTRATOR_LOG_OFF="1"))
        self.assert_empty(self.run_event("subagent-stop", self.stop_payload(), ORCHESTRATOR_OFF="1"))
        self.assertEqual(self.log(), [])


class AgentCallLinkTest(HandlerCase):
    def test_agent_call_logs_the_tool_use_id(self) -> None:
        self.start_turn("s1", STUB_DELEGATE)
        payload = {"session_id": "s1", "tool_name": "Agent", "tool_input": {"description": "x", "model": "opus"},
                   "tool_use_id": "toolu_01Cc"}
        self.run_event("agent-call", payload, ORCHESTRATOR_ROUTER_STUB=STUB_TIER)
        self.agent({"description": "y"}, session="s1", ORCHESTRATOR_ROUTER_STUB=STUB_TIER)
        self.assertEqual([r["tool_use_id"] for r in self.log("agent_call")], ["toolu_01Cc", None])


class WordingLogTest(HandlerCase):
    def test_prompt_record_keeps_the_wording_ids(self) -> None:
        stub = dict(json.loads(STUB_DELEGATE), route_wording="a-2026-09-23", tier_wording="b-2026-09-24")
        self.start_turn("s1", json.dumps(stub))
        verdict = self.log("prompt")[0]["verdict"]
        self.assertEqual((verdict["route_wording"], verdict["tier_wording"]), ("a-2026-09-23", "b-2026-09-24"))

    def test_agent_call_record_keeps_the_wording_id(self) -> None:
        self.start_turn("s1", STUB_DELEGATE)
        stub = dict(json.loads(STUB_TIER), tier_wording="b-2026-09-24")
        self.agent({"description": "x"}, ORCHESTRATOR_ROUTER_STUB=json.dumps(stub))
        self.assertEqual(self.log("agent_call")[0]["verdict"]["tier_wording"], "b-2026-09-24")

    def test_answer_without_wording_logs_null(self) -> None:
        # A router from before 0.5.5 sends no wording id. The hooks still act and log null.
        self.start_turn("s1", STUB_DELEGATE)
        self.agent({"description": "x"}, ORCHESTRATOR_ROUTER_STUB=STUB_TIER)
        self.assertEqual(self.log("prompt")[0]["verdict"]["route"], "delegate")
        self.assertIsNone(self.log("prompt")[0]["verdict"]["tier_wording"])
        call = self.log("agent_call")[0]
        self.assertEqual((call["model_set"], call["verdict"]["tier_wording"]), ("haiku", None))


class RouterStartCase(HandlerCase):
    """A temporary plugin with a fake router Python that records its arguments."""

    def setUp(self) -> None:
        super().setUp()
        self.plugin = self.tmp / "plugin"
        (self.plugin / "router").mkdir(parents=True)
        (self.plugin / "references").mkdir()
        (self.plugin / "references" / "orchestrator-protocol.md").write_text("# Protocol\n")
        self.args = self.tmp / "fake-args"
        self.fake = self.tmp / "fake-python"
        self.fake.write_text('#!/bin/sh\nprintf \'%%s\\n\' "$*" >>"%s"\nexit 0\n' % self.args)
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IXUSR)

    def start(self, **env: str) -> HookResult:
        base = {"CLAUDE_PLUGIN_ROOT": str(self.plugin), "ORCHESTRATOR_ROUTER_PYTHON": str(self.fake)}
        base.update(env)
        return self.run_event("session-start", {}, **base)

    def wait_for_args(self) -> str:
        for _ in range(50):
            if self.args.exists() and self.args.read_text():
                break
            time.sleep(0.05)
        pid = int((self.data / "router-server.pid").read_text())
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        return self.args.read_text() if self.args.exists() else ""


class RouterStartTest(RouterStartCase):
    def test_silent_paths(self) -> None:
        self.assertEqual(self.start().stdout, "# Protocol\n")
        (self.plugin / "router" / "server.py").write_text("")
        self.assertEqual(self.start(ORCHESTRATOR_ROUTER_STUB=STUB_SELF).stdout, "# Protocol\n")
        self.assertEqual(self.start(ORCHESTRATOR_ROUTER_PYTHON=str(self.tmp / "missing")).stdout, "# Protocol\n")
        self.assertEqual(self.start(ORCHESTRATOR_ROUTER_OFF="1").stdout, "# Protocol\n")
        self.data.mkdir()
        (self.data / "router-server.pid").write_text("%d\n" % os.getpid())
        self.assertEqual(self.start().stdout, "# Protocol\n")
        self.assertFalse(self.args.exists())

    def test_launches_after_a_dead_pid(self) -> None:
        (self.plugin / "router" / "server.py").write_text("")
        self.data.mkdir()
        (self.data / "router-server.pid").write_text("999999\n")
        result = self.start()
        self.assertEqual(result.stdout, "# Protocol\norchestrator router: starting the router daemon on "
                                        "http://127.0.0.1:1. First answers arrive after the model loads.\n")
        self.assertNotEqual((self.data / "router-server.pid").read_text().strip(), "999999")
        self.assertEqual(self.wait_for_args(), "%s --port 1\n" % (self.plugin / "router" / "server.py"))
        self.assertTrue((self.data / "router-server.log").exists())

    def test_default_port(self) -> None:
        (self.plugin / "router" / "server.py").write_text("")
        result = self.start(ORCHESTRATOR_ROUTER_URL="http://127.0.0.1")
        self.assertIn("starting the router daemon on http://127.0.0.1.", result.stdout)
        self.assertTrue(self.wait_for_args().endswith("--port 8790\n"))


class RouterRestartTest(RouterStartCase):
    """An outdated daemon answers /health. No test here sends a real signal to any process."""

    OLD_PID = 424242
    ROUTER_COMMAND = "/data/router-venv/bin/python /plugin/router/server.py --port 8790"

    def setUp(self) -> None:
        super().setUp()
        (self.plugin / "router" / "server.py").write_text("")
        self.data.mkdir()
        (self.data / "router-server.pid").write_text("%d\n" % self.OLD_PID)
        self.terminate = self.patch("_terminate", return_value=True)
        self.alive = self.patch("_alive", return_value=True)
        self.command = self.patch("_command_line", return_value=self.ROUTER_COMMAND)
        # The first health check sees the old daemon. Each later one, in the wait loop, sees the port free.
        self.health_info = self.patch("RouterClient.health_info", target="orchestrator_hooks.daemon",
                                      return_value={"status": "ok", "plugin_version": "0.0.1"})
        self.health = self.patch("RouterClient.health", target="orchestrator_hooks.daemon", return_value=False)

    def patch(self, name: str, target: str = "orchestrator_hooks.daemon", **kwargs: Any) -> mock.MagicMock:
        patcher = mock.patch(target + "." + name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def restart_line(self, old: str) -> str:
        return ("orchestrator router: restarting the router daemon on http://127.0.0.1:1, because it runs "
                "version %s and the plugin is version %s. First answers arrive after the model loads." % (old, __version__))

    def outdated_line(self, old: str = "0.0.1") -> str:
        return ("orchestrator router: the router daemon on http://127.0.0.1:1 runs version %s, but the plugin is "
                "version %s. Stop the process on port 1 (lsof -ti tcp:1 shows it), then start a new session."
                % (old, __version__))

    def assert_not_stopped(self) -> None:
        self.terminate.assert_not_called()
        self.assertFalse(self.args.exists())
        self.assertEqual((self.data / "router-server.pid").read_text(), "%d\n" % self.OLD_PID)

    def test_version_mismatch_restarts(self) -> None:
        result = self.start()
        self.assertEqual(result.stdout, "# Protocol\n" + self.restart_line("0.0.1") + "\n")
        self.command.assert_called_once_with(self.OLD_PID)
        self.terminate.assert_called_once_with(self.OLD_PID)
        self.assertNotEqual((self.data / "router-server.pid").read_text().strip(), str(self.OLD_PID))
        self.assertEqual(self.wait_for_args(), "%s --port 1\n" % (self.plugin / "router" / "server.py"))

    def test_daemon_without_version_restarts(self) -> None:
        for body in ({"status": "ok", "device": "mps"}, {}, {"plugin_version": 5}):
            with self.subTest(body=body):
                self.health_info.return_value = body
                if self.args.exists():
                    self.args.unlink()
                result = self.start()
                self.assertIn(self.restart_line("unknown"), result.stdout)
                self.wait_for_args()
                (self.data / "router-server.pid").write_text("%d\n" % self.OLD_PID)

    def test_matching_version_does_nothing(self) -> None:
        self.health_info.return_value = {"status": "ok", "plugin_version": __version__}
        self.assertEqual(self.start().stdout, "# Protocol\n")
        self.command.assert_not_called()
        self.assert_not_stopped()

    def test_unconfirmed_pid_is_not_stopped(self) -> None:
        cases = {
            "other program": lambda: setattr(self.command, "return_value", "/usr/bin/vim notes.md"),
            "ps gives nothing": lambda: setattr(self.command, "return_value", ""),
            "dead pid": lambda: setattr(self.alive, "return_value", False),
            "no pid file": lambda: (self.data / "router-server.pid").unlink(),
            "junk pid file": lambda: (self.data / "router-server.pid").write_text("abc\n"),
        }
        for label, arrange in cases.items():
            with self.subTest(label):
                self.command.return_value, self.alive.return_value = self.ROUTER_COMMAND, True
                (self.data / "router-server.pid").write_text("%d\n" % self.OLD_PID)
                arrange()
                result = self.start()
                self.assertEqual(result.stdout, "# Protocol\n" + self.outdated_line() + "\n")
                self.terminate.assert_not_called()
                self.assertFalse(self.args.exists())

    def test_no_new_daemon_to_start_keeps_the_old_one(self) -> None:
        (self.plugin / "router" / "server.py").unlink()
        self.assertEqual(self.start().stdout, "# Protocol\n" + self.outdated_line() + "\n")
        self.assert_not_stopped()

    def test_failed_signal_does_not_start(self) -> None:
        self.terminate.return_value = False
        self.assertEqual(self.start().stdout, "# Protocol\n" + self.outdated_line() + "\n")
        self.assertFalse(self.args.exists())

    def test_port_still_busy_does_not_start(self) -> None:
        self.health.return_value = True
        with mock.patch("orchestrator_hooks.daemon.STOP_WAIT_S", 0.2):
            result = self.start()
        self.assertEqual(result.stdout, "# Protocol\norchestrator router: stopped the outdated router daemon on "
                                        "http://127.0.0.1:1, but its port is still busy. The next session starts "
                                        "the new one.\n")
        self.terminate.assert_called_once_with(self.OLD_PID)
        self.assertFalse(self.args.exists())

    def test_stub_skips_the_version_check(self) -> None:
        self.assertEqual(self.start(ORCHESTRATOR_ROUTER_STUB=STUB_SELF).stdout, "# Protocol\n")
        self.health_info.assert_not_called()
        self.assert_not_stopped()


class CommandLineTest(unittest.TestCase):
    """The ps check on processes that are safe to look at. Nothing is stopped."""

    def test_own_process(self) -> None:
        from orchestrator_hooks import daemon
        self.assertIn("python", daemon._command_line(os.getpid()).lower())

    def test_missing_process(self) -> None:
        from orchestrator_hooks import daemon
        self.assertEqual(daemon._command_line(999999), "")
        self.assertFalse(daemon._alive(999999))


if __name__ == "__main__":
    unittest.main()
