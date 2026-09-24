"""Unit tests for the labelling tool."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import label  # noqa: E402


def prompt(session: str, turn: int, ts: str, route: str, text: str = "do it", **extra: object) -> dict:
    record = {"kind": "prompt", "ts": ts, "session_id": session, "turn": turn, "cwd": "/work/app", "text": text,
              "verdict": {"route": route if route != "unsure" else "delegate",
                          "route_probs": {"delegate": 0.52, "self": 0.48}, "tier": "sonnet",
                          "tier_probs": {"opus": 0.2, "sonnet": 0.6, "haiku": 0.2}, "by_regex": False},
              "route_effective": route, "margin": 0.04, "carried_from_turn": None, "latency_ms": 5, "server": "ok"}
    record.update(extra)
    return record


def outcome(session: str, turn: int, **counts: object) -> dict:
    record = {"kind": "prompt_outcome", "ts": "2026-09-24T10:00:00Z", "session_id": session, "turn": turn,
              "n_exploratory": 0, "n_agent": 0, "n_tool": 0, "warned": False, "source": "stop"}
    record.update(counts)
    return record


def call(session: str, turn: int, given: object, model_set: object, **extra: object) -> dict:
    record = {"kind": "agent_call", "ts": "2026-09-24T10:00:00Z", "session_id": session, "turn": turn,
              "tool": "Agent", "subagent_type": "general-purpose", "description": "find the bug",
              "prompt": "look   at\n\nthe code", "model_given": given, "verdict": {"tier": "haiku", "tier_probs": {}},
              "model_set": model_set, "action": "set", "tier_margin": 0.2, "reason": "downgrade"}
    record.update(extra)
    return record


class LabelTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_log(self, rows: list, extra_lines: tuple = ()) -> None:
        with (self.dir / "router-log.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
            for line in extra_lines:
                handle.write(line + "\n")

    def run_tool(self, answers: str = "", *args: str) -> str:
        out = io.StringIO()
        label.main(["--data-dir", str(self.dir), *args], stdin=io.StringIO(answers), out=out)
        return out.getvalue()

    def labels(self) -> list:
        path = self.dir / "labels.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def standard_log(self) -> None:
        self.write_log([
            prompt("s1", 1, "2026-09-24T09:00:00Z", "self"),  # rest
            prompt("s1", 2, "2026-09-24T09:01:00Z", "self"), outcome("s1", 2, n_exploratory=3),  # self, busy
            prompt("s1", 3, "2026-09-24T09:02:00Z", "delegate"), outcome("s1", 3),  # delegate, no worker
            prompt("s1", 4, "2026-09-24T09:03:00Z", "unsure"),  # unsure, older
            prompt("s1", 5, "2026-09-24T09:04:00Z", "unsure"),  # unsure, newer
            prompt("s1", 6, "2026-09-24T09:05:00Z", "delegate"), outcome("s1", 6, n_agent=1),  # rest
            call("s1", 6, "opus", "haiku"),
        ])

    def test_old_and_new_verdicts_load_side_by_side(self) -> None:
        # Records from 0.5.5 carry wording ids in the verdict. Older records lack them. Both load.
        new_verdict = {"tier": "sonnet", "tier_probs": {}, "tier_wording": "b-2026-09-24"}
        self.write_log([
            prompt("s1", 1, "2026-09-24T09:00:00Z", "delegate"),
            call("s1", 1, "opus", "haiku"),
            call("s1", 1, None, "sonnet", verdict=new_verdict),
        ])
        log = label.Log.load(self.dir / "router-log.jsonl")
        self.assertEqual(log.bad, 0)
        calls = [item["call"] for item in log.tier_items()]
        self.assertEqual([c["verdict"].get("tier_wording") for c in calls], [None, "b-2026-09-24"])

    def test_order_groups_then_newest_first(self) -> None:
        self.standard_log()
        self.run_tool("k\n" * 6)
        self.assertEqual([row["turn"] for row in self.labels()], [5, 4, 3, 2, 6, 1])

    def test_answers_write_one_line_each_with_decision_copy(self) -> None:
        self.standard_log()
        self.run_tool("d\ns\nq\n")
        rows = self.labels()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["kind"], "route")
        self.assertEqual(rows[0]["session_id"], "s1")
        self.assertEqual(rows[0]["turn"], 5)
        self.assertEqual(rows[0]["label"], "delegate")
        self.assertEqual(rows[0]["route_effective"], "unsure")
        self.assertEqual(rows[0]["route_raw"], "delegate")
        self.assertAlmostEqual(rows[0]["margin"], 0.04)
        self.assertEqual(rows[1]["label"], "self")
        self.assertIn("ts", rows[0])

    def test_already_labelled_items_are_skipped(self) -> None:
        self.standard_log()
        self.run_tool("d\nq\n")
        self.run_tool("s\nq\n")
        self.assertEqual([row["turn"] for row in self.labels()], [5, 4])

    def test_skip_is_recorded_and_not_asked_again(self) -> None:
        self.standard_log()
        self.run_tool("k\nq\n")
        self.run_tool("d\nq\n")
        self.assertEqual([(r["turn"], r["label"]) for r in self.labels()], [(5, "skip"), (4, "delegate")])

    def test_undo_appends_retraction_and_asks_again(self) -> None:
        self.standard_log()
        self.run_tool("d\nu\ns\nq\n")
        rows = self.labels()
        self.assertEqual([(r["turn"], r["label"]) for r in rows], [(5, "delegate"), (5, None), (5, "self")])
        self.assertTrue(rows[1]["retract"])
        self.assertEqual(label.current_labels(self.dir / "labels.jsonl")[("route", "s1", 5, None)]["label"], "self")

    def test_undone_item_is_asked_again_next_run(self) -> None:
        self.standard_log()
        self.run_tool("d\nu\nq\n")
        self.run_tool("s\nq\n")
        self.assertEqual(self.labels()[-1]["turn"], 5)
        self.assertEqual(self.labels()[-1]["label"], "self")

    def test_unknown_key_asks_again_and_end_of_input_stops(self) -> None:
        self.standard_log()
        output = self.run_tool("x\nd\n")
        self.assertIn("unknown key", output)
        self.assertEqual(len(self.labels()), 1)

    def test_last_outcome_wins(self) -> None:
        self.write_log([
            prompt("s1", 1, "2026-09-24T09:00:00Z", "self"),
            outcome("s1", 1, n_exploratory=5, source="next_prompt"),
            outcome("s1", 1, n_exploratory=0, source="stop"),
            prompt("s1", 2, "2026-09-24T08:00:00Z", "self"),
            outcome("s1", 2, n_exploratory=0), outcome("s1", 2, n_exploratory=4),
        ])
        output = self.run_tool("k\nk\n")
        self.assertEqual([row["turn"] for row in self.labels()], [2, 1])  # only turn 2 did real work
        self.assertIn("exploratory 4", output)

    def test_filters_and_limit(self) -> None:
        self.write_log([prompt("s1", 1, "2026-09-20T09:00:00Z", "self"),
                        prompt("s2", 1, "2026-09-24T09:00:00Z", "self"),
                        prompt("t9", 1, "2026-09-24T09:00:00Z", "self")])
        self.run_tool("k\nk\nk\n", "--since", "2026-09-21", "--session", "s")
        self.assertEqual([row["session_id"] for row in self.labels()], ["s2"])
        self.run_tool("k\nk\nk\n", "--limit", "1")
        self.assertEqual(len(self.labels()), 2)

    def test_old_lines_and_malformed_lines_are_tolerated(self) -> None:
        old = prompt("s1", 1, "2026-09-23T09:00:00Z", "delegate")
        del old["route_effective"], old["margin"], old["carried_from_turn"]
        self.write_log([old, outcome("s1", 1, n_agent=1)], extra_lines=("{broken", "[1, 2]", '{"kind": "prompt"}'))
        output = self.run_tool("d\n")
        self.assertIn("skipped 3 malformed log lines", output)
        row = self.labels()[0]
        self.assertEqual(row["route_effective"], "delegate")  # falls back to the raw route
        self.assertAlmostEqual(row["margin"], 0.04)  # computed from the probabilities

    def test_new_outcome_fields_are_shown(self) -> None:
        self.write_log([prompt("s1", 1, "2026-09-24T09:00:00Z", "self", plugin_version="0.6.0"),
                        outcome("s1", 1, n_edit=2, duration_s=31.4, context_tokens_start=1000,
                                context_tokens_end=4500)])
        output = self.run_tool("s\n")
        self.assertIn("edits 2", output)
        self.assertIn("duration 31s", output)
        self.assertIn("context +3500 tokens", output)

    def test_missing_and_empty_log(self) -> None:
        output = self.run_tool("d\n")
        self.assertIn("no log at", output)
        self.assertIn("nothing left to label", output)
        self.write_log([])
        self.assertIn("nothing left to label", self.run_tool("d\n"))
        self.assertIn("Unlabelled: 0 route items, 0 tier items", self.run_tool("", "--stats"))

    def test_keyboard_interrupt_keeps_answers(self) -> None:
        self.standard_log()
        answers = iter(["d", "s"])

        def reader() -> str:
            try:
                return next(answers)
            except StopIteration:
                raise KeyboardInterrupt
        out = io.StringIO()
        items = label.order_items(label.Log.load(self.dir / "router-log.jsonl").route_items(), label.route_group)
        count = label.review(items, label.ROUTE_KEYS, "q?", label.show_route, self.dir / "labels.jsonl", reader, out)
        self.assertEqual(count, 2)
        self.assertIn("interrupted", out.getvalue())
        self.assertEqual(len(self.labels()), 2)

    def test_workers_mode_skips_forks_and_links_results(self) -> None:
        self.write_log([
            prompt("s1", 1, "2026-09-24T09:00:00Z", "delegate"),
            call("s1", 1, None, None, subagent_type="fork", action="fork", reason="fork"),
            call("s1", 1, "opus", "haiku", description="first"),
            call("s1", 1, "sonnet", "sonnet", description="second", reason="no_change"),
            {"kind": "agent_result", "session_id": "s1", "turn": 1, "agent_id": "a0", "agent_type": "fork",
             "model": "opus", "duration_s": 1.0, "context_tokens_end": 10, "report_chars": 5},
            {"kind": "agent_result", "session_id": "s1", "turn": 1, "agent_id": "a1", "agent_type": "general-purpose",
             "model": "haiku", "duration_s": 12.5, "context_tokens_end": 900, "report_chars": 1234},
        ])
        output = self.run_tool("s\nh\n", "--workers")
        rows = self.labels()
        self.assertEqual([(r["kind"], r["index"], r["label"], r["model_set"]) for r in rows],
                         [("tier", 1, "sonnet", "haiku"), ("tier", 2, "haiku", "sonnet")])
        self.assertIn("report_chars 1234", output)
        self.assertIn("prompt: look at the code", output)

    def test_link_key_beats_order(self) -> None:
        calls = [{"agent_id": "b"}, {"agent_id": "a"}]
        results = [{"agent_id": "a", "n": 1}, {"agent_id": "b", "n": 2}]
        self.assertEqual([r["n"] for r in label.link_results(calls, results)], [2, 1])

    def test_stats_numbers(self) -> None:
        self.standard_log()
        # Order: 5 unsure, 4 unsure, 3 delegate, 2 self, 6 delegate, 1 self.
        self.run_tool("d\ns\nd\ns\ns\nk\n")
        self.run_tool("h\n", "--workers")
        output = self.run_tool("", "--stats")
        self.assertIn("Route labels: 5", output)
        self.assertIn("agreement (route used was delegate or self): 67% (2/3)", output)
        self.assertIn("<0.05      60% (3/5)", output)  # raw route delegate on 5, 4, 3, 6; self on 2
        self.assertIn("Tier labels: 1", output)
        self.assertIn("downgrades: 1, wrong (label bigger than model set): 0", output)
        self.assertIn("Skipped: 1", output)
        self.assertIn("Unlabelled: 0 route items, 0 tier items", output)

    def test_stats_counts_wrong_downgrade(self) -> None:
        self.standard_log()
        self.run_tool("o\n", "--workers")
        output = self.run_tool("", "--stats")
        self.assertIn("downgrades: 1, wrong (label bigger than model set): 1", output)
        self.assertIn("agreement: 0% (0/1)", output)
        self.assertIn("Unlabelled: 6 route items, 0 tier items", output)

    def test_export(self) -> None:
        self.standard_log()
        self.run_tool("d\nk\n")
        self.run_tool("s\n", "--workers")
        target = self.dir / "out.jsonl"
        output = self.run_tool("", "--export", str(target))
        self.assertIn("wrote 2 examples", output)
        rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
        route = next(r for r in rows if r["kind"] == "route")
        tier = next(r for r in rows if r["kind"] == "tier")
        self.assertEqual((route["turn"], route["label"], route["text"], route["route_effective"]),
                         (5, "delegate", "do it", "unsure"))
        self.assertEqual(route["route_probs"], {"delegate": 0.52, "self": 0.48})
        self.assertEqual((tier["label"], tier["model_set"], tier["model_given"]), ("sonnet", "haiku", "opus"))
        self.assertIn("find the bug", tier["text"])

    def test_data_dir_from_environment(self) -> None:
        import os
        old = os.environ.get("ORCHESTRATOR_DATA_DIR")
        os.environ["ORCHESTRATOR_DATA_DIR"] = str(self.dir)
        try:
            self.assertEqual(label.data_dir(None), self.dir)
            self.assertEqual(label.data_dir("/x"), Path("/x"))
        finally:
            if old is None:
                del os.environ["ORCHESTRATOR_DATA_DIR"]
            else:
                os.environ["ORCHESTRATOR_DATA_DIR"] = old


if __name__ == "__main__":
    unittest.main()
