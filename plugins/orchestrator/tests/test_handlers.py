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

from orchestrator_hooks import handlers  # noqa: E402
from orchestrator_hooks.output import HookResult  # noqa: E402

STUB_DELEGATE = json.dumps({
    "route": "delegate", "route_conf": 0.123, "route_probs": {"delegate": 0.56, "self": 0.44},
    "tier": "sonnet", "tier_conf": 0.2, "tier_probs": {"opus": 0.3, "sonnet": 0.5, "haiku": 0.2},
    "latency_ms": 114.2, "by_regex": False})
STUB_SELF = json.dumps({
    "route": "self", "route_conf": 0.3, "route_probs": {"delegate": 0.35, "self": 0.65},
    "tier": "haiku", "tier_conf": 0.1, "tier_probs": {}, "latency_ms": 101.0, "by_regex": False})
STUB_SKILL = json.dumps({
    "route": "skill", "route_conf": 1.0, "route_probs": {}, "tier": "none", "tier_conf": 0.0,
    "tier_probs": {}, "latency_ms": 0.0, "by_regex": True})
STUB_TIER = json.dumps({"tier": "haiku", "tier_conf": 0.4,
                        "tier_probs": {"opus": 0.1, "sonnet": 0.5, "haiku": 0.4}, "latency_ms": 90.1})

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

    def start_turn(self, session: str, stub: str, prompt: str = "a prompt", **env: str) -> HookResult:
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
                         ("none", None, "down", {"tier": "none", "tier_conf": 0, "tier_probs": {}}))
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
        self.assertEqual(record["verdict"]["route_probs"], {"delegate": 0.56, "self": 0.44})

    def test_silent_on_self_skill_and_down(self) -> None:
        for session, stub, expected in (("a", STUB_SELF, ("self", 5)), ("b", STUB_SKILL, ("skill", 3)),
                                        ("c", "down", ("none", 3)), ("d", "{not json", ("none", 3))):
            self.assertEqual(self.start_turn(session, stub).stdout, REMINDER + "\n")
            state = self.state(session)
            self.assertEqual((state["route"], state["threshold"]), expected)
        self.assertEqual(self.state("c")["server"], "down")
        self.assertEqual(self.log("prompt")[2]["verdict"], {
            "route": "none", "route_conf": 0, "route_probs": {}, "tier": "none", "tier_conf": 0,
            "tier_probs": {}, "by_regex": False})

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
        "prompt": ["kind", "ts", "session_id", "turn", "cwd", "text", "verdict", "latency_ms", "server"],
        "prompt_outcome": ["kind", "ts", "session_id", "turn", "n_exploratory", "n_agent", "n_tool", "warned",
                           "source"],
        "agent_call": ["kind", "ts", "session_id", "turn", "tool", "subagent_type", "description", "prompt",
                       "model_given", "user_named_subagent", "verdict", "model_set", "action", "latency_ms",
                       "server"],
        "exploration_warning": ["kind", "ts", "session_id", "turn", "n_exploratory", "threshold", "tool",
                                "blocked"],
    }

    def test_every_kind_has_the_expected_keys(self) -> None:
        self.start_turn("k1", STUB_DELEGATE)
        self.agent({"description": "x"}, session="k1", ORCHESTRATOR_ROUTER_STUB=STUB_TIER)
        for _ in range(3):
            self.read("k1")
        self.run_event("stop", {"session_id": "k1"})
        rows = self.log()
        self.assertEqual([r["kind"] for r in rows], ["prompt", "agent_call", "exploration_warning", "prompt_outcome"])
        for row in rows:
            self.assertEqual(list(row), self.expected[row["kind"]])
            self.assertRegex(row["ts"], TS_PATTERN)
            self.assertEqual((row["session_id"], row["turn"]), ("k1", 1))
        self.assertEqual(self.state("k1")["n_agent"], 1)


class RouterStartTest(HandlerCase):
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


if __name__ == "__main__":
    unittest.main()
