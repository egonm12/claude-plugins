"""Start the router daemon in the background, and replace one that an update left behind.

The start never waits for the model to load. It prints one line only when
it started or restarted the daemon, or when an outdated daemon needs a
manual stop.

A daemon keeps serving the code it started with. So when its health check
names another plugin version than this package, or none, the old daemon
stops and a new one starts. The hooks stop only the process in the pid file,
and only when its command line names server.py. Anything else stays alive.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from . import __version__, rules
from .client import RouterClient
from .config import Config
from .messages import OUTDATED_TEXT, RESTART_TEXT, START_TEXT, STILL_BUSY_TEXT

# Started daemons stay referenced, so no cleanup runs while the hook process lives.
_DAEMONS: List["subprocess.Popen[bytes]"] = []
# How long to wait for a stopped daemon to free its port. SessionStart has 10 seconds in total.
STOP_WAIT_S = 3.0
STOP_POLL_S = 0.1
PS_TIMEOUT_S = 2.0


def start_router(config: Config) -> Optional[str]:
    """Start the daemon when it is not running, or restart an outdated one. The line to print, or None."""
    if config.stub is not None:
        return None
    client = RouterClient.from_config(config)
    health = client.health_info()
    if health is not None:
        running = health_version(health)
        if not is_older(running, __version__):
            return None
        return _replace_outdated(config, client, running)
    if _pid_alive(config):
        return None
    if not _can_launch(config):
        return None
    _launch(config)
    return START_TEXT.format(url=config.router_url)


def _replace_outdated(config: Config, client: RouterClient, running: Optional[str]) -> str:
    """Stop the outdated daemon and start a new one. Without a confirmed pid, only say how to stop it."""
    old = running or "unknown"
    pid = _read_pid(config)
    confirmed = pid is not None and _alive(pid) and "server.py" in _command_line(pid)
    # Without a new daemon to start, the old one keeps serving rather than leaving no router at all.
    if not (confirmed and _can_launch(config) and _terminate(pid)):
        return OUTDATED_TEXT.format(url=config.router_url, old=old, new=__version__,
                                    port=rules.port_from_url(config.router_url))
    if not _wait_until_down(client):
        return STILL_BUSY_TEXT.format(url=config.router_url)
    _launch(config)
    return RESTART_TEXT.format(url=config.router_url, old=old, new=__version__)


def _can_launch(config: Config) -> bool:
    python, server = config.router_python, config.server_script
    return os.path.isfile(python) and os.access(python, os.X_OK) and server.is_file()


def _launch(config: Config) -> None:
    port = rules.port_from_url(config.router_url)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    with open(config.server_log, "ab") as log:
        process = subprocess.Popen(
            [config.router_python, str(config.server_script), "--port", str(port)],
            stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True,
        )
    _DAEMONS.append(process)
    config.pid_file.write_text("%d\n" % process.pid)


def _read_pid(config: Config) -> Optional[int]:
    """The pid in the pid file, or None when there is no usable one."""
    try:
        pid = int(config.pid_file.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return pid if pid > 0 else None


def _alive(pid: int) -> bool:
    """True when a process with this pid exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _pid_alive(config: Config) -> bool:
    """True when the pid file names a live process from an earlier start."""
    pid = _read_pid(config)
    return pid is not None and _alive(pid)


def _command_line(pid: int) -> str:
    """The command line of a process as ps shows it, or an empty string when ps gives none."""
    try:
        done = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True,
                              timeout=PS_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _terminate(pid: int) -> bool:
    """Ask the process to stop. True when the signal went out."""
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    return True


def _wait_until_down(client: RouterClient) -> bool:
    """True once the health check fails, so the port is free. False after the wait runs out."""
    deadline = time.monotonic() + STOP_WAIT_S
    while True:
        if not client.health():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(STOP_POLL_S)


def is_older(running: Optional[str], mine: str) -> bool:
    """True when the running daemon's version is older than this plugin's, or unknown.

    A newer daemon is left alone, so an older session never stops the router a newer version started.
    """
    def parts(version: Optional[str]) -> Optional[Tuple[int, ...]]:
        try:
            return tuple(int(p) for p in (version or "").split("."))
        except ValueError:
            return None
    ran, own = parts(running), parts(mine)
    return ran is None or own is None or ran < own


def health_version(health: Dict[str, Any]) -> Optional[str]:
    """The plugin version a health answer names, or None."""
    running = health.get("plugin_version")
    return running if isinstance(running, str) and running else None
