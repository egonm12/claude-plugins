"""Unit tests for reading context size, model and duration from a session transcript."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))

from orchestrator_hooks import transcript  # noqa: E402


def assistant(ts: str, model: str = "claude-opus-5-5", tokens: tuple = (2, 1000, 50), sidechain: bool = False,
              content: Any = None) -> Dict[str, Any]:
    """An assistant line shaped like a real Claude Code transcript line."""
    usage = {"input_tokens": tokens[0], "cache_read_input_tokens": tokens[1],
             "cache_creation_input_tokens": tokens[2], "output_tokens": 9}
    return {"type": "assistant", "isSidechain": sidechain, "timestamp": ts,
            "message": {"model": model, "usage": usage, "content": content or [{"type": "text", "text": "ok"}]}}


def user(ts: str, sidechain: bool = False) -> Dict[str, Any]:
    return {"type": "user", "isSidechain": sidechain, "timestamp": ts, "message": {"role": "user", "content": "hi"}}


def handback(ts: str, message: str) -> Dict[str, Any]:
    content = [{"type": "tool_use", "id": "toolu_x", "name": "SubagentHandback", "input": {"message": message}}]
    return assistant(ts, sidechain=True, content=content)


class TranscriptCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "session.jsonl"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, rows: List[Any], path: Path = None) -> Path:
        path = path or self.path
        path.write_text("".join((row if isinstance(row, str) else json.dumps(row)) + "\n" for row in rows))
        return path


class ContextTokensTest(TranscriptCase):
    def test_sums_the_usage_of_the_last_assistant_message(self) -> None:
        self.write([assistant("2026-09-24T08:00:00Z", tokens=(1, 10, 100)), user("2026-09-24T08:00:01Z"),
                    assistant("2026-09-24T08:00:02Z", tokens=(2, 174422, 4929)), user("2026-09-24T08:00:03Z")])
        self.assertEqual(transcript.context_tokens(self.path), 2 + 174422 + 4929)

    def test_skips_synthetic_and_sidechain_messages_and_broken_lines(self) -> None:
        self.write([assistant("2026-09-24T08:00:00Z", tokens=(3, 30, 300)),
                    assistant("2026-09-24T08:00:01Z", tokens=(0, 0, 0), model="<synthetic>"),
                    assistant("2026-09-24T08:00:02Z", tokens=(5, 5, 5), sidechain=True),
                    "{not json", "[1]", ""])
        self.assertEqual(transcript.context_tokens(self.path), 333)

    def test_missing_fields_count_as_zero_and_no_usage_gives_none(self) -> None:
        row = assistant("2026-09-24T08:00:00Z")
        row["message"]["usage"] = {"input_tokens": 7, "cache_read_input_tokens": "x"}
        self.write([row])
        self.assertEqual(transcript.context_tokens(self.path), 7)
        self.write([user("2026-09-24T08:00:00Z")])
        self.assertIsNone(transcript.context_tokens(self.path))

    def test_failures_give_none(self) -> None:
        self.assertIsNone(transcript.context_tokens(self.dir / "missing.jsonl"))
        self.assertIsNone(transcript.context_tokens(""))
        self.assertIsNone(transcript.context_tokens(None))
        self.assertIsNone(transcript.context_tokens(self.dir))

    def test_reads_only_the_tail_of_a_large_file(self) -> None:
        # The early message lies outside the tail window, so it can never be the answer.
        pad = json.dumps({"type": "user", "pad": "x" * 1000})
        rows: List[Any] = [assistant("2026-09-24T08:00:00Z", tokens=(1, 1, 1))] + [pad] * 700
        self.write(rows)
        self.assertGreater(self.path.stat().st_size, transcript.TAIL_BYTES)
        self.assertIsNone(transcript.context_tokens(self.path))
        self.write(rows + [assistant("2026-09-24T08:00:09Z", tokens=(1, 2, 3))])
        self.assertEqual(transcript.context_tokens(self.path), 6)


class AgentRunTest(TranscriptCase):
    def test_model_duration_tokens_and_handback_report(self) -> None:
        self.write([user("2026-09-23T19:57:05.547Z", sidechain=True),
                    assistant("2026-09-23T19:57:10.000Z", model="claude-sonnet-5", tokens=(1, 1, 1), sidechain=True),
                    handback("2026-09-23T19:59:30.000Z", "the report"),
                    assistant("2026-09-23T19:59:31.720Z", model="claude-sonnet-5", tokens=(2, 45745, 2484),
                              sidechain=True)])
        run = transcript.agent_run(self.path)
        self.assertEqual((run.model, run.duration_s, run.context_tokens_end, run.report),
                         ("claude-sonnet-5", 146.2, 2 + 45745 + 2484, "the report"))

    def test_without_handback_the_report_is_none(self) -> None:
        self.write([user("2026-09-23T19:57:05Z", sidechain=True),
                    assistant("2026-09-23T19:57:06Z", sidechain=True)])
        run = transcript.agent_run(self.path)
        self.assertEqual((run.model, run.duration_s, run.report), ("claude-opus-5-5", 1.0, None))

    def test_synthetic_model_is_skipped(self) -> None:
        self.write([assistant("2026-09-23T19:57:05Z", model="claude-haiku-4-5", sidechain=True),
                    assistant("2026-09-23T19:57:06Z", model="<synthetic>", tokens=(0, 0, 0), sidechain=True)])
        self.assertEqual(transcript.agent_run(self.path).model, "claude-haiku-4-5")

    def test_failures_give_empty_values(self) -> None:
        for path in (self.dir / "missing.jsonl", "", None):
            run = transcript.agent_run(path)
            self.assertEqual((run.model, run.duration_s, run.context_tokens_end, run.report),
                             (None, None, None, None))
        self.write(["{not json", json.dumps({"type": "assistant", "timestamp": "late"})])
        run = transcript.agent_run(self.path)
        self.assertEqual((run.model, run.duration_s), (None, None))

    def test_tool_use_id_from_the_meta_file(self) -> None:
        path = self.write([user("2026-09-23T19:57:05Z", sidechain=True)], self.dir / "agent-a1.jsonl")
        self.assertIsNone(transcript.agent_tool_use_id(path))
        (self.dir / "agent-a1.meta.json").write_text(json.dumps({"agentType": "x", "toolUseId": "toolu_01C"}))
        self.assertEqual(transcript.agent_tool_use_id(path), "toolu_01C")
        (self.dir / "agent-a1.meta.json").write_text("[1]")
        self.assertIsNone(transcript.agent_tool_use_id(path))
        self.assertIsNone(transcript.agent_tool_use_id(None))
        self.assertIsNone(transcript.agent_tool_use_id(self.dir / "notes.txt"))


class TimeTest(unittest.TestCase):
    def test_seconds_between(self) -> None:
        self.assertEqual(transcript.seconds_between("2026-09-23T19:57:05.547Z", "2026-09-23T19:59:31.720Z"), 146.173)
        self.assertEqual(transcript.seconds_between("2026-09-23T19:57:05Z", "2026-09-23T19:57:05.5+00:00"), 0.5)
        for bad in ("", "late", None, 3):
            self.assertIsNone(transcript.seconds_between(bad, "2026-09-23T19:57:05Z"))


if __name__ == "__main__":
    unittest.main()
