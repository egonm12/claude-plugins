"""Read context size, model and duration from a Claude Code transcript.

A transcript is JSON lines. Only the last TAIL_BYTES of a file are read, so a
long session stays cheap. Every failure gives None, so reading never breaks a hook.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional

TAIL_BYTES = 512 * 1024
USAGE_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
SYNTHETIC = "<synthetic>"
_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})?$")


@dataclass
class AgentRun:
    model: Optional[str] = None
    duration_s: Optional[float] = None
    context_tokens_end: Optional[int] = None
    # The message of the last SubagentHandback call, when the worker handed back through that tool.
    report: Optional[str] = None


def _entries(lines: Iterable[bytes]) -> Iterator[Dict[str, Any]]:
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            yield entry


def _tail(path: Any) -> Iterator[Dict[str, Any]]:
    """The parsed lines in the last TAIL_BYTES of the file, last line first, parsed as they are read."""
    with open(Path(path), "rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(size - TAIL_BYTES, 0))
        lines = handle.read().split(b"\n")
    if size > TAIL_BYTES:
        lines = lines[1:]  # The first line was cut by the seek.
    return _entries(reversed(lines))


def _first(path: Any) -> Optional[Dict[str, Any]]:
    with open(Path(path), "rb") as handle:
        return next(_entries([handle.readline(TAIL_BYTES)]), None)


def _message(entry: Dict[str, Any], main_only: bool) -> Optional[Dict[str, Any]]:
    """The message of a real assistant line, or None."""
    message = entry.get("message")
    if entry.get("type") != "assistant" or not isinstance(message, dict) or message.get("model") == SYNTHETIC:
        return None
    return None if main_only and entry.get("isSidechain") is True else message


def _tokens(message: Dict[str, Any]) -> Optional[int]:
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    return sum(v for v in (usage.get(k) for k in USAGE_KEYS) if isinstance(v, int) and not isinstance(v, bool))


def context_tokens(path: Any) -> Optional[int]:
    """The main thread's context size: the input tokens of its last assistant message."""
    try:
        for entry in _tail(path):
            message = _message(entry, main_only=True)
            tokens = _tokens(message) if message is not None else None
            if tokens is not None:
                return tokens
    except Exception:
        pass
    return None


def agent_run(path: Any) -> AgentRun:
    """What a worker's own transcript says about its run. Missing parts stay None."""
    run = AgentRun()
    try:
        last_ts = None
        for entry in _tail(path):
            if last_ts is None:
                last_ts = entry.get("timestamp")
            message = _message(entry, main_only=False)
            if message is None:
                continue
            if run.model is None and isinstance(message.get("model"), str):
                run.model = message["model"]
            if run.context_tokens_end is None:
                run.context_tokens_end = _tokens(message)
            if run.report is None:
                run.report = _handback(message)
            if None not in (last_ts, run.model, run.context_tokens_end, run.report):
                break
        first = _first(path)
        run.duration_s = _round(seconds_between(first.get("timestamp") if first else None, last_ts))
    except Exception:
        pass
    return run


def _handback(message: Dict[str, Any]) -> Optional[str]:
    content = message.get("content")
    for block in reversed(content if isinstance(content, list) else []):
        if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "SubagentHandback":
            text = block.get("input", {}).get("message") if isinstance(block.get("input"), dict) else None
            if isinstance(text, str):
                return text
    return None


def agent_tool_use_id(path: Any) -> Optional[str]:
    """The Agent tool_use id from the meta file next to a worker transcript, or None."""
    try:
        transcript = Path(path)
        if transcript.suffix != ".jsonl":
            return None
        meta = json.loads(transcript.with_suffix(".meta.json").read_text(encoding="utf-8"))
        found = meta.get("toolUseId") if isinstance(meta, dict) else None
        return found if isinstance(found, str) and found else None
    except Exception:
        return None


def parse_time(text: Any) -> Optional[datetime]:
    """An ISO 8601 time such as 2026-09-23T19:57:05.547Z, read as UTC when it names no zone."""
    match = _TIME.match(text) if isinstance(text, str) else None
    if match is None:
        return None
    base = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    zone = match.group(3) or "Z"
    offset = 0 if zone == "Z" else (1 if zone[0] == "+" else -1) * (int(zone[1:3]) * 3600 + int(zone[4:6]) * 60)
    return base + timedelta(seconds=float(match.group(2) or 0) - offset)


def seconds_between(start: Any, end: Any) -> Optional[float]:
    """Seconds from start to end, to the millisecond, or None when either is not a time."""
    first, last = parse_time(start), parse_time(end)
    if first is None or last is None:
        return None
    return round(last.timestamp() - first.timestamp(), 3)


def _round(seconds: Optional[float]) -> Optional[float]:
    return None if seconds is None else round(seconds, 1)
