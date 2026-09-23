"""Read the hook payload that Claude Code sends on stdin."""

from __future__ import annotations

import json
import re
from typing import Any, Dict

from .rules import model_text

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def parse(raw: str) -> Dict[str, Any]:
    """The payload as a dict. Anything that is not a JSON object becomes {}."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def value(data: Dict[str, Any], *keys: str) -> Any:
    """The value at a key path, or None when any step is missing."""
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def field_text(data: Dict[str, Any], *keys: str) -> str:
    """A field as text. A string stays as is, false becomes empty, other values become compact JSON."""
    found = value(data, *keys)
    return "" if found is False else model_text(found)


def tool_input(data: Dict[str, Any]) -> Dict[str, Any]:
    """The tool input object, or {} when it is missing or not an object."""
    found = data.get("tool_input")
    return found if isinstance(found, dict) else {}


def sanitize_session_id(raw: str) -> str:
    """A session id that is safe as a file name. Empty becomes "unknown"."""
    return _UNSAFE.sub("_", raw) if raw else "unknown"


def session_id(data: Dict[str, Any]) -> str:
    """The payload session id, safe as a file name."""
    return sanitize_session_id(field_text(data, "session_id"))
