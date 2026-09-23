"""Every environment variable the hooks read, in one place.

Handlers build a Config from the environment they are given, so tests can
pass a plain dict instead of changing os.environ.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

TEXT_LIMIT = 4000
DEFAULT_URL = "http://127.0.0.1:8790"
DEFAULT_PORT = 8790
DEFAULT_MODELS = "opus,sonnet,haiku"
DEFAULT_TIMEOUT_MS = 1500
MIN_TIMEOUT_MS = 100
HEALTH_TIMEOUT_S = 1.0


def env_flag(env: Mapping[str, str], name: str) -> bool:
    """True only when the variable is exactly "1"."""
    return env.get(name, "0") == "1"


def env_int(env: Mapping[str, str], name: str, default: int) -> int:
    """The variable as a whole number, or the default when it is not one."""
    value = env.get(name, "")
    if value.isascii() and value.isdigit():
        return int(value)
    return default


def data_dir(env: Mapping[str, str]) -> Path:
    """The plugin data directory, outside any repository."""
    given = env.get("CLAUDE_PLUGIN_DATA", "")
    if given:
        return Path(given)
    home = env.get("HOME", "") or str(Path.home())
    return Path(home) / ".claude" / "orchestrator"


def default_plugin_root() -> Path:
    """The plugin root this package lives in, used when Claude Code sets none."""
    return Path(__file__).resolve().parents[2]


@dataclass
class Config:
    off: bool
    router_off: bool
    models: str
    debug_file: str
    router_url: str
    router_python: str
    timeout_ms: int
    block: bool
    log_off: bool
    stub: Optional[str]
    data_dir: Path
    plugin_root: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Config":
        directory = data_dir(env)
        timeout = max(env_int(env, "ORCHESTRATOR_ROUTER_TIMEOUT_MS", DEFAULT_TIMEOUT_MS), MIN_TIMEOUT_MS)
        return cls(
            off=env_flag(env, "ORCHESTRATOR_OFF"),
            router_off=env_flag(env, "ORCHESTRATOR_ROUTER_OFF"),
            models=env.get("ORCHESTRATOR_MODELS", "") or DEFAULT_MODELS,
            debug_file=env.get("ORCHESTRATOR_DEBUG", ""),
            router_url=(env.get("ORCHESTRATOR_ROUTER_URL", "") or DEFAULT_URL).rstrip("/"),
            router_python=env.get("ORCHESTRATOR_ROUTER_PYTHON", "")
            or str(directory / "router-venv" / "bin" / "python"),
            timeout_ms=timeout,
            block=env_flag(env, "ORCHESTRATOR_EXPLORATION_BLOCK"),
            log_off=env_flag(env, "ORCHESTRATOR_LOG_OFF"),
            stub=env.get("ORCHESTRATOR_ROUTER_STUB"),
            data_dir=directory,
            plugin_root=env.get("CLAUDE_PLUGIN_ROOT", ""),
        )

    @property
    def state_dir(self) -> Path:
        return self.data_dir / "state"

    @property
    def log_file(self) -> Path:
        return self.data_dir / "router-log.jsonl"

    @property
    def server_log(self) -> Path:
        return self.data_dir / "router-server.log"

    @property
    def pid_file(self) -> Path:
        return self.data_dir / "router-server.pid"

    @property
    def protocol_file(self) -> Optional[Path]:
        """The protocol file, or None when Claude Code gave no plugin root."""
        if not self.plugin_root:
            return None
        return Path(self.plugin_root) / "references" / "orchestrator-protocol.md"

    def protocol_text(self) -> Optional[str]:
        """The protocol file's text, or None when there is no readable file."""
        try:
            return self.protocol_file.read_text(encoding="utf-8") if self.protocol_file else None
        except (OSError, ValueError):
            return None

    @property
    def server_script(self) -> Path:
        root = Path(self.plugin_root) if self.plugin_root else default_plugin_root()
        return root / "router" / "server.py"


def current_dir() -> str:
    """The process working directory, or an empty string when it is gone."""
    try:
        return os.getcwd()
    except OSError:
        return ""
