"""The four record kinds of the training log, and the append to it.

The log is append-only JSON lines in the data directory. Records join on
session id and turn. A failed write is ignored, so logging never breaks a hook.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union

from .config import TEXT_LIMIT


def now_iso() -> str:
    """The current UTC time in ISO 8601 with seconds and a Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def truncate(text: str) -> str:
    """The first 4000 characters of a text."""
    return text[:TEXT_LIMIT]


@dataclass
class PromptRecord:
    session_id: str
    turn: int
    cwd: str
    text: str
    verdict: Dict[str, Any]
    latency_ms: int
    server: str
    # The route the hooks acted on, the delegate-self gap, and the turn a short follow-up took its route from.
    route_effective: str = "none"
    margin: Optional[float] = None
    carried_from_turn: Optional[int] = None
    ts: str = field(default_factory=now_iso)

    def to_json(self) -> Dict[str, Any]:
        return {
            "kind": "prompt", "ts": self.ts, "session_id": self.session_id, "turn": self.turn,
            "cwd": self.cwd, "text": truncate(self.text), "verdict": self.verdict,
            "route_effective": self.route_effective, "margin": self.margin,
            "carried_from_turn": self.carried_from_turn, "latency_ms": self.latency_ms, "server": self.server,
        }


@dataclass
class PromptOutcomeRecord:
    session_id: str
    turn: int
    n_exploratory: int
    n_agent: int
    n_tool: int
    warned: bool
    source: str
    ts: str = field(default_factory=now_iso)

    def to_json(self) -> Dict[str, Any]:
        return {
            "kind": "prompt_outcome", "ts": self.ts, "session_id": self.session_id,
            "turn": self.turn, "n_exploratory": self.n_exploratory, "n_agent": self.n_agent,
            "n_tool": self.n_tool, "warned": self.warned, "source": self.source,
        }


@dataclass
class AgentCallRecord:
    session_id: str
    turn: int
    tool: str
    subagent_type: str
    description: str
    prompt: str
    model_given: Any
    user_named_subagent: bool
    verdict: Dict[str, Any]
    model_set: Any
    action: str
    latency_ms: int
    server: str
    ts: str = field(default_factory=now_iso)

    def to_json(self) -> Dict[str, Any]:
        return {
            "kind": "agent_call", "ts": self.ts, "session_id": self.session_id, "turn": self.turn,
            "tool": self.tool, "subagent_type": self.subagent_type,
            "description": truncate(self.description), "prompt": truncate(self.prompt),
            "model_given": self.model_given, "user_named_subagent": self.user_named_subagent,
            "verdict": self.verdict, "model_set": self.model_set, "action": self.action,
            "latency_ms": self.latency_ms, "server": self.server,
        }


@dataclass
class ExplorationWarningRecord:
    session_id: str
    turn: int
    n_exploratory: int
    threshold: int
    tool: str
    blocked: bool
    ts: str = field(default_factory=now_iso)

    def to_json(self) -> Dict[str, Any]:
        return {
            "kind": "exploration_warning", "ts": self.ts, "session_id": self.session_id,
            "turn": self.turn, "n_exploratory": self.n_exploratory, "threshold": self.threshold,
            "tool": self.tool, "blocked": self.blocked,
        }


Record = Union[PromptRecord, PromptOutcomeRecord, AgentCallRecord, ExplorationWarningRecord]


def append(path: Path, record: Record, log_off: bool = False) -> None:
    """Append one record as a JSON line, unless logging is off. Never raises."""
    if log_off:
        return
    try:
        line = json.dumps(record.to_json(), ensure_ascii=False, separators=(",", ":"))
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        pass
