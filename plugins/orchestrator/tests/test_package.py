"""Package tests: manifests, hook registration, drift between docs and agents.

Ported from the package and drift parts of tests/gate.test.sh and
tests/router.test.sh, updated to the Python entry point in the contract.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
HOOKS_JSON = PLUGIN_ROOT / "hooks" / "hooks.json"
PLUGIN_JSON = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
APM_YML = PLUGIN_ROOT / "apm.yml"
MARKETPLACE_JSON = PLUGIN_ROOT.parents[1] / ".claude-plugin" / "marketplace.json"
PROTOCOL = PLUGIN_ROOT / "references" / "orchestrator-protocol.md"
INSTRUCTIONS = PLUGIN_ROOT / ".apm" / "instructions" / "orchestrator.instructions.md"
AGENTS_DIR = PLUGIN_ROOT / "agents"

DEFAULT_MODELS = "opus,sonnet,haiku"
EM_DASH = chr(0x2014)  # written as a code point so this file stays clean

# (hooks.json event, matcher or None, hook.py event, timeout), from the contract.
EXPECTED_REGISTRATIONS = [
    ("SessionStart", "*", "session-start", 10),
    ("UserPromptSubmit", None, "prompt", 5),
    ("PreToolUse", "Agent|Task", "agent-call", 5),
    ("PreToolUse", "Bash|Read|Grep|Glob|WebFetch|WebSearch", "tool-call", 5),
    ("PostToolUse", "Edit|Write|MultiEdit|NotebookEdit", "edit-call", 5),
    ("Stop", None, "stop", 5),
    ("SubagentStop", None, "subagent-stop", 5),
]


def command_for(event: str) -> str:
    return f'"${{ORCHESTRATOR_PYTHON:-python3}}" "${{CLAUDE_PLUGIN_ROOT}}/hooks/hook.py" {event}'


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def numbered_rules(path: Path) -> List[str]:
    return [l for l in path.read_text(encoding="utf-8").splitlines() if re.match(r"^[1-4]\. ", l)]


def registrations(hooks: Dict[str, Any]) -> List[tuple]:
    found = []
    for hook_event, entries in hooks["hooks"].items():
        for entry in entries:
            for hook in entry.get("hooks", []):
                found.append((hook_event, entry.get("matcher"), hook))
    return found


class ManifestTest(unittest.TestCase):
    def test_hooks_json_parses(self) -> None:
        self.assertIsInstance(load_json(HOOKS_JSON), dict)

    def test_plugin_json_parses(self) -> None:
        self.assertIsInstance(load_json(PLUGIN_JSON), dict)

    def test_package_version_matches_the_manifests(self) -> None:
        sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))
        from orchestrator_hooks import __version__
        self.assertEqual(__version__, load_json(PLUGIN_JSON)["version"], "plugin.json")
        apm = re.search(r"^version: (\S+)$", APM_YML.read_text(encoding="utf-8"), flags=re.MULTILINE)
        self.assertEqual(__version__, apm.group(1) if apm else None, "apm.yml")
        if MARKETPLACE_JSON.is_file():
            listed = [p["version"] for p in load_json(MARKETPLACE_JSON)["plugins"] if p["name"] == "orchestrator"]
            self.assertEqual([__version__], listed, "marketplace.json")
        repo_readme = MARKETPLACE_JSON.parent.parent / "README.md"
        if repo_readme.is_file():
            row = re.search(r"^\| \[orchestrator\]\([^)]*\) \| (\S+) \|", repo_readme.read_text(encoding="utf-8"),
                            flags=re.MULTILINE)
            self.assertEqual(__version__, row.group(1) if row else None, "repository README")


class HooksJsonTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hooks = load_json(HOOKS_JSON)

    def test_event_keys(self) -> None:
        self.assertEqual(set(self.hooks["hooks"]), {"SessionStart", "UserPromptSubmit", "PreToolUse",
                                                    "PostToolUse", "Stop", "SubagentStop"})

    def test_exactly_seven_registrations(self) -> None:
        found = [(e, m, h["command"].rsplit(" ", 1)[-1], h.get("timeout"))
                 for e, m, h in registrations(self.hooks)]
        self.assertEqual(sorted(found, key=repr), sorted(EXPECTED_REGISTRATIONS, key=repr))

    def test_one_hook_per_entry(self) -> None:
        for hook_event, entries in self.hooks["hooks"].items():
            for entry in entries:
                with self.subTest(f"{hook_event} {entry.get('matcher')}"):
                    self.assertEqual(len(entry["hooks"]), 1)

    def test_each_event_registered_once(self) -> None:
        events = [h["command"].rsplit(" ", 1)[-1] for _, _, h in registrations(self.hooks)]
        self.assertEqual(sorted(events), sorted(r[2] for r in EXPECTED_REGISTRATIONS))

    def test_commands(self) -> None:
        by_event = {(e, m): h for e, m, h in registrations(self.hooks)}
        for hook_event, matcher, event, timeout in EXPECTED_REGISTRATIONS:
            with self.subTest(event):
                hook = by_event[(hook_event, matcher)]
                self.assertEqual(hook["type"], "command")
                # The path is quoted, so the command ends in: hook.py" <event>
                self.assertRegex(hook["command"], rf'hook\.py"? {re.escape(event)}$')
                self.assertIn("${ORCHESTRATOR_PYTHON:-python3}", hook["command"])
                self.assertEqual(hook["command"], command_for(event))
                self.assertEqual(hook["timeout"], timeout)

    def test_registered_entry_point_exists(self) -> None:
        # Port of "every registered script exists". Fails until hooks/hook.py is written.
        self.assertTrue((PLUGIN_ROOT / "hooks" / "hook.py").is_file(), "hooks/hook.py is missing")


class DriftTest(unittest.TestCase):
    def test_protocol_has_four_rules(self) -> None:
        self.assertEqual(len(numbered_rules(PROTOCOL)), 4)

    def test_agent_rules_match_protocol(self) -> None:
        agents = sorted(AGENTS_DIR.glob("*.md"))
        self.assertTrue(agents, "no agent files")
        for agent in agents:
            with self.subTest(agent.name):
                self.assertEqual(numbered_rules(agent), numbered_rules(PROTOCOL))

    def test_model_table_matches_gate_default(self) -> None:
        text = PROTOCOL.read_text(encoding="utf-8")
        table = re.findall(r"^\| `([a-z]+)` \|", text, flags=re.MULTILINE)
        self.assertEqual(",".join(table), DEFAULT_MODELS)

    def test_one_reminder_line(self) -> None:
        lines = [l for l in PROTOCOL.read_text(encoding="utf-8").splitlines()
                 if l.startswith("> Before you start:")]
        self.assertEqual(len(lines), 1)

    def test_instructions_name_no_model(self) -> None:
        text = INSTRUCTIONS.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"opus|sonnet|haiku|fable", text, flags=re.IGNORECASE),
                          "instructions name a model, but they must stay tool-neutral")


class StyleTest(unittest.TestCase):
    def test_no_em_dash_in_python_files(self) -> None:
        files = sorted((PLUGIN_ROOT / "hooks").rglob("*.py")) + sorted((PLUGIN_ROOT / "tests").rglob("*.py"))
        self.assertTrue(files)
        for path in files:
            with self.subTest(str(path.relative_to(PLUGIN_ROOT))):
                self.assertNotIn(EM_DASH, path.read_text(encoding="utf-8"))

    def test_no_em_dash_in_hooks_json(self) -> None:
        self.assertNotIn(EM_DASH, HOOKS_JSON.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
