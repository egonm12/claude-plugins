"""What a hook writes back to Claude Code, and the JSON shapes it accepts.

Every JSON output is built here with json.dumps, never by string formatting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

PREFIX = "orchestrator: "


@dataclass
class HookResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


def _json_line(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"


def lines(texts: List[str]) -> HookResult:
    """Plain text on stdout, one line per entry, nothing when there are none."""
    return HookResult(stdout="".join(line + "\n" for line in texts))


def block_stderr(message: str) -> HookResult:
    """Deny a tool call with exit code 2 and the reason on stderr."""
    return HookResult(stderr=message, exit_code=2)


def pre_tool_use(
    system_messages: List[str],
    contexts: List[str],
    updated_input: Optional[Dict[str, Any]] = None,
) -> HookResult:
    """A PreToolUse answer with only the keys that apply. Nothing when nothing applies."""
    data: Dict[str, Any] = {}
    if system_messages:
        data["systemMessage"] = " ".join(system_messages)
    specific: Dict[str, Any] = {}
    if contexts:
        specific["additionalContext"] = " ".join(contexts)
    if updated_input is not None:
        specific["updatedInput"] = updated_input
    if specific:
        data["hookSpecificOutput"] = dict({"hookEventName": "PreToolUse"}, **specific)
    return HookResult(stdout=_json_line(data)) if data else HookResult()


def pre_tool_use_deny(reason: str) -> HookResult:
    """A PreToolUse answer that denies the call with a reason Claude can read."""
    return HookResult(stdout=_json_line({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
