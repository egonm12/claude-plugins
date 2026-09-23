"""Start the router daemon in the background when it is not running.

The start never waits for the model to load. It prints one line only when
it actually started the daemon.
"""

from __future__ import annotations

import os
import subprocess
from typing import List, Optional

from . import rules
from .client import RouterClient
from .config import Config
from .messages import START_TEXT

# Started daemons stay referenced, so no cleanup runs while the hook process lives.
_DAEMONS: List["subprocess.Popen[bytes]"] = []


def start_router(config: Config) -> Optional[str]:
    """Start the daemon when it is not running. The line to print, or None."""
    if config.stub is not None:
        return None
    if _pid_alive(config):
        return None
    if RouterClient.from_config(config).health():
        return None
    python, server = config.router_python, config.server_script
    if not (os.path.isfile(python) and os.access(python, os.X_OK) and server.is_file()):
        return None
    port = rules.port_from_url(config.router_url)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    with open(config.server_log, "ab") as log:
        process = subprocess.Popen(
            [python, str(server), "--port", str(port)],
            stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True,
        )
    _DAEMONS.append(process)
    config.pid_file.write_text("%d\n" % process.pid)
    return START_TEXT.format(url=config.router_url)


def _pid_alive(config: Config) -> bool:
    """True when the pid file names a live process from an earlier start."""
    try:
        pid = int(config.pid_file.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
