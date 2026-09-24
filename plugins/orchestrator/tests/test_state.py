"""Unit tests for the per-session state record."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))

from orchestrator_hooks import payload, state  # noqa: E402


class StateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "state" / "s1.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_round_trip(self) -> None:
        record = state.TurnState(
            session_id="s1", turn=3, turn_started="2026-09-23T14:00:00Z", prompt="use the explore agent",
            route="delegate", route_conf=0.12, tier="sonnet", threshold=2,
            n_exploratory=1, n_agent=2, n_tool=3, warned=True, finalized=False, server="ok",
            n_edit=4, context_tokens_start=179353,
        )
        self.assertTrue(state.save(self.path, record))
        self.assertEqual(state.load(self.path), record)
        written = json.loads(self.path.read_text())
        self.assertEqual(list(written), [
            "session_id", "turn", "turn_started", "prompt", "route", "route_conf", "tier",
            "threshold", "n_exploratory", "n_agent", "n_tool", "warned", "finalized", "server",
            "n_edit", "context_tokens_start",
        ])
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["s1.json"])

    def test_missing_file(self) -> None:
        self.assertIsNone(state.load(self.path))

    def test_broken_json(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text("not json")
        self.assertIsNone(state.load(self.path))
        self.path.write_text("[1, 2]")
        self.assertIsNone(state.load(self.path))
        self.path.write_text('{"turn": Infinity}')
        self.assertIsNone(state.load(self.path))

    def test_extra_keys_and_odd_types(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({
            "session_id": "s1", "turn": 2.7, "n_tool": "x", "warned": "yes",
            "threshold": 4, "something_new": [1],
        }))
        loaded = state.load(self.path)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual((loaded.turn, loaded.n_tool, loaded.warned, loaded.threshold), (2, 0, False, 4))
        self.assertEqual(loaded.route, "none")

    def test_context_tokens_start_is_a_whole_number_or_null(self) -> None:
        self.path.parent.mkdir(parents=True)
        for stored, expected in ((1200, 1200), (12.9, 12), (None, None), ("x", None), (True, None)):
            with self.subTest(repr(stored)):
                self.path.write_text(json.dumps({"session_id": "s1", "context_tokens_start": stored}))
                loaded = state.load(self.path)
                assert loaded is not None
                self.assertEqual(loaded.context_tokens_start, expected)
        self.assertEqual((state.TurnState().n_edit, state.TurnState().context_tokens_start), (0, None))

    def test_save_failure_returns_false(self) -> None:
        blocker = self.dir / "file"
        blocker.write_text("x")
        self.assertFalse(state.save(blocker / "state" / "s1.json", state.TurnState(session_id="s1")))

    def test_load_for_a_payload(self) -> None:
        state_dir = self.dir / "state"
        path, record = state.load_for(state_dir, {"session_id": "s1"})
        self.assertEqual((path, record), (self.path, None))
        state.save(self.path, state.TurnState(session_id="s1", turn=4))
        path, record = state.load_for(state_dir, {"session_id": "s1"})
        self.assertEqual((path, record.turn if record else None), (self.path, 4))
        self.assertEqual(state.load_for(state_dir, {"session_id": "../x"})[0], state_dir / ".._x.json")

    def test_sanitised_session_ids(self) -> None:
        self.assertEqual(payload.sanitize_session_id("s1"), "s1")
        self.assertEqual(payload.sanitize_session_id("../../evil"), ".._.._evil")
        self.assertEqual(payload.sanitize_session_id("a b/c\\d"), "a_b_c_d")
        self.assertEqual(payload.sanitize_session_id(""), "unknown")
        path = state.state_path(self.dir / "state", "../../evil")
        self.assertEqual(path.parent, self.dir / "state")
        self.assertEqual(path.name, ".._.._evil.json")

    def test_session_id_from_payload(self) -> None:
        self.assertEqual(payload.session_id({"session_id": "abc-1"}), "abc-1")
        self.assertEqual(payload.session_id({}), "unknown")
        self.assertEqual(payload.session_id({"session_id": None}), "unknown")


class PayloadTest(unittest.TestCase):
    def test_parse(self) -> None:
        self.assertEqual(payload.parse('{"a": 1}'), {"a": 1})
        for raw in ("", "{not json", "[1]", "3", "null"):
            self.assertEqual(payload.parse(raw), {}, raw)

    def test_text_fields(self) -> None:
        data = {"tool_input": {"model": {"name": "x"}, "description": "d", "n": None}, "agent_id": ""}
        self.assertEqual(payload.field_text(data, "tool_input", "description"), "d")
        self.assertEqual(payload.field_text(data, "tool_input", "model"), '{"name":"x"}')
        self.assertEqual(payload.field_text(data, "tool_input", "n"), "")
        self.assertEqual(payload.field_text(data, "missing", "deeper"), "")
        self.assertEqual(payload.field_text({"model": False}, "model"), "")
        self.assertEqual(payload.field_text({"n": 3}, "n"), "3")
        self.assertEqual(payload.tool_input({"tool_input": "junk"}), {})


if __name__ == "__main__":
    unittest.main()
