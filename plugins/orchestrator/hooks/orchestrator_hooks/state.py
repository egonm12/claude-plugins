"""The per-session state record for the current turn.

One JSON file per session. Writes go to a temp file and then replace the
record. There is no lock, so parallel tool calls may undercount.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .payload import sanitize_session_id, session_id


@dataclass
class TurnState:
    session_id: str = "unknown"
    turn: int = 0
    turn_started: str = ""
    prompt: str = ""
    # The effective route: "unsure" for a close verdict, or the previous turn's route for a short follow-up.
    route: str = "none"
    route_conf: float = 0
    tier: str = "none"
    threshold: int = 3
    n_exploratory: int = 0
    n_agent: int = 0
    n_tool: int = 0
    warned: bool = False
    finalized: bool = False
    server: str = "down"


def state_path(state_dir: Path, session: str) -> Path:
    """The state file for a session, always directly inside the state directory."""
    return Path(state_dir) / (sanitize_session_id(session) + ".json")


def load_for(state_dir: Path, payload: Dict[str, Any]) -> Tuple[Path, Optional[TurnState]]:
    """The state file for the payload's session, and its record or None."""
    path = state_path(state_dir, session_id(payload))
    return path, load(path)


# Fields that hold any number. Other number fields hold whole numbers.
_REAL_FIELDS = frozenset({"route_conf"})


def _coerce(name: str, default: Any, found: Any) -> Any:
    """The stored value when it has the field's type, else the default."""
    if isinstance(default, bool):
        return found if isinstance(found, bool) else default
    if isinstance(default, (int, float)):
        if isinstance(found, bool) or not isinstance(found, (int, float)):
            return default
        return found if name in _REAL_FIELDS else int(found // 1)
    return found if isinstance(found, str) else default


def load(path: Path) -> Optional[TurnState]:
    """The state record, or None when it is missing or broken."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        record = TurnState()
        for item in fields(TurnState):
            if item.name in data:
                setattr(record, item.name, _coerce(item.name, getattr(record, item.name), data[item.name]))
        return record
    except Exception:
        return None


def save(path: Path, record: TurnState) -> bool:
    """Replace the state record. False when the write failed."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp." + str(os.getpid()))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(asdict(record), ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
