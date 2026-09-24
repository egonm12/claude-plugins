"""Client for the local router daemon.

Any problem counts as down: an exception, a status other than 200, a body
that is not a JSON object, or a body with an "error" key. With a stub set,
no request goes out at all.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .config import HEALTH_TIMEOUT_S, TEXT_LIMIT, Config

# Requests to the local daemon must never go through a proxy from the environment.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass
class Answer:
    body: Dict[str, Any] = field(default_factory=dict)
    server: str = "down"
    latency_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.server in ("ok", "stub")


class RouterClient:
    def __init__(self, url: str, timeout_ms: int, stub: Optional[str]) -> None:
        self.url = url.rstrip("/")
        self.timeout_s = timeout_ms / 1000.0
        self.stub = stub

    @classmethod
    def from_config(cls, config: Config) -> "RouterClient":
        return cls(config.router_url, config.timeout_ms, config.stub)

    def route(self, text: str) -> Answer:
        """Ask for a route verdict on a prompt."""
        return self._ask("route", text)

    def tier(self, text: str) -> Answer:
        """Ask for a tier verdict on a worker task."""
        return self._ask("tier", text)

    def health(self) -> bool:
        """True when the daemon answers its health check with a 200."""
        return self.health_info() is not None

    def health_info(self) -> Optional[Dict[str, Any]]:
        """The health answer, or None when the daemon is down.

        A 200 with a body that is not a JSON object gives an empty dict, so it still counts as up.
        """
        try:
            with _OPENER.open(self.url + "/health", timeout=HEALTH_TIMEOUT_S) as response:
                if response.status != 200:
                    return None
                raw = response.read()
        except Exception:
            return None
        try:
            answer = json.loads(raw.decode("utf-8"))
        except ValueError:
            return {}
        return answer if isinstance(answer, dict) else {}

    def _ask(self, endpoint: str, text: str) -> Answer:
        if self.stub is not None:
            return _stub_answer(self.stub)
        body = json.dumps({"text": (text or "")[:TEXT_LIMIT]}).encode("utf-8")
        request = urllib.request.Request(
            self.url + "/" + endpoint, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        start = time.perf_counter()
        try:
            with _OPENER.open(request, timeout=self.timeout_s) as response:
                if response.status != 200:
                    return Answer()
                answer = json.loads(response.read().decode("utf-8"))
        except Exception:
            return Answer()
        latency = int(round((time.perf_counter() - start) * 1000))
        if not isinstance(answer, dict) or "error" in answer:
            return Answer()
        return Answer(body=answer, server="ok", latency_ms=latency)


def _stub_answer(stub: str) -> Answer:
    """The stub as an answer. "down" or anything but a JSON object means no answer."""
    if stub == "down":
        return Answer()
    try:
        answer = json.loads(stub)
    except ValueError:
        return Answer()
    if not isinstance(answer, dict):
        return Answer()
    return Answer(body=answer, server="stub", latency_ms=0)
