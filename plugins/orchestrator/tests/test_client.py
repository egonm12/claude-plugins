"""Unit tests for the router HTTP client."""

from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))

from orchestrator_hooks.client import RouterClient  # noqa: E402

TIER = {"tier": "haiku", "tier_conf": 0.4, "tier_probs": {"haiku": 0.4}, "latency_ms": 90.1}


class CannedServer:
    """A local HTTP server in a thread that answers every request with one body."""

    def __init__(self, status: int, body: str) -> None:
        self.requests: List[Tuple[str, str, str]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                sent = self.rfile.read(length).decode("utf-8") if length else ""
                outer.requests.append((self.command, self.path, sent))
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = _answer
            do_POST = _answer

            def log_message(self, *args: object) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)

    def __enter__(self) -> "CannedServer":
        self.thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.server.shutdown()
        self.server.server_close()


class StubTest(unittest.TestCase):
    def test_stub_answer(self) -> None:
        answer = RouterClient("http://127.0.0.1:1", 1500, json.dumps(TIER)).tier("x")
        self.assertEqual((answer.body, answer.server, answer.latency_ms), (TIER, "stub", 0))
        self.assertTrue(answer.ok)

    def test_stub_down(self) -> None:
        answer = RouterClient("http://127.0.0.1:1", 1500, "down").route("x")
        self.assertEqual((answer.body, answer.server, answer.latency_ms), ({}, "down", 0))
        self.assertFalse(answer.ok)

    def test_stub_junk(self) -> None:
        for junk in ("{not json", "[1]", "3", ""):
            answer = RouterClient("http://127.0.0.1:1", 1500, junk).route("x")
            self.assertEqual((answer.body, answer.server), ({}, "down"), junk)


class NetworkTest(unittest.TestCase):
    def test_real_request(self) -> None:
        with CannedServer(200, json.dumps(TIER)) as server:
            answer = RouterClient(server.url + "/", 1500, None).tier("a" * 5000)
        self.assertEqual((answer.body, answer.server), (TIER, "ok"))
        self.assertIsInstance(answer.latency_ms, int)
        method, path, sent = server.requests[0]
        self.assertEqual((method, path), ("POST", "/tier"))
        self.assertEqual(len(json.loads(sent)["text"]), 4000)

    def test_route_endpoint(self) -> None:
        with CannedServer(200, '{"route": "self"}') as server:
            answer = RouterClient(server.url, 1500, None).route("hello")
        self.assertEqual(answer.body, {"route": "self"})
        self.assertEqual(server.requests[0][1], "/route")
        self.assertEqual(json.loads(server.requests[0][2]), {"text": "hello"})

    def test_error_body_counts_as_down(self) -> None:
        with CannedServer(200, '{"error": "bad"}') as server:
            answer = RouterClient(server.url, 1500, None).tier("x")
        self.assertEqual((answer.body, answer.server), ({}, "down"))

    def test_non_200_counts_as_down(self) -> None:
        with CannedServer(404, '{"error": "not found"}') as server:
            self.assertEqual(RouterClient(server.url, 1500, None).tier("x").server, "down")

    def test_non_object_body_counts_as_down(self) -> None:
        with CannedServer(200, "[1, 2]") as server:
            self.assertEqual(RouterClient(server.url, 1500, None).tier("x").server, "down")

    def test_refused_connection_is_fast(self) -> None:
        start = time.perf_counter()
        answer = RouterClient("http://127.0.0.1:1", 200, None).route("x")
        self.assertLess(time.perf_counter() - start, 1.0)
        self.assertEqual(answer.server, "down")

    def test_health(self) -> None:
        with CannedServer(200, '{"status": "ok"}') as server:
            self.assertTrue(RouterClient(server.url, 1500, None).health())
            self.assertEqual(server.requests[0][:2], ("GET", "/health"))
        self.assertFalse(RouterClient("http://127.0.0.1:1", 1500, None).health())

    def test_health_info(self) -> None:
        body = {"status": "ok", "device": "mps", "checkpoint": "c", "plugin_version": "0.5.5"}
        with CannedServer(200, json.dumps(body)) as server:
            self.assertEqual(RouterClient(server.url, 1500, None).health_info(), body)
        # A 200 without a JSON object still means up, with no version to read.
        with CannedServer(200, "not json") as server:
            self.assertEqual(RouterClient(server.url, 1500, None).health_info(), {})
        with CannedServer(500, "{}") as server:
            self.assertIsNone(RouterClient(server.url, 1500, None).health_info())
        self.assertIsNone(RouterClient("http://127.0.0.1:1", 1500, None).health_info())


if __name__ == "__main__":
    unittest.main()
