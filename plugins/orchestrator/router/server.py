#!/usr/bin/env python3
"""HTTP server for the orchestrator plugin's router.

Loads the laya checkpoint once, then serves three endpoints on localhost:
  GET  /health  -> {"status", "device", "checkpoint", "plugin_version"}
  POST /route   -> route and tier verdict for a prompt, body {"text": "..."}
  POST /tier    -> tier verdict only, for a worker task, body {"text": "..."}

Every verdict carries the id of the question wording that produced it. The
health check carries the plugin version this server runs, so the hooks can
restart a server that an update left behind.

Run:
  python server.py [--host 127.0.0.1] [--port 8790] \
      [--device auto|mps|cpu] [--checkpoint convaiinnovations/laya]

Standard library only. Single threaded: calls take about 100 ms, so a
simple queue of requests is fine.
"""
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import router as router_mod

MAX_TEXT_CHARS = 4000
WARM_UP_TEXT = (
    "Why does the login test fail after the refactor? Compare the last three "
    "commits, check the fixtures, trace the failing assertion and tell me "
    "whether the change to the session middleware or the new fixture causes it."
)

PLUGIN_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".claude-plugin", "plugin.json")

MODEL = None
CHECKPOINT = router_mod.DEFAULT_CHECKPOINT
DEVICE_LABEL = "unknown"


def read_plugin_version(path=PLUGIN_JSON):
    """The version in plugin.json, or None when the file or the field is unreadable."""
    try:
        with open(path, encoding="utf-8") as handle:
            version = json.load(handle).get("version")
    except (OSError, ValueError, AttributeError):
        return None
    return version if isinstance(version, str) else None


# Read once at start, so the health check names the code this process runs.
PLUGIN_VERSION = read_plugin_version()


def _health_json():
    return {
        "status": "ok",
        "device": DEVICE_LABEL,
        "checkpoint": CHECKPOINT,
        "plugin_version": PLUGIN_VERSION,
    }


def _route_json(decision):
    return {
        "route": decision.route,
        "route_conf": decision.route_conf,
        "route_probs": decision.route_probs,
        "tier": decision.tier,
        "tier_conf": decision.tier_conf,
        "tier_probs": decision.tier_probs,
        "latency_ms": decision.ms,
        "by_regex": decision.by_regex,
        "route_wording": router_mod.ROUTE_WORDING,
        "tier_wording": router_mod.TIER_WORDING,
    }


def _tier_json(decision):
    return {
        "tier": decision.tier,
        "tier_conf": decision.tier_conf,
        "tier_probs": decision.tier_probs,
        "latency_ms": decision.ms,
        "tier_wording": router_mod.TIER_WORDING,
    }


class RouterHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"orchestrator router: {self.command} {self.path}", file=sys.stderr)

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_text(self):
        """Read and validate the request body. Returns (text, error)."""
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None, "invalid JSON body"
        if not isinstance(data, dict):
            return None, "invalid JSON body"
        text = data.get("text")
        if not isinstance(text, str):
            return None, "missing or non-string 'text'"
        return text[:MAX_TEXT_CHARS], None

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, _health_json())
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/route":
            text, err = self._read_text()
            if err:
                self._send_json(400, {"error": err})
                return
            decision = router_mod.route_prompt(MODEL, text)
            self._send_json(200, _route_json(decision))
            return
        if self.path == "/tier":
            text, err = self._read_text()
            if err:
                self._send_json(400, {"error": err})
                return
            decision = router_mod.tier_for_task(MODEL, text)
            self._send_json(200, _tier_json(decision))
            return
        self._send_json(404, {"error": "not found"})


def main():
    global MODEL, CHECKPOINT, DEVICE_LABEL
    parser = argparse.ArgumentParser(description="Orchestrator router HTTP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--checkpoint", default=router_mod.DEFAULT_CHECKPOINT)
    args = parser.parse_args()

    CHECKPOINT = args.checkpoint
    device = None if args.device == "auto" else args.device
    MODEL = router_mod.load_model(device, CHECKPOINT)
    DEVICE_LABEL = router_mod.device_of(MODEL)
    print(f"orchestrator router: model loaded on {DEVICE_LABEL}", file=sys.stderr)

    # One route and one tier call on realistic text, so the first hook request
    # after start does not pay for kernel warm-up.
    warm_up = router_mod.route_prompt(MODEL, WARM_UP_TEXT)
    warm_tier = router_mod.tier_for_task(MODEL, WARM_UP_TEXT)
    print(
        f"orchestrator router: warm-up done in {warm_up.ms + warm_tier.ms:.1f} ms",
        file=sys.stderr,
    )

    server = HTTPServer((args.host, args.port), RouterHandler)
    print(f"orchestrator router: listening on {args.host}:{args.port}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
