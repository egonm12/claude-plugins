"""Tests for the router service files, with laya replaced by an empty stub module.

The real model is not loaded. These tests check the question wording, the
wording ids in the answers and the plugin version in the health check.
"""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1]
ROUTER_DIR = PLUGIN / "router"

TIER_INSTRUCTIONS = ("This is a task for a worker agent. Does the worker have to work out the approach itself, "
                     "or is the approach given? Pick the smallest capability that can do it well.")
TIER_CRITERIA = {
    "a": ("Open-ended work where the worker must find its own way: researching facts outside the codebase or an "
          "unfamiliar system, finding the root cause of a failure, designing or splitting a change, or building "
          "new tooling."),
    "b": ("Work that follows a path the task already lays out: drafting or reviewing against given criteria or a "
          "checklist, taking stock of the current state, comparing two things for parity, or making a "
          "well-specified edit."),
    "c": "Mechanical work with an obvious answer: grepping, listing files, renaming, counting, or reformatting.",
}


def load_service():
    """Import router.py and server.py from the router directory with a stub laya. Leaves no modules behind."""
    saved = {name: sys.modules.get(name) for name in ("laya", "router", "server")}
    try:
        with mock.patch.object(sys, "path", [str(ROUTER_DIR)] + sys.path):
            sys.modules["laya"] = types.ModuleType("laya")
            for name in ("router", "server"):
                sys.modules.pop(name, None)
            router = importlib.import_module("router")
            server = importlib.import_module("server")
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    return router, server


class FakeModel:
    """Answers every question with key a, so the key mapping decides the labels."""

    def predict(self, text, questions):
        return {"answers": {name: {"choice": "a", "confidence": 0.5,
                                   "probabilities": dict.fromkeys(q["criteria"], 0.25)}
                            for name, q in questions.items()}}


class TierQuestionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.router, self.server = load_service()

    def test_tier_wording(self) -> None:
        question = self.router.TIER_QUESTION
        self.assertEqual(question["type"], "choice")
        self.assertEqual(question["instructions"], TIER_INSTRUCTIONS)
        self.assertEqual(question["criteria"], TIER_CRITERIA)

    def test_key_mapping(self) -> None:
        self.assertEqual(self.router.TIER_LABELS, {"a": "opus", "b": "sonnet", "c": "haiku"})
        self.assertEqual(self.router.ROUTE_LABELS, {"a": "delegate", "b": "self"})

    def test_wording_ids(self) -> None:
        self.assertEqual(self.router.TIER_WORDING, "b-2026-09-24")
        self.assertEqual(self.router.ROUTE_WORDING, "a-2026-09-23")

    def test_answers_carry_the_wording_ids(self) -> None:
        tier = self.server._tier_json(self.router.tier_for_task(FakeModel(), "grep for x"))
        self.assertEqual((tier["tier"], tier["tier_wording"]), ("opus", "b-2026-09-24"))
        route = self.server._route_json(self.router.route_prompt(FakeModel(), "why does it fail?"))
        self.assertEqual((route["route"], route["tier"], route["route_wording"], route["tier_wording"]),
                         ("delegate", "opus", "a-2026-09-23", "b-2026-09-24"))


class HealthVersionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.router, self.server = load_service()

    def test_health_names_the_plugin_version(self) -> None:
        expected = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
        self.assertEqual(self.server.PLUGIN_VERSION, expected)
        health = self.server._health_json()
        self.assertEqual((health["status"], health["plugin_version"]), ("ok", expected))

    def test_unreadable_plugin_json_gives_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(self.server.read_plugin_version(str(Path(tmp) / "missing.json")))
            for body in ("{not json", "[1]", '{"version": 5}', "{}"):
                path = Path(tmp) / "plugin.json"
                path.write_text(body, encoding="utf-8")
                self.assertIsNone(self.server.read_plugin_version(str(path)), body)


if __name__ == "__main__":
    unittest.main()
