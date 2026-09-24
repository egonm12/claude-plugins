"""Unit tests for the training log records."""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))

from orchestrator_hooks import __version__, records  # noqa: E402

TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
ROUTE_VERDICT = {"route": "delegate", "route_conf": 0.12, "route_probs": {}, "tier": "sonnet",
                 "tier_conf": 0.2, "tier_probs": {}, "by_regex": False}
TIER_VERDICT = {"tier": "opus", "tier_conf": 0.1, "tier_probs": {}}


def prompt_record(text: str = "why") -> records.PromptRecord:
    return records.PromptRecord(session_id="s1", turn=3, cwd="/work", text=text,
                                verdict=ROUTE_VERDICT, latency_ms=114, server="ok",
                                route_effective="unsure", margin=0.0558, carried_from_turn=None)


def agent_record(**changes: object) -> records.AgentCallRecord:
    fields = dict(session_id="s1", turn=3, tool="Agent", subagent_type="general-purpose",
                  description="d", prompt="p", model_given=None, user_named_subagent=False,
                  verdict=TIER_VERDICT, model_set="opus", action="set", tier_margin=0.3, reason="upgrade",
                  latency_ms=157, server="ok")
    fields.update(changes)
    return records.AgentCallRecord(**fields)  # type: ignore[arg-type]


class ShapeTest(unittest.TestCase):
    def assert_shape(self, data: dict, keys: list, types: dict) -> None:
        self.assertEqual(list(data), keys + ["plugin_version"])
        self.assertEqual(data["plugin_version"], __version__)
        self.assertRegex(data["ts"], TS)
        for key, kind in types.items():
            self.assertIsInstance(data[key], kind, key)

    def test_prompt(self) -> None:
        data = prompt_record().to_json()
        self.assert_shape(data, ["kind", "ts", "session_id", "turn", "cwd", "text", "verdict",
                                 "route_effective", "margin", "carried_from_turn", "latency_ms", "server"],
                          {"turn": int, "text": str, "verdict": dict, "latency_ms": int})
        self.assertEqual(data["kind"], "prompt")
        self.assertEqual(data["verdict"], ROUTE_VERDICT)
        self.assertEqual((data["route_effective"], data["margin"], data["carried_from_turn"]),
                         ("unsure", 0.0558, None))

    def test_prompt_outcome(self) -> None:
        data = records.PromptOutcomeRecord(session_id="s1", turn=3, n_exploratory=5, n_agent=0,
                                           n_tool=7, warned=True, source="stop", n_edit=2, duration_s=41,
                                           context_tokens_start=1200, context_tokens_end=5400).to_json()
        self.assert_shape(data, ["kind", "ts", "session_id", "turn", "n_exploratory", "n_agent",
                                 "n_tool", "n_edit", "warned", "source", "duration_s",
                                 "context_tokens_start", "context_tokens_end"],
                          {"n_exploratory": int, "n_agent": int, "n_tool": int, "n_edit": int, "warned": bool})
        self.assertEqual((data["kind"], data["source"]), ("prompt_outcome", "stop"))
        self.assertEqual((data["n_edit"], data["duration_s"], data["context_tokens_start"],
                          data["context_tokens_end"]), (2, 41, 1200, 5400))

    def test_prompt_outcome_new_fields_default(self) -> None:
        data = records.PromptOutcomeRecord(session_id="s1", turn=3, n_exploratory=0, n_agent=0,
                                           n_tool=0, warned=False, source="stop").to_json()
        self.assertEqual((data["n_edit"], data["duration_s"], data["context_tokens_start"],
                          data["context_tokens_end"]), (0, None, None, None))

    def test_agent_result(self) -> None:
        data = records.AgentResultRecord(session_id="s1", turn=3, agent_id="a1", agent_type="Explore",
                                         tool_use_id="toolu_01", model="claude-sonnet-5", duration_s=146.2,
                                         context_tokens_end=48231, report_chars=3911).to_json()
        self.assert_shape(data, ["kind", "ts", "session_id", "turn", "agent_id", "agent_type", "tool_use_id",
                                 "model", "duration_s", "context_tokens_end", "report_chars"],
                          {"turn": int, "duration_s": float, "context_tokens_end": int, "report_chars": int})
        self.assertEqual((data["kind"], data["model"], data["tool_use_id"]),
                         ("agent_result", "claude-sonnet-5", "toolu_01"))

    def test_agent_call(self) -> None:
        data = agent_record().to_json()
        self.assert_shape(data, ["kind", "ts", "session_id", "turn", "tool", "subagent_type",
                                 "description", "prompt", "model_given", "user_named_subagent",
                                 "verdict", "model_set", "action", "tier_margin", "reason",
                                 "latency_ms", "server", "tool_use_id"],
                          {"user_named_subagent": bool, "verdict": dict, "latency_ms": int})
        self.assertIsNone(data["tool_use_id"])
        self.assertEqual(agent_record(tool_use_id="toolu_01").to_json()["tool_use_id"], "toolu_01")
        self.assertEqual(data["kind"], "agent_call")
        self.assertIsNone(data["model_given"])
        self.assertEqual(data["verdict"], TIER_VERDICT)
        self.assertEqual((data["tier_margin"], data["reason"]), (0.3, "upgrade"))

    def test_agent_call_tier_margin_can_be_null(self) -> None:
        data = agent_record(tier_margin=None, reason="fork").to_json()
        self.assertEqual((data["tier_margin"], data["reason"]), (None, "fork"))

    def test_exploration_warning(self) -> None:
        data = records.ExplorationWarningRecord(session_id="s1", turn=3, n_exploratory=3,
                                                threshold=2, tool="Bash", blocked=False).to_json()
        self.assert_shape(data, ["kind", "ts", "session_id", "turn", "n_exploratory", "threshold",
                                 "tool", "blocked"],
                          {"n_exploratory": int, "threshold": int, "blocked": bool})
        self.assertEqual(data["kind"], "exploration_warning")

    def test_text_truncation(self) -> None:
        self.assertEqual(len(prompt_record("a" * 4100).to_json()["text"]), 4000)
        data = agent_record(description="b" * 5000, prompt="c" * 4001).to_json()
        self.assertEqual((len(data["description"]), len(data["prompt"])), (4000, 4000))

    def test_now_format(self) -> None:
        self.assertRegex(records.now_iso(), TS)


class AppendTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.log = Path(self._tmp.name) / "data" / "router-log.jsonl"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_append_writes_one_line_per_record(self) -> None:
        records.append(self.log, prompt_record())
        records.append(self.log, agent_record())
        lines = self.log.read_text().splitlines()
        self.assertEqual([json.loads(line)["kind"] for line in lines], ["prompt", "agent_call"])

    def test_log_off_writes_nothing(self) -> None:
        records.append(self.log, prompt_record(), log_off=True)
        self.assertFalse(self.log.exists())

    def test_unwritable_path_does_not_raise(self) -> None:
        blocker = Path(self._tmp.name) / "file"
        blocker.write_text("x")
        records.append(blocker / "router-log.jsonl", prompt_record())
        self.assertEqual(blocker.read_text(), "x")


if __name__ == "__main__":
    unittest.main()
