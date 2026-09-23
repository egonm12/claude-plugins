"""Seam tests: run hooks/hook.py the way Claude Code runs it.

Each test starts the entry point as a subprocess, sends a JSON payload on
stdin and checks stdout, stderr, the exit code, the state file and the log.
The cases are ported from tests/gate.test.sh and tests/router.test.sh.
Case names from the bash suites appear as test names or subtest labels.
The contract in .scratch/router-contract.md wins where the two differ.

No test calls the network. Every run gets ORCHESTRATOR_ROUTER_URL pointing
at a closed local port unless the case sets its own, and most router cases
use ORCHESTRATOR_ROUTER_STUB.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
HOOK = PLUGIN_ROOT / "hooks" / "hook.py"
PROTOCOL = PLUGIN_ROOT / "references" / "orchestrator-protocol.md"

# A closed port: a refused connection counts as "router down" and is fast.
CLOSED_URL = "http://127.0.0.1:1"

TS_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"

# Router answers for the stub, copied from router.test.sh.
STUB_DELEGATE = json.dumps({
    "route": "delegate", "route_conf": 0.123,
    "route_probs": {"delegate": 0.66, "self": 0.34},
    "tier": "sonnet", "tier_conf": 0.2,
    "tier_probs": {"opus": 0.3, "sonnet": 0.5, "haiku": 0.2},
    "latency_ms": 114.2, "by_regex": False,
})
STUB_SELF = json.dumps({
    "route": "self", "route_conf": 0.3,
    "route_probs": {"delegate": 0.35, "self": 0.65},
    "tier": "haiku", "tier_conf": 0.1,
    "tier_probs": {"opus": 0.3, "sonnet": 0.3, "haiku": 0.4},
    "latency_ms": 101.0, "by_regex": False,
})
STUB_SKILL = json.dumps({
    "route": "skill", "route_conf": 1.0, "route_probs": {},
    "tier": "none", "tier_conf": 0.0, "tier_probs": {},
    "latency_ms": 0.0, "by_regex": True,
})
# The real verdict that motivated the unsure route: a clear investigation scored as self.
STUB_CLOSE_SELF = json.dumps({
    "route": "self", "route_conf": 0.0279,
    "route_probs": {"delegate": 0.4721, "self": 0.5279},
    "tier": "sonnet", "tier_conf": 0.2,
    "tier_probs": {"opus": 0.3, "sonnet": 0.5, "haiku": 0.2},
    "latency_ms": 97.0, "by_regex": False,
})
STUB_TIER_HAIKU = json.dumps({
    "tier": "haiku", "tier_conf": 0.8,
    "tier_probs": {"opus": 0.05, "sonnet": 0.15, "haiku": 0.8},
    "latency_ms": 90.1,
})
STUB_TIER_OPUS = json.dumps({
    "tier": "opus", "tier_conf": 0.6,
    "tier_probs": {"opus": 0.6, "sonnet": 0.3, "haiku": 0.1},
    "latency_ms": 88.0,
})
# The real case that motivated the downgrade guard: opus given, haiku the router's top pick, but too
# close to sonnet and opus to act on with confidence.
STUB_TIER_CLOSE_HAIKU = json.dumps({
    "tier": "haiku", "tier_conf": 0.3764,
    "tier_probs": {"opus": 0.3317, "sonnet": 0.292, "haiku": 0.3764},
    "latency_ms": 91.0,
})

# Message texts. The gate and fallback texts are "as today" in the contract.
FALLBACK_PROTOCOL = (
    "orchestrator is active. Delegate reading and searching to workers, state a model on "
    "every Agent call, never use fable, and require verified evidence in every worker report."
)
FALLBACK_REMINDER = (
    "orchestrator: Before you start, decide whether this needs workers. "
    "Delegate research, keep actions and decisions."
)
REMINDER_PATTERN = (
    r"^orchestrator: Before you start: if this needs more than two exploratory commands"
)
DELEGATE_LINE = (
    "orchestrator router: this prompt looks like an investigation (delegate, confidence 0.12, "
    "tier sonnet). Delegate the research to a worker before running commands."
)
START_LINE = (
    "orchestrator router: starting the router daemon on http://127.0.0.1:1. "
    "First answers arrive after the model loads."
)
GATE_NO_MODEL = (
    "orchestrator: This Agent call sets no model. The effective model comes from the agent "
    "definition or the configured default, which this hook cannot read. Set model explicitly "
    "so the choice is stated, or confirm the agent definition pins a non-Fable model."
)
GATE_FORK = (
    "orchestrator: This is a fork. It ignores any model override and runs on the session "
    "model, which this hook cannot read. It also inherits your full conversation. Confirm the "
    "session is not on Fable, and say in your next message why a fork was needed instead of "
    "a fresh worker."
)


def gate_unknown(model: str, allowed: str = "opus, sonnet, haiku") -> str:
    return (
        f'orchestrator: This Agent call sets model "{model}", which is not in the allowed '
        f"list ({allowed}). Check it for a typo. If you meant it, say why in your next message."
    )


def pick_set(tier: str) -> str:
    return f'orchestrator: the router set model "{tier}" for this worker.'


def pick_replace(tier: str, given: str) -> str:
    return f'orchestrator: the router set model "{tier}" for this worker, replacing "{given}".'


FLOOR_NOTE = "the task reads as judgement work, so the router did not use haiku."


def exploration_msg(n: int, threshold: int, route: str) -> str:
    return (
        f"orchestrator router: {n} exploratory commands this turn, threshold {threshold} "
        f"(verdict {route}). Hand the rest of the research to a worker."
    )


def protocol_reminder() -> str:
    for line in PROTOCOL.read_text(encoding="utf-8").splitlines():
        if line.startswith("> Before you start:"):
            return "orchestrator: " + line[2:]
    raise AssertionError("protocol has no '> Before you start:' line")


# ---------------------------------------------------------------- helpers


@dataclass
class Result:
    stdout: str
    stderr: str
    returncode: int

    @property
    def lines(self) -> List[str]:
        return self.stdout.splitlines()


def build_env(
    data_dir: Union[str, Path],
    env: Optional[Mapping[str, str]] = None,
    plugin_root: Optional[Union[str, Path]] = None,
) -> Dict[str, str]:
    """A clean environment: no ORCHESTRATOR_* or CLAUDE_PLUGIN_* from the caller."""
    base = {
        k: v for k, v in os.environ.items()
        if not k.startswith("ORCHESTRATOR_") and not k.startswith("CLAUDE_PLUGIN_")
    }
    base["CLAUDE_PLUGIN_DATA"] = str(data_dir)
    base["CLAUDE_PLUGIN_ROOT"] = str(plugin_root if plugin_root is not None else PLUGIN_ROOT)
    # Keep the suite off the network, as router.test.sh did. A case may override it.
    base["ORCHESTRATOR_ROUTER_URL"] = CLOSED_URL
    if env:
        for key, value in env.items():
            if value is None:
                base.pop(key, None)
            else:
                base[key] = value
    return base


def run_hook(
    event: str,
    payload: Union[Dict[str, Any], str],
    env: Optional[Mapping[str, str]] = None,
    data_dir: Optional[Union[str, Path]] = None,
    plugin_root: Optional[Union[str, Path]] = None,
) -> Result:
    """Run hook.py with one event, like Claude Code does. A str payload is sent raw."""
    if data_dir is None:
        raise ValueError("data_dir is required")
    if isinstance(payload, str):
        stdin = payload
    else:
        stdin = json.dumps(payload, separators=(",", ":"))
    proc = subprocess.run(
        [sys.executable, str(HOOK), event],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=10,
        env=build_env(data_dir, env, plugin_root),
    )
    return Result(proc.stdout, proc.stderr, proc.returncode)


def parse_json(stdout: str) -> Dict[str, Any]:
    """Parse stdout as exactly one JSON object."""
    value = json.loads(stdout)
    if not isinstance(value, dict):
        raise AssertionError(f"stdout is not a JSON object: {stdout!r}")
    return value


def read_state(data_dir: Union[str, Path], session: str) -> Optional[Dict[str, Any]]:
    path = Path(data_dir) / "state" / f"{session}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_log(data_dir: Union[str, Path]) -> List[Dict[str, Any]]:
    path = Path(data_dir) / "router-log.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def prompt_payload(session: str, prompt: str) -> Dict[str, Any]:
    return {"session_id": session, "prompt": prompt, "cwd": "/work"}


def tool_payload(
    session: str, tool: str, tool_input: Any, agent_id: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"session_id": session, "tool_name": tool, "tool_input": tool_input}
    if agent_id:
        payload["agent_id"] = agent_id
    return payload


def bash_payload(session: str, command: str) -> Dict[str, Any]:
    return tool_payload(session, "Bash", {"command": command})


def read_payload(session: str) -> Dict[str, Any]:
    return tool_payload(session, "Read", {"file_path": "/x"})


def agent_payload(tool_input: Any, tool: str = "Agent") -> Dict[str, Any]:
    return {"tool_name": tool, "tool_input": tool_input}


class SeamCase(unittest.TestCase):
    """Fresh data directory per test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.data = self.tmp / "data"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # Run helpers bound to this test's data dir.
    def hook(self, event: str, payload: Union[Dict[str, Any], str], plugin_root=None, **env: str) -> Result:
        return run_hook(event, payload, env=env, data_dir=self.data, plugin_root=plugin_root)

    def start_turn(self, session: str, stub: str, prompt: str = "look into this for me", **env: str) -> Result:
        result = self.hook("prompt", prompt_payload(session, prompt), ORCHESTRATOR_ROUTER_STUB=stub, **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def state(self, session: str) -> Optional[Dict[str, Any]]:
        return read_state(self.data, session)

    def log(self, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        records = read_log(self.data)
        if kind is None:
            return records
        return [r for r in records if r.get("kind") == kind]

    # Assertion helpers.
    def assertSilent(self, result: Result) -> None:
        """Exit 0, nothing on stdout, nothing on stderr."""
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def assertOk(self, result: Result) -> None:
        """Exit 0 and nothing on stderr."""
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def assertDenied(self, result: Result) -> None:
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("Blocked by orchestrator", result.stderr)


# ---------------------------------------------------------------- session-start


class SessionStartTest(SeamCase):
    def setUp(self) -> None:
        super().setUp()
        self.fake = self.tmp / "fake-python"
        self.args = self.tmp / "fake-args"
        self.fake.write_text(
            "#!/bin/sh\n" f"printf '%s\\n' \"$*\" >>'{self.args}'\n" "exit 0\n",
            encoding="utf-8",
        )
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        self.plugin = self.tmp / "plugin"
        (self.plugin / "router").mkdir(parents=True)

    def wait_for_args(self) -> str:
        for _ in range(30):
            if self.args.exists() and self.args.stat().st_size > 0:
                break
            time.sleep(0.1)
        return self.args.read_text(encoding="utf-8") if self.args.exists() else ""

    def start_env(self, **extra: str) -> Dict[str, str]:
        env = {"ORCHESTRATOR_ROUTER_PYTHON": str(self.fake), "ORCHESTRATOR_ROUTER_URL": CLOSED_URL}
        env.update(extra)
        return env

    def assertProtocolOnly(self, result: Result) -> None:
        self.assertOk(result)
        self.assertEqual(result.stdout.rstrip("\n"), PROTOCOL.read_text(encoding="utf-8").rstrip("\n"))
        self.assertNotIn("orchestrator router:", result.stdout)

    def test_prints_protocol_with_plugin_root(self) -> None:
        self.assertProtocolOnly(self.hook("session-start", {}))

    def test_fallback_with_missing_root(self) -> None:
        result = self.hook("session-start", {}, plugin_root=self.tmp / "missing")
        self.assertOk(result)
        self.assertEqual(result.lines[0], FALLBACK_PROTOCOL)

    def test_fallback_with_empty_root(self) -> None:
        result = self.hook("session-start", {}, plugin_root="")
        self.assertOk(result)
        self.assertIn(FALLBACK_PROTOCOL, result.lines)

    def test_off_switch(self) -> None:
        self.assertSilent(self.hook("session-start", {}, ORCHESTRATOR_OFF="1"))

    def test_start_off_switch(self) -> None:
        # Router off: the protocol only, and the daemon is not started.
        result = self.hook("session-start", {}, **self.start_env(ORCHESTRATOR_ROUTER_OFF="1"))
        self.assertProtocolOnly(result)
        self.assertFalse(self.args.exists(), "fake python ran with the router off")

    def test_start_with_stub(self) -> None:
        result = self.hook("session-start", {}, **self.start_env(ORCHESTRATOR_ROUTER_STUB=STUB_SELF))
        self.assertProtocolOnly(result)
        self.assertFalse(self.args.exists(), "fake python ran with a stub set")

    def test_start_with_stub_temp_plugin(self) -> None:
        (self.plugin / "router" / "server.py").touch()
        result = self.hook(
            "session-start", {}, plugin_root=self.plugin,
            **self.start_env(ORCHESTRATOR_ROUTER_STUB=STUB_SELF),
        )
        self.assertOk(result)
        self.assertNotIn(START_LINE, result.lines)
        self.assertFalse(self.args.exists())

    def test_start_launches(self) -> None:
        (self.plugin / "router" / "server.py").touch()
        result = self.hook("session-start", {}, plugin_root=self.plugin, **self.start_env())
        self.assertOk(result)
        self.assertEqual(result.lines.count(START_LINE), 1, result.stdout)
        # The temp plugin has no protocol, so the fallback comes first.
        self.assertEqual(result.lines, [FALLBACK_PROTOCOL, START_LINE])
        pid_text = (self.data / "router-server.pid").read_text(encoding="utf-8").strip()
        self.assertRegex(pid_text, r"^\d+$")
        self.assertEqual(self.wait_for_args().strip(), f"{self.plugin}/router/server.py --port 1")

    def test_start_dead_pid_does_not_stop_start(self) -> None:
        (self.plugin / "router" / "server.py").touch()
        self.data.mkdir(parents=True)
        (self.data / "router-server.pid").write_text("999999\n", encoding="utf-8")
        result = self.hook("session-start", {}, plugin_root=self.plugin, **self.start_env())
        self.assertOk(result)
        self.assertIn(START_LINE, result.lines)
        pid_text = (self.data / "router-server.pid").read_text(encoding="utf-8").strip()
        self.assertRegex(pid_text, r"^\d+$")
        self.assertNotEqual(pid_text, "999999", "pid file not rewritten")

    def test_start_default_port(self) -> None:
        (self.plugin / "router" / "server.py").touch()
        result = self.hook(
            "session-start", {}, plugin_root=self.plugin,
            **self.start_env(ORCHESTRATOR_ROUTER_URL="http://127.0.0.1"),
        )
        self.assertOk(result)
        self.assertTrue(
            any(l.startswith("orchestrator router: starting the router daemon") for l in result.lines),
            result.stdout,
        )
        self.assertRegex(self.wait_for_args().strip(), r"--port 8790$")

    def test_start_without_server_py(self) -> None:
        result = self.hook("session-start", {}, plugin_root=self.plugin, **self.start_env())
        self.assertOk(result)
        self.assertNotIn(START_LINE, result.lines)
        self.assertFalse(self.args.exists())

    def test_start_without_python(self) -> None:
        (self.plugin / "router" / "server.py").touch()
        result = self.hook(
            "session-start", {}, plugin_root=self.plugin,
            **self.start_env(ORCHESTRATOR_ROUTER_PYTHON=str(self.tmp / "missing-python")),
        )
        self.assertOk(result)
        self.assertNotIn(START_LINE, result.lines)

    def test_start_live_pid(self) -> None:
        (self.plugin / "router" / "server.py").touch()
        self.data.mkdir(parents=True)
        (self.data / "router-server.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
        result = self.hook("session-start", {}, plugin_root=self.plugin, **self.start_env())
        self.assertOk(result)
        self.assertNotIn(START_LINE, result.lines)
        self.assertFalse(self.args.exists(), "fake python ran on a silent path")


# ---------------------------------------------------------------- prompt


class PromptReminderTest(SeamCase):
    def test_reminder_text(self) -> None:
        result = self.hook("prompt", {"prompt": "x"}, ORCHESTRATOR_ROUTER_STUB="down")
        self.assertOk(result)
        self.assertRegex(result.lines[0], REMINDER_PATTERN)
        self.assertEqual(result.lines[0], protocol_reminder())
        self.assertTrue(result.stdout.endswith("\n"))

    def test_reminder_fallback(self) -> None:
        result = self.hook("prompt", {"prompt": "x"}, plugin_root=self.tmp / "missing",
                           ORCHESTRATOR_ROUTER_STUB="down")
        self.assertOk(result)
        self.assertEqual(result.lines[0], FALLBACK_REMINDER)

    def test_reminder_off(self) -> None:
        self.assertSilent(self.hook("prompt", {"prompt": "x"}, ORCHESTRATOR_OFF="1"))

    def test_hint_off_switch(self) -> None:
        result = self.hook("prompt", prompt_payload("s1", "x"),
                           ORCHESTRATOR_ROUTER_STUB=STUB_DELEGATE, ORCHESTRATOR_OFF="1")
        self.assertSilent(result)
        self.assertIsNone(self.state("s1"))

    def test_hint_router_off(self) -> None:
        result = self.hook("prompt", prompt_payload("s1", "x"),
                           ORCHESTRATOR_ROUTER_STUB=STUB_DELEGATE, ORCHESTRATOR_ROUTER_OFF="1")
        self.assertOk(result)
        self.assertEqual(result.lines, [protocol_reminder()])
        self.assertIsNone(self.state("s1"), "state written with the router off")
        self.assertEqual(self.log(), [])

    def test_malformed_and_empty_payload_still_remind(self) -> None:
        for label, payload in (("malformed payload", "{not json"), ("empty payload", ""),
                               ("non-object payload", "[1, 2]")):
            with self.subTest(label):
                result = self.hook("prompt", payload, ORCHESTRATOR_ROUTER_STUB=STUB_SELF)
                self.assertOk(result)
                self.assertEqual(result.lines[0], protocol_reminder())


class PromptHintTest(SeamCase):
    def test_hint_delegate(self) -> None:
        result = self.hook("prompt", prompt_payload("s1", "why does the build fail"),
                           ORCHESTRATOR_ROUTER_STUB=STUB_DELEGATE)
        self.assertOk(result)
        # The reminder comes first, then the hint: two lines.
        self.assertEqual(result.lines, [protocol_reminder(), DELEGATE_LINE])
        self.assertTrue(result.stdout.endswith("\n"))

        st = self.state("s1")
        self.assertIsNotNone(st)
        with self.subTest("hint state: turn"):
            self.assertEqual(st["turn"], 1)
        with self.subTest("hint state: route"):
            self.assertEqual(st["route"], "delegate")
        with self.subTest("hint state: route_conf"):
            self.assertEqual(st["route_conf"], 0.123)
        with self.subTest("hint state: tier"):
            self.assertEqual(st["tier"], "sonnet")
        with self.subTest("hint state: threshold"):
            self.assertEqual(st["threshold"], 2)
        with self.subTest("hint state: prompt"):
            self.assertEqual(st["prompt"], "why does the build fail")
        with self.subTest("hint state: counters are numbers at 0"):
            for key in ("n_exploratory", "n_agent", "n_tool"):
                self.assertIsInstance(st[key], int)
                self.assertNotIsInstance(st[key], bool)
                self.assertEqual(st[key], 0)
        with self.subTest("hint state: flags"):
            self.assertIs(st["warned"], False)
            self.assertIs(st["finalized"], False)
        with self.subTest("hint state: server"):
            self.assertEqual(st["server"], "stub")
        with self.subTest("hint state: session"):
            self.assertEqual(st["session_id"], "s1")
        with self.subTest("hint state: turn_started"):
            self.assertRegex(st["turn_started"], TS_PATTERN)

        prompts = self.log("prompt")
        with self.subTest("hint log: one prompt record"):
            self.assertEqual(len(prompts), 1)
        rec = prompts[0]
        with self.subTest("hint log: server stub"):
            self.assertEqual(rec["server"], "stub")
        with self.subTest("hint log: fields"):
            self.assertEqual(
                (rec["session_id"], rec["turn"], rec["cwd"], rec["text"],
                 rec["verdict"]["route"], rec["verdict"]["tier"], rec["verdict"]["by_regex"]),
                ("s1", 1, "/work", "why does the build fail", "delegate", "sonnet", False),
            )
        with self.subTest("hint log: probs kept"):
            self.assertEqual(rec["verdict"]["route_probs"]["delegate"], 0.66)
        with self.subTest("hint log: latency is a whole number"):
            self.assertIsInstance(rec["latency_ms"], int)
        with self.subTest("hint log: ts"):
            self.assertRegex(rec["ts"], TS_PATTERN)

    def test_hint_second_prompt(self) -> None:
        self.start_turn("s1", STUB_DELEGATE)
        result = self.hook("prompt", prompt_payload("s1", "thanks, that answers my question"),
                           ORCHESTRATOR_ROUTER_STUB=STUB_SELF)
        self.assertOk(result)
        self.assertEqual(result.lines, [protocol_reminder()])
        st = self.state("s1")
        with self.subTest("hint second prompt: turn"):
            self.assertEqual(st["turn"], 2)
        with self.subTest("hint second prompt: threshold after self"):
            self.assertEqual(st["threshold"], 5)
        with self.subTest("hint second prompt: prompt replaced"):
            self.assertEqual(st["prompt"], "thanks, that answers my question")
        outcomes = self.log("prompt_outcome")
        with self.subTest("hint second prompt: outcome"):
            self.assertEqual(
                [(o["source"], o["turn"], o["n_tool"], o["warned"]) for o in outcomes],
                [("next_prompt", 1, 0, False)],
            )
        with self.subTest("hint second prompt: record order"):
            self.assertEqual([r["kind"] for r in self.log()], ["prompt", "prompt_outcome", "prompt"])

    def test_hint_only_on_delegate(self) -> None:
        for label, stub in (("self", STUB_SELF), ("skill", STUB_SKILL), ("down", "down"),
                            ("bad stub", "{not json"), ("junk stub", "junk"), ("array stub", "[1]")):
            with self.subTest(label):
                data = self.tmp / f"data-{label.replace(' ', '-')}"
                result = run_hook("prompt", prompt_payload("s1", "hello"),
                                  env={"ORCHESTRATOR_ROUTER_STUB": stub}, data_dir=data)
                self.assertOk(result)
                self.assertEqual(result.lines, [protocol_reminder()])

    def test_hint_skill(self) -> None:
        self.start_turn("s1", STUB_SKILL, prompt="/commit")
        st = self.state("s1")
        self.assertEqual((st["route"], st["tier"], st["threshold"]), ("skill", "none", 3))

    def test_hint_down(self) -> None:
        self.start_turn("s1", "down", prompt="hello")
        st = self.state("s1")
        with self.subTest("hint down: state"):
            self.assertEqual((st["route"], st["tier"], st["threshold"], st["server"]),
                             ("none", "none", 3, "down"))
            self.assertEqual(st["route_conf"], 0)
        rec = self.log("prompt")[0]
        with self.subTest("hint down: log server"):
            self.assertEqual(rec["server"], "down")
        with self.subTest("hint down: empty verdict"):
            v = rec["verdict"]
            self.assertEqual((v["route"], v["route_probs"], v["tier"], v["tier_probs"]),
                             ("none", {}, "none", {}))
            self.assertEqual(v["route_conf"], 0)
            self.assertEqual(v["tier_conf"], 0)

    def test_hint_bad_stub(self) -> None:
        for label, stub in (("hint bad stub", "{not json"), ("junk stub", "junk")):
            with self.subTest(label):
                data = self.tmp / f"data-{label.replace(' ', '-')}"
                self.assertOk(run_hook("prompt", prompt_payload("s1", "hello"),
                                       env={"ORCHESTRATOR_ROUTER_STUB": stub}, data_dir=data))
                st = read_state(data, "s1")
                self.assertIsNotNone(st)
                self.assertEqual(st["server"], "down")
                self.assertEqual(st["route"], "none")
                self.assertEqual(st["threshold"], 3)

    def test_hint_no_cwd(self) -> None:
        self.assertOk(self.hook("prompt", {"session_id": "s1", "prompt": "x"}, ORCHESTRATOR_ROUTER_STUB=STUB_SELF))
        records = self.log("prompt")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["cwd"], os.getcwd())

    def test_hint_no_session(self) -> None:
        self.assertOk(self.hook("prompt", {"prompt": "x"}, ORCHESTRATOR_ROUTER_STUB=STUB_SELF))
        st = self.state("unknown")
        self.assertIsNotNone(st)
        self.assertEqual(st["session_id"], "unknown")

    def test_hint_odd_session(self) -> None:
        result = self.hook("prompt", prompt_payload("../../evil", "x"), ORCHESTRATOR_ROUTER_STUB=STUB_SELF)
        self.assertOk(result)
        self.assertFalse((self.tmp / "evil.json").exists(), "state written outside the state dir")
        self.assertFalse((self.data / "evil.json").exists(), "state written outside the state dir")
        files = os.listdir(self.data / "state")
        self.assertEqual(len(files), 1, files)
        self.assertRegex(files[0], r"^[A-Za-z0-9._-]+\.json$")

    def test_hint_long_text(self) -> None:
        self.start_turn("s1", STUB_SELF, prompt="a" * 4100)
        self.assertEqual(len(self.log("prompt")[0]["text"]), 4000)
        self.assertEqual(len(self.state("s1")["prompt"]), 4000)

    def test_hint_log_off(self) -> None:
        result = self.hook("prompt", prompt_payload("s1", "x"),
                           ORCHESTRATOR_ROUTER_STUB=STUB_DELEGATE, ORCHESTRATOR_LOG_OFF="1")
        self.assertOk(result)
        self.assertTrue(result.lines[1].startswith("orchestrator router"))
        self.assertFalse((self.data / "router-log.jsonl").exists(), "log file written")
        self.assertEqual(self.state("s1")["turn"], 1)

    def test_hint_threshold_overrides(self) -> None:
        cases = (
            ("hint threshold override delegate", "t1", STUB_DELEGATE, {"ORCHESTRATOR_THRESHOLD_DELEGATE": "4"}, 4),
            ("hint threshold override self", "t2", STUB_SELF, {"ORCHESTRATOR_THRESHOLD_SELF": "7"}, 7),
            ("hint threshold override default", "t3", "down", {"ORCHESTRATOR_THRESHOLD_DEFAULT": "1"}, 1),
            ("hint threshold bad override", "t4", STUB_DELEGATE, {"ORCHESTRATOR_THRESHOLD_DELEGATE": "abc"}, 2),
            ("bad self override", "t5", STUB_SELF, {"ORCHESTRATOR_THRESHOLD_SELF": "x1"}, 5),
            ("bad default override", "t6", STUB_SKILL, {"ORCHESTRATOR_THRESHOLD_DEFAULT": ""}, 3),
        )
        for label, session, stub, env, want in cases:
            with self.subTest(label):
                self.start_turn(session, stub, **env)
                self.assertEqual(self.state(session)["threshold"], want)

    def test_hint_refused_connection(self) -> None:
        t0 = time.monotonic()
        result = self.hook("prompt", prompt_payload("s1", "x"),
                           ORCHESTRATOR_ROUTER_URL=CLOSED_URL, ORCHESTRATOR_ROUTER_TIMEOUT_MS="200")
        elapsed = time.monotonic() - t0
        self.assertOk(result)
        self.assertEqual(result.lines, [protocol_reminder()])
        self.assertLess(elapsed, 3.0, f"took {elapsed:.2f} s")
        self.assertEqual(self.state("s1")["server"], "down")
        self.assertEqual(self.log("prompt")[0]["server"], "down")


class PromptUnsureAndCarryTest(SeamCase):
    def test_close_verdict_is_unsure(self) -> None:
        result = self.start_turn("s1", STUB_CLOSE_SELF, prompt="find out why the nightly job stopped")
        self.assertEqual(result.lines, [protocol_reminder()])
        st = self.state("s1")
        self.assertEqual((st["route"], st["threshold"]), ("unsure", 3))
        rec = self.log("prompt")[0]
        self.assertEqual(rec["verdict"]["route"], "self")
        self.assertEqual((rec["route_effective"], rec["margin"], rec["carried_from_turn"]), ("unsure", 0.0558, None))

    def test_margin_setting(self) -> None:
        self.start_turn("s1", STUB_CLOSE_SELF, ORCHESTRATOR_ROUTE_MARGIN="0.05")
        self.assertEqual((self.state("s1")["route"], self.state("s1")["threshold"]), ("self", 5))
        self.start_turn("s2", STUB_CLOSE_SELF, ORCHESTRATOR_ROUTE_MARGIN="high")
        self.assertEqual(self.state("s2")["route"], "unsure")

    def test_regex_verdict_is_never_unsure(self) -> None:
        stub = json.dumps({"route": "skill", "route_conf": 1.0, "route_probs": {"delegate": 0.5, "self": 0.5},
                           "tier": "none", "by_regex": True})
        self.start_turn("s1", stub, prompt="/commit")
        self.assertEqual(self.state("s1")["route"], "skill")
        self.assertEqual(self.log("prompt")[0]["route_effective"], "skill")

    def test_continue_carries_the_delegate_verdict(self) -> None:
        self.start_turn("s1", STUB_DELEGATE, prompt="why does the build fail")
        result = self.start_turn("s1", STUB_SELF, prompt="continue")
        self.assertEqual(result.lines, [protocol_reminder(), DELEGATE_LINE])
        st = self.state("s1")
        self.assertEqual((st["turn"], st["route"], st["tier"], st["threshold"]), (2, "delegate", "sonnet", 2))
        rec = self.log("prompt")[-1]
        self.assertEqual((rec["verdict"]["route"], rec["verdict"]["tier"]), ("self", "haiku"))
        self.assertEqual((rec["route_effective"], rec["carried_from_turn"]), ("delegate", 1))
        self.assertEqual([r["kind"] for r in self.log()], ["prompt", "prompt_outcome", "prompt"])

    def test_carried_threshold_drives_the_counter(self) -> None:
        self.start_turn("s1", STUB_DELEGATE, prompt="why does the build fail")
        self.start_turn("s1", STUB_SELF, prompt="go on")
        for _ in range(2):
            self.assertSilent(self.hook("tool-call", read_payload("s1")))
        result = self.hook("tool-call", read_payload("s1"))
        self.assertEqual(parse_json(result.stdout)["systemMessage"], exploration_msg(3, 2, "delegate"))

    def test_six_words_do_not_carry(self) -> None:
        self.start_turn("s1", STUB_DELEGATE, prompt="why does the build fail")
        result = self.start_turn("s1", STUB_SELF, prompt="yes, branch and open a PR")
        self.assertEqual(result.lines, [protocol_reminder()])
        self.assertEqual((self.state("s1")["route"], self.state("s1")["threshold"]), ("self", 5))
        self.assertIsNone(self.log("prompt")[-1]["carried_from_turn"])

    def test_first_turn_and_carry_off(self) -> None:
        self.start_turn("s1", STUB_SELF, prompt="continue")
        self.assertIsNone(self.log("prompt")[-1]["carried_from_turn"])
        self.start_turn("s2", STUB_DELEGATE, prompt="why does the build fail")
        self.start_turn("s2", STUB_SELF, prompt="continue", ORCHESTRATOR_CARRY_WORDS="0")
        self.assertEqual(self.state("s2")["route"], "self")


# ---------------------------------------------------------------- prompt: worker reports


class WorkerReportTest(SeamCase):
    def report(self, session: str, text: str, **env: str) -> Result:
        return self.hook("prompt", prompt_payload(session, text), ORCHESTRATOR_ROUTER_STUB=STUB_DELEGATE, **env)

    def test_agent_message_and_task_notification_produce_no_output(self) -> None:
        for label, text in (
            ("agent-message", '<agent-message from="a2c95a8d059e8622e">done</agent-message>'),
            ("task-notification", "<task-notification>\n<task-id>abc</task-id>"),
            ("leading whitespace", '  \n<agent-message from="x">'),
        ):
            with self.subTest(label):
                self.assertSilent(self.report(f"w-{label}", text))

    def test_no_turn_started_and_no_prompt_record(self) -> None:
        self.report("s1", '<agent-message from="x">done</agent-message>')
        self.assertIsNone(self.state("s1"))
        self.assertEqual(self.log(), [])

    def test_keeps_the_current_turn_and_its_counters(self) -> None:
        self.start_turn("s1", STUB_DELEGATE, prompt="why does the build fail")
        self.assertSilent(self.hook("tool-call", read_payload("s1")))
        before = self.state("s1")
        self.assertSilent(self.report("s1", '<agent-message from="x">done</agent-message>'))
        after = self.state("s1")
        self.assertEqual((after["turn"], after["route"], after["tier"], after["n_tool"], after["n_exploratory"],
                          after["prompt"]),
                         (before["turn"], before["route"], before["tier"], before["n_tool"],
                          before["n_exploratory"], before["prompt"]))
        self.assertIs(after["finalized"], False)
        self.assertEqual(self.log(), [r for r in self.log() if r["kind"] == "prompt"])

    def test_reopens_a_finalized_turn_for_a_fresh_outcome(self) -> None:
        self.start_turn("s1", STUB_DELEGATE, prompt="why does the build fail")
        self.assertSilent(self.hook("tool-call", read_payload("s1")))
        self.assertSilent(self.hook("stop", {"session_id": "s1"}))
        self.assertIs(self.state("s1")["finalized"], True)
        self.assertEqual(len(self.log("prompt_outcome")), 1)

        self.assertSilent(self.report("s1", "<task-notification>\n<task-id>1</task-id>"))
        self.assertIs(self.state("s1")["finalized"], False)
        self.assertEqual(len(self.log("prompt_outcome")), 1, "no outcome written just by reopening")

        self.assertSilent(self.hook("tool-call", read_payload("s1")))
        self.assertSilent(self.hook("stop", {"session_id": "s1"}))
        outcomes = self.log("prompt_outcome")
        self.assertEqual(len(outcomes), 2)
        self.assertEqual([o["turn"] for o in outcomes], [1, 1])
        self.assertEqual(outcomes[-1]["n_tool"], 2)

    def test_exploration_warning_still_fires_at_most_once_after_a_worker_report(self) -> None:
        self.start_turn("s1", STUB_DELEGATE, prompt="why does the build fail")
        self.assertSilent(self.hook("tool-call", read_payload("s1")))
        self.assertSilent(self.hook("stop", {"session_id": "s1"}))
        self.assertSilent(self.report("s1", '<agent-message from="x">done</agent-message>'))

        # Threshold 2: one more silent call, then the warning, and never a second one.
        self.assertSilent(self.hook("tool-call", read_payload("s1")))
        first_warning = self.hook("tool-call", read_payload("s1"))
        self.assertOk(first_warning)
        self.assertIn("exploratory commands", parse_json(first_warning.stdout)["systemMessage"])
        self.assertSilent(self.hook("tool-call", read_payload("s1")))
        self.assertEqual(len(self.log("exploration_warning")), 1)

    def test_router_off_does_not_reopen_a_finalized_turn(self) -> None:
        self.start_turn("s1", STUB_DELEGATE, prompt="why does the build fail")
        self.assertSilent(self.hook("stop", {"session_id": "s1"}))
        self.assertSilent(self.report("s1", '<agent-message from="x">done</agent-message>',
                                      ORCHESTRATOR_ROUTER_OFF="1"))
        self.assertIs(self.state("s1")["finalized"], True)

    def test_off_switch_is_silent_too(self) -> None:
        self.assertSilent(self.report("s1", '<agent-message from="x">done</agent-message>', ORCHESTRATOR_OFF="1"))


# ---------------------------------------------------------------- agent-call: gate


class GateTest(SeamCase):
    DENY_CASES = (
        ("fable short name", agent_payload({"model": "fable", "description": "x"}), {}),
        ("fable full id", agent_payload({"model": "claude-fable-5-1"}), {}),
        ("fable upper case", agent_payload({"model": "FABLE"}), {}),
        ("fable via Task", agent_payload({"model": "fable"}, tool="Task"), {}),
        ("fable listed", agent_payload({"model": "fable"}), {"ORCHESTRATOR_MODELS": "opus,fable"}),
        ("fable in object", agent_payload({"model": {"name": "fable"}}), {}),
    )
    ALLOWED = ("opus", "sonnet", "haiku", "claude-sonnet-5", "claude-haiku-4-5-20251001",
               "claude-opus-5-5[1m]", "Sonnet")

    def test_deny(self) -> None:
        for mode, extra in (("router on", {}), ("router off", {"ORCHESTRATOR_ROUTER_OFF": "1"})):
            for label, payload, env in self.DENY_CASES:
                with self.subTest(f"{label} ({mode})"):
                    self.assertDenied(self.hook("agent-call", payload, **env, **extra))

    def test_deny_message_names_allowed_models(self) -> None:
        result = self.hook("agent-call", agent_payload({"model": "fable", "description": "x"}))
        self.assertDenied(result)
        self.assertIn("Re-issue the call with one of: opus, sonnet, haiku.", result.stderr)
        self.assertIn("Task was: x", result.stderr)

    def test_allowed_models_pass_silently(self) -> None:
        # Router on with no router answer keeps the given model: no output either.
        for mode, extra in (("router off", {"ORCHESTRATOR_ROUTER_OFF": "1"}),
                            ("router down", {"ORCHESTRATOR_ROUTER_STUB": "down"})):
            for model in self.ALLOWED:
                label = {"claude-sonnet-5": "full id", "claude-haiku-4-5-20251001": "full id dated",
                         "claude-opus-5-5[1m]": "full id 1m", "Sonnet": "mixed case"}.get(model, model)
                with self.subTest(f"{label} ({mode})"):
                    self.assertSilent(self.hook("agent-call", agent_payload({"model": model}), **extra))

    def test_warnings(self) -> None:
        cases = (
            ("typo", {"model": "sonet"}, {}, gate_unknown("sonet")),
            ("other vendor", {"model": "gpt-5"}, {}, gate_unknown("gpt-5")),
            ("prefix trick", {"model": "claude-sonnetx"}, {}, gate_unknown("claude-sonnetx")),
            ("no model", {"description": "x"}, {}, GATE_NO_MODEL),
            ("fork", {"subagent_type": "fork", "model": "opus"}, {}, GATE_FORK),
            ("custom list", {"model": "sonnet"}, {"ORCHESTRATOR_MODELS": "opus"}, gate_unknown("sonnet", "opus")),
        )
        for label, tool_input, env, message in cases:
            with self.subTest(label):
                result = self.hook("agent-call", agent_payload(tool_input), ORCHESTRATOR_ROUTER_OFF="1", **env)
                self.assertOk(result)
                out = parse_json(result.stdout)
                self.assertEqual(out["systemMessage"], message)
                self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PreToolUse")
                self.assertEqual(out["hookSpecificOutput"]["additionalContext"], message)
                self.assertNotIn("permissionDecision", out["hookSpecificOutput"])
                self.assertNotIn("updatedInput", out["hookSpecificOutput"])

    def test_pass_untouched(self) -> None:
        cases = (
            ("other tool", {"tool_name": "Bash", "tool_input": {"model": "fable"}}),
            ("empty payload", ""),
            ("malformed payload", "{not json"),
            ("non-object payload", "42"),
        )
        for mode, extra in (("router on", {}), ("router off", {"ORCHESTRATOR_ROUTER_OFF": "1"})):
            for label, payload in cases:
                with self.subTest(f"{label} ({mode})"):
                    self.assertSilent(self.hook("agent-call", payload, **extra))

    def test_off_switch(self) -> None:
        self.assertSilent(self.hook("agent-call", agent_payload({"model": "fable"}), ORCHESTRATOR_OFF="1"))

    def test_debug_capture(self) -> None:
        debug = self.tmp / "debug.jsonl"
        result = self.hook("agent-call", agent_payload({"model": "opus"}),
                           ORCHESTRATOR_DEBUG=str(debug), ORCHESTRATOR_ROUTER_OFF="1")
        self.assertSilent(result)
        self.assertTrue(debug.exists(), "payload not written")
        self.assertIn('"model":"opus"', debug.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- agent-call: model pick


class ModelPickTest(SeamCase):
    INPUT = {"subagent_type": "general-purpose", "description": "count files",
             "prompt": "count the files in src"}

    def call(self, tool_input: Any, stub: str = STUB_TIER_OPUS, session: str = "t1",
             tool: str = "Agent", agent_id: Optional[str] = None, **env: str) -> Result:
        return self.hook("agent-call", tool_payload(session, tool, tool_input, agent_id),
                         ORCHESTRATOR_ROUTER_STUB=stub, **env)

    def last_agent_record(self) -> Dict[str, Any]:
        records = self.log("agent_call")
        self.assertTrue(records, "no agent_call record")
        return records[-1]

    def test_no_model_router_sets_it(self) -> None:
        self.start_turn("t1", STUB_DELEGATE)
        result = self.call(dict(self.INPUT))
        self.assertOk(result)
        out = parse_json(result.stdout)
        hso = out["hookSpecificOutput"]
        with self.subTest("fill no model: updatedInput"):
            self.assertEqual(hso["updatedInput"], dict(self.INPUT, model="opus"))
        with self.subTest("fill no model: event name"):
            self.assertEqual(hso["hookEventName"], "PreToolUse")
        with self.subTest("fill no model: no decision"):
            self.assertNotIn("permissionDecision", hso)
        with self.subTest("set message is systemMessage only"):
            self.assertIn('set model "opus"', out["systemMessage"])
            self.assertEqual(out["systemMessage"], pick_set("opus"))
            self.assertNotIn("additionalContext", hso)
        rec = self.last_agent_record()
        with self.subTest("fill no model: log"):
            self.assertEqual(
                (rec["action"], rec["model_given"], rec["model_set"], rec["server"], rec["turn"],
                 rec["tool"], rec["verdict"]["tier"], rec["subagent_type"], rec["description"],
                 rec["user_named_subagent"]),
                ("set", None, "opus", "stub", 1, "Agent", "opus", "general-purpose", "count files", False),
            )
        with self.subTest("fill no model: log prompt"):
            self.assertEqual(rec["prompt"], "count the files in src")
        with self.subTest("fill no model: latency is a whole number"):
            self.assertIsInstance(rec["latency_ms"], int)
        with self.subTest("fill no model: ts"):
            self.assertRegex(rec["ts"], TS_PATTERN)
        with self.subTest("fill no model: n_agent"):
            self.assertEqual(self.state("t1")["n_agent"], 1)

    def test_null_model_router_sets_it(self) -> None:
        self.start_turn("t1", STUB_DELEGATE)
        result = self.call({"description": "x", "model": None}, stub=STUB_TIER_HAIKU, tool="Task")
        self.assertOk(result)
        out = parse_json(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["updatedInput"], {"description": "x", "model": "haiku"})
        rec = self.last_agent_record()
        self.assertEqual((rec["action"], rec["model_given"], rec["model_set"], rec["tool"]),
                         ("set", None, "haiku", "Task"))

    def test_given_model_replaced(self) -> None:
        self.start_turn("t1", STUB_DELEGATE)
        tool_input = {"description": "x", "prompt": "y", "model": "haiku"}
        result = self.call(dict(tool_input))
        self.assertOk(result)
        out = parse_json(result.stdout)
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["updatedInput"], dict(tool_input, model="opus"))
        self.assertIn('replacing "haiku"', hso["additionalContext"])
        self.assertEqual(hso["additionalContext"], pick_replace("opus", "haiku"))
        self.assertEqual(out["systemMessage"], pick_replace("opus", "haiku"))
        self.assertNotIn("permissionDecision", hso)
        rec = self.last_agent_record()
        self.assertEqual((rec["action"], rec["model_given"], rec["model_set"], rec["verdict"]["tier"]),
                         ("set", "haiku", "opus", "opus"))

    def test_fill_explicit_model_same_as_verdict(self) -> None:
        # Ported from "fill explicit model": now the router decides. Same model: systemMessage only.
        self.start_turn("t1", STUB_DELEGATE)
        tool_input = {"description": "x", "prompt": "y", "model": "opus"}
        result = self.call(dict(tool_input))
        self.assertOk(result)
        out = parse_json(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["updatedInput"], tool_input)
        self.assertEqual(out["systemMessage"], pick_set("opus"))
        self.assertNotIn("additionalContext", out["hookSpecificOutput"])
        rec = self.last_agent_record()
        self.assertEqual((rec["action"], rec["model_given"], rec["model_set"]), ("set", "opus", "opus"))

    def test_fill_explicit_model_different_from_verdict(self) -> None:
        # The bash case: model opus given, tier haiku answered. The contract now replaces it.
        self.start_turn("t1", STUB_DELEGATE)
        result = self.call({"description": "x", "prompt": "y", "model": "opus"}, stub=STUB_TIER_HAIKU)
        self.assertOk(result)
        out = parse_json(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["updatedInput"]["model"], "haiku")
        self.assertEqual(out["hookSpecificOutput"]["additionalContext"], pick_replace("haiku", "opus"))
        rec = self.last_agent_record()
        self.assertEqual((rec["action"], rec["model_given"], rec["model_set"], rec["verdict"]["tier"]),
                         ("set", "opus", "haiku", "haiku"))

    def test_unknown_model_replaced_drops_the_gate_warning(self) -> None:
        # The contract skips the unknown-model warning when the router set a model on the call.
        self.start_turn("t1", STUB_DELEGATE)
        result = self.call({"description": "x", "model": "sonet"})
        self.assertOk(result)
        out = parse_json(result.stdout)
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["updatedInput"]["model"], "opus")
        for field in (out["systemMessage"], hso["additionalContext"]):
            self.assertEqual(field, pick_replace("opus", "sonet"))
            self.assertNotIn("allowed list", field)

    def test_word_inside_another_word_does_not_name_the_subagent(self) -> None:
        self.start_turn("t1", STUB_DELEGATE, prompt="give an explanation of the failing test")
        result = self.call({"subagent_type": "Plan", "model": "sonnet", "description": "x"})
        self.assertOk(result)
        self.assertEqual(parse_json(result.stdout)["hookSpecificOutput"]["updatedInput"]["model"], "opus")
        rec = self.last_agent_record()
        self.assertEqual((rec["action"], rec["user_named_subagent"]), ("set", False))

    def test_user_named_subagent_keeps_model(self) -> None:
        self.start_turn("t1", STUB_DELEGATE, prompt="use the verifying-worker for this")
        result = self.call({"subagent_type": "orchestrator:verifying-worker", "description": "x",
                            "prompt": "y", "model": "sonnet"})
        self.assertSilent(result)
        rec = self.last_agent_record()
        self.assertEqual(
            (rec["action"], rec["user_named_subagent"], rec["model_given"], rec["model_set"],
             rec["server"], rec["verdict"]["tier"]),
            ("kept", True, "sonnet", "sonnet", "stub", "opus"),
        )

    def test_user_named_subagent_no_model(self) -> None:
        self.start_turn("t1", STUB_DELEGATE, prompt="use the verifying-worker for this")
        result = self.call({"subagent_type": "orchestrator:verifying-worker", "description": "x"})
        self.assertOk(result)
        out = parse_json(result.stdout)
        self.assertEqual(out["systemMessage"], GATE_NO_MODEL)
        self.assertEqual(out["hookSpecificOutput"]["additionalContext"], GATE_NO_MODEL)
        self.assertNotIn("updatedInput", out["hookSpecificOutput"])
        rec = self.last_agent_record()
        self.assertEqual((rec["action"], rec["user_named_subagent"], rec["model_set"]), ("kept", True, None))

    def test_user_named_subagent_variants(self) -> None:
        cases = (
            ("full type in prompt", "please run orchestrator:verifying-worker on it", True),
            ("mixed case in prompt", "Use the Verifying-Worker for this", True),
            ("other subagent named", "use the general-purpose agent", False),
        )
        for i, (label, prompt, named) in enumerate(cases):
            with self.subTest(label):
                session = f"u{i}"
                self.start_turn(session, STUB_DELEGATE, prompt=prompt)
                result = self.call({"subagent_type": "orchestrator:verifying-worker", "model": "sonnet"},
                                   session=session)
                self.assertOk(result)
                rec = self.last_agent_record()
                self.assertEqual(rec["user_named_subagent"], named)
                if named:
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(rec["action"], "kept")
                else:
                    self.assertEqual(parse_json(result.stdout)["hookSpecificOutput"]["updatedInput"]["model"], "opus")
                    self.assertEqual(rec["action"], "set")

    def test_empty_subagent_type_is_not_named(self) -> None:
        self.start_turn("t1", STUB_DELEGATE, prompt="anything")
        self.call({"subagent_type": "", "model": "sonnet"})
        self.assertIs(self.last_agent_record()["user_named_subagent"], False)

    def test_fork(self) -> None:
        self.start_turn("t1", STUB_DELEGATE)
        for label, tool_input, model_set in (
            ("fill fork", {"subagent_type": "fork", "description": "x", "prompt": "y"}, None),
            ("fill fork with model", {"subagent_type": "fork", "model": "opus"}, "opus"),
        ):
            with self.subTest(label):
                result = self.call(tool_input)
                self.assertOk(result)
                out = parse_json(result.stdout)
                self.assertEqual(out["systemMessage"], GATE_FORK)
                self.assertNotIn("updatedInput", out["hookSpecificOutput"])
                rec = self.last_agent_record()
                self.assertEqual((rec["action"], rec["model_set"], rec["server"]), ("fork", model_set, "none"))

    def test_down_with_model(self) -> None:
        self.start_turn("t1", STUB_DELEGATE)
        result = self.call({"description": "x", "model": "sonnet"}, stub="down")
        self.assertSilent(result)
        rec = self.last_agent_record()
        self.assertEqual((rec["action"], rec["model_given"], rec["model_set"], rec["server"]),
                         ("kept", "sonnet", "sonnet", "down"))

    def test_down_without_model(self) -> None:
        self.start_turn("t1", STUB_DELEGATE)
        result = self.call({"description": "x"}, stub="down")
        self.assertOk(result)
        out = parse_json(result.stdout)
        self.assertEqual(out["systemMessage"], GATE_NO_MODEL)
        self.assertEqual(out["hookSpecificOutput"]["additionalContext"], GATE_NO_MODEL)
        self.assertNotIn("updatedInput", out["hookSpecificOutput"])
        rec = self.last_agent_record()
        v = rec["verdict"]
        self.assertEqual((rec["action"], rec["model_set"], rec["server"], v["tier"], v["tier_probs"]),
                         ("none", None, "down", "none", {}))
        self.assertEqual(v["tier_conf"], 0)

    def test_no_tier_in_answer(self) -> None:
        self.start_turn("t1", STUB_DELEGATE)
        result = self.call({"description": "x"}, stub='{"tier":"none"}')
        self.assertOk(result)
        self.assertNotIn("updatedInput", parse_json(result.stdout)["hookSpecificOutput"])
        self.assertEqual(self.last_agent_record()["action"], "none")

    def test_fable_still_denied(self) -> None:
        self.start_turn("t1", STUB_DELEGATE)
        result = self.call({"description": "x", "model": "fable"})
        self.assertDenied(result)
        # Inferred from "denied before the router looks at it": no agent_call record.
        self.assertEqual(self.log("agent_call"), [])

    def test_worker_payload(self) -> None:
        self.start_turn("t1", STUB_DELEGATE)
        before = len(self.log())
        result = self.call({"description": "x"}, agent_id="agent-3")
        self.assertOk(result)
        # The gate still runs: no model and no pick, so the missing-model warning stands.
        out = parse_json(result.stdout)
        self.assertEqual(out["systemMessage"], GATE_NO_MODEL)
        self.assertNotIn("updatedInput", out["hookSpecificOutput"])
        self.assertEqual(len(self.log()), before, "worker call logged")
        self.assertEqual(self.state("t1")["n_agent"], 0)
        with self.subTest("worker payload with fable is denied"):
            self.assertDenied(self.call({"model": "fable"}, agent_id="agent-3"))

    def test_ignored_calls(self) -> None:
        self.start_turn("t1", STUB_DELEGATE)
        before = len(self.log())
        with self.subTest("fill other tool"):
            self.assertSilent(self.call({"command": "ls"}, tool="Bash"))
        with self.subTest("fill off switch"):
            self.assertSilent(self.call({"description": "x"}, ORCHESTRATOR_OFF="1"))
        with self.subTest("fill router off"):
            result = self.call({"description": "x"}, ORCHESTRATOR_ROUTER_OFF="1")
            self.assertOk(result)
            out = parse_json(result.stdout)
            self.assertEqual(out["systemMessage"], GATE_NO_MODEL)
            self.assertNotIn("updatedInput", out["hookSpecificOutput"])
        with self.subTest("fill ignored calls: no log lines"):
            self.assertEqual(len(self.log()), before)
        with self.subTest("fill ignored calls: n_agent unchanged"):
            self.assertEqual(self.state("t1")["n_agent"], 0)

    def test_n_agent_counts_main_thread_calls(self) -> None:
        self.start_turn("t1", STUB_DELEGATE)
        calls = (
            ({"description": "x"}, STUB_TIER_OPUS),
            ({"description": "x", "model": None}, STUB_TIER_HAIKU),
            ({"description": "x", "model": "opus"}, STUB_TIER_HAIKU),
            ({"subagent_type": "fork"}, STUB_TIER_HAIKU),
            ({"subagent_type": "fork", "model": "opus"}, STUB_TIER_HAIKU),
            ({"description": "x"}, "down"),
        )
        for i, (tool_input, stub) in enumerate(calls, start=1):
            self.call(tool_input, stub=stub)
            self.assertEqual(self.state("t1")["n_agent"], i)
        self.assertEqual(len(self.log("agent_call")), 6)

    def test_without_state(self) -> None:
        result = self.call({"description": "x"}, session="t9")
        self.assertOk(result)
        out = parse_json(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["updatedInput"]["model"], "opus")
        rec = self.log("agent_call")[0]
        self.assertEqual(rec["turn"], 0)
        self.assertIs(rec["user_named_subagent"], False)
        self.assertIsNone(self.state("t9"), "state created by agent-call")

    def test_log_off(self) -> None:
        self.start_turn("t1", STUB_DELEGATE, ORCHESTRATOR_LOG_OFF="1")
        result = self.call({"description": "x"}, ORCHESTRATOR_LOG_OFF="1")
        self.assertOk(result)
        self.assertEqual(parse_json(result.stdout)["hookSpecificOutput"]["updatedInput"]["model"], "opus")
        self.assertFalse((self.data / "router-log.jsonl").exists())
        self.assertEqual(self.state("t1")["n_agent"], 1)


# ---------------------------------------------------------------- agent-call: downgrade guard


class ModelPickDowngradeGuardTest(ModelPickTest):
    def test_real_case_keeps_opus_instead_of_dropping_to_haiku(self) -> None:
        # opus 0.3317, sonnet 0.292, haiku 0.3764: too close to act on a downgrade from opus.
        self.start_turn("t1", STUB_DELEGATE)
        result = self.call({
            "description": "Spec review of notifier diff", "model": "opus",
            "prompt": "Read-only spec-conformance review. Do not change any files.",
        }, stub=STUB_TIER_CLOSE_HAIKU)
        self.assertSilent(result)
        rec = self.last_agent_record()
        self.assertEqual(
            (rec["action"], rec["model_given"], rec["model_set"], rec["reason"], rec["verdict"]["tier"]),
            ("kept", "opus", "opus", "downgrade_blocked", "haiku"),
        )
        self.assertEqual(rec["tier_margin"], 0.0447)

    def test_sibling_case_keeps_opus(self) -> None:
        # The sibling call: opus 0.5344 is the clear top pick, agreeing with Claude's own choice.
        stub = json.dumps({"tier": "opus", "tier_conf": 0.5344,
                           "tier_probs": {"opus": 0.5344, "sonnet": 0.31, "haiku": 0.1556}})
        self.start_turn("t1", STUB_DELEGATE)
        result = self.call({"description": "Standards review of notifier diff", "model": "opus"}, stub=stub)
        self.assertOk(result)
        out = parse_json(result.stdout)
        self.assertEqual(out["systemMessage"], pick_set("opus"))
        rec = self.last_agent_record()
        self.assertEqual((rec["action"], rec["reason"]), ("set", "no_change"))

    def test_downgrade_applies_with_enough_margin(self) -> None:
        self.start_turn("t1", STUB_DELEGATE)
        result = self.call({"description": "x", "model": "opus"}, stub=STUB_TIER_HAIKU)
        self.assertOk(result)
        out = parse_json(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["updatedInput"]["model"], "haiku")
        rec = self.last_agent_record()
        self.assertEqual((rec["action"], rec["reason"], rec["tier_margin"]), ("set", "downgrade", 0.65))

    def test_margin_setting_widens_or_disables_the_guard(self) -> None:
        self.start_turn("t1", STUB_DELEGATE)
        blocked = self.call({"description": "x", "model": "opus"}, stub=STUB_TIER_CLOSE_HAIKU,
                            ORCHESTRATOR_TIER_MARGIN="0.5")
        self.assertSilent(blocked)
        self.assertEqual(self.last_agent_record()["reason"], "downgrade_blocked")
        allowed = self.call({"description": "x", "model": "opus"}, stub=STUB_TIER_CLOSE_HAIKU,
                            ORCHESTRATOR_TIER_MARGIN="0")
        self.assertEqual(parse_json(allowed.stdout)["hookSpecificOutput"]["updatedInput"]["model"], "haiku")
        self.assertEqual(self.last_agent_record()["reason"], "downgrade")

    def test_upgrade_reason_is_free(self) -> None:
        self.start_turn("t1", STUB_DELEGATE)
        result = self.call({"description": "x", "model": "haiku"}, stub=STUB_TIER_OPUS)
        self.assertOk(result)
        self.assertEqual(parse_json(result.stdout)["hookSpecificOutput"]["updatedInput"]["model"], "opus")
        self.assertEqual(self.last_agent_record()["reason"], "upgrade")

    def test_judgement_floor_raises_haiku_and_tells_claude(self) -> None:
        self.start_turn("t1", STUB_DELEGATE)
        result = self.call({"description": "security audit of the diff"}, stub=STUB_TIER_HAIKU)
        self.assertOk(result)
        out = parse_json(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["updatedInput"]["model"], "sonnet")
        self.assertEqual(out["systemMessage"], pick_set("sonnet") + " " + FLOOR_NOTE)
        self.assertEqual(out["hookSpecificOutput"]["additionalContext"], out["systemMessage"])
        rec = self.last_agent_record()
        self.assertEqual((rec["action"], rec["model_set"], rec["reason"]), ("set", "sonnet", "judgement_floor"))

    def test_router_down_and_fork_reasons_are_untouched(self) -> None:
        self.start_turn("t1", STUB_DELEGATE)
        self.call({"description": "x", "model": "opus"}, stub="down")
        self.assertEqual(self.last_agent_record()["reason"], "router_down")
        self.call({"subagent_type": "fork", "model": "opus"}, stub=STUB_TIER_CLOSE_HAIKU)
        self.assertEqual(self.last_agent_record()["reason"], "fork")

    def test_user_named_subagent_reason_is_untouched(self) -> None:
        self.start_turn("t1", STUB_DELEGATE, prompt="use the verifying-worker for this")
        self.call({"subagent_type": "orchestrator:verifying-worker", "description": "x", "model": "sonnet"},
                  stub=STUB_TIER_CLOSE_HAIKU)
        self.assertEqual(self.last_agent_record()["reason"], "user_named_subagent")


# ---------------------------------------------------------------- tool-call


EXPLORATORY_BASH = (
    "cat README.md", "head -n 5 x", "tail -f log", "sed -n 1,5p x", "grep -r foo .", "rg foo",
    "find . -name x", "ls -la", "wc -l x", "git log --oneline", "git diff", "git show HEAD",
    "git status", "git blame x", "cd /tmp && ls", "cd /tmp; git status", "cd x && rg foo",
    "cat a | wc -l", "  cat x",
)
ACTION_BASH = (
    "echo hi", "npm test", "git commit -m x", "git push", "sed -i s/a/b/ x", "echo hi | grep x",
    "cd /tmp && npm test", "catalog", "lsof", "python x.py", "mkdir x && ls", "",
)


class ToolCallTest(SeamCase):
    def tool(self, payload: Dict[str, Any], **env: str) -> Result:
        return self.hook("tool-call", payload, **env)

    def counts(self, session: str) -> tuple:
        st = self.state(session)
        return (st["n_tool"], st["n_exploratory"])

    def test_delegate_threshold_with_cat(self) -> None:
        self.start_turn("c1", STUB_DELEGATE)
        self.assertSilent(self.tool(bash_payload("c1", "cat x")))
        self.assertSilent(self.tool(bash_payload("c1", "cat x")))
        result = self.tool(bash_payload("c1", "cat x"))
        self.assertOk(result)
        out = parse_json(result.stdout)
        msg = exploration_msg(3, 2, "delegate")
        self.assertIn("3 exploratory commands this turn, threshold 2 (verdict delegate)",
                      out["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(out["hookSpecificOutput"]["additionalContext"], msg)
        self.assertEqual(out["systemMessage"], msg)
        self.assertSilent(self.tool(bash_payload("c1", "cat x")))
        self.assertEqual(self.counts("c1"), (4, 4))

    def test_counter_sequence(self) -> None:
        """The sequence from router.test.sh, in order."""
        self.start_turn("c1", STUB_DELEGATE)
        with self.subTest("counter worker payload"):
            self.assertSilent(self.tool(tool_payload("c1", "Read", {"file_path": "/x"}, "agent-7")))
            self.assertEqual(self.state("c1")["n_tool"], 0)
        with self.subTest("counter no state"):
            self.assertSilent(self.tool(read_payload("nosuch")))
            self.assertIsNone(self.state("nosuch"))
        with self.subTest("counter off switch"):
            self.assertSilent(self.tool(read_payload("c1"), ORCHESTRATOR_OFF="1"))
        with self.subTest("counter router off"):
            self.assertSilent(self.tool(read_payload("c1"), ORCHESTRATOR_ROUTER_OFF="1"))
            self.assertEqual(self.state("c1")["n_tool"], 0)

        with self.subTest("counter read"):
            self.assertSilent(self.tool(read_payload("c1")))
            self.assertEqual(self.counts("c1"), (1, 1))
        with self.subTest("counter actions: n_tool grows, n_exploratory does not"):
            for cmd in ("echo hi", "npm test", "git commit -m x"):
                self.assertSilent(self.tool(bash_payload("c1", cmd)))
            self.assertEqual(self.counts("c1"), (4, 1))
        with self.subTest("counter pipe at threshold"):
            self.assertSilent(self.tool(bash_payload("c1", "cat a | wc -l")))
            self.assertEqual(self.state("c1")["n_exploratory"], 2)

        result = self.tool(bash_payload("c1", "git diff"))
        msg = exploration_msg(3, 2, "delegate")
        with self.subTest("counter warns past threshold"):
            self.assertOk(result)
            out = parse_json(result.stdout)
            self.assertEqual(out["hookSpecificOutput"]["additionalContext"], msg)
            self.assertEqual(out["systemMessage"], msg)
            self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PreToolUse")
            self.assertNotIn("permissionDecision", out["hookSpecificOutput"])
            self.assertIs(self.state("c1")["warned"], True)
        with self.subTest("counter warns once"):
            self.assertSilent(self.tool(bash_payload("c1", "cd x && rg foo")))
        with self.subTest("counter cd prefix counts"):
            self.assertEqual(self.counts("c1"), (7, 4))
        with self.subTest("counter warning log"):
            warnings = self.log("exploration_warning")
            self.assertEqual(
                [(w["turn"], w["n_exploratory"], w["threshold"], w["tool"], w["blocked"]) for w in warnings],
                [(1, 3, 2, "Bash", False)],
            )
            self.assertRegex(warnings[0]["ts"], TS_PATTERN)
            self.assertEqual(warnings[0]["session_id"], "c1")

        # The next prompt starts a clean turn with a fresh warning budget.
        self.start_turn("c1", STUB_DELEGATE)
        with self.subTest("counter new turn resets"):
            st = self.state("c1")
            self.assertEqual((st["turn"], st["n_tool"], st["n_exploratory"], st["warned"]), (2, 0, 0, False))
        with self.subTest("counter new turn outcome"):
            o = self.log("prompt_outcome")[0]
            self.assertEqual((o["n_exploratory"], o["n_tool"], o["warned"], o["source"]), (4, 7, True, "next_prompt"))

    def test_classification(self) -> None:
        cases: List[tuple] = []
        cases += [(f"bash '{cmd}'", bash_payload("e1", cmd), 1) for cmd in EXPLORATORY_BASH]
        cases += [(f"bash '{cmd}'", bash_payload("e1", cmd), 0) for cmd in ACTION_BASH]
        cases += [(t, tool_payload("e1", t, {}), 1) for t in ("Read", "Grep", "Glob", "WebFetch", "WebSearch")]
        cases += [("Edit", tool_payload("e1", "Edit", {}), 0)]
        for label, payload, want in cases:
            with self.subTest(f"counter classifies {label}"):
                self.start_turn("e1", STUB_SELF)
                self.assertSilent(self.tool(payload))
                self.assertEqual(self.counts("e1"), (1, want))

    def test_self_warns_at_six(self) -> None:
        self.start_turn("s1", STUB_SELF)
        for i in range(1, 6):
            with self.subTest(f"counter self call {i}"):
                self.assertSilent(self.tool(read_payload("s1")))
        result = self.tool(read_payload("s1"))
        self.assertOk(result)
        self.assertIn("threshold 5 (verdict self)", parse_json(result.stdout)["systemMessage"])

    def test_down_warns_at_four(self) -> None:
        self.start_turn("s1", "down")
        for i in range(1, 4):
            with self.subTest(f"counter none call {i}"):
                self.assertSilent(self.tool(read_payload("s1")))
        result = self.tool(read_payload("s1"))
        self.assertOk(result)
        self.assertIn("threshold 3 (verdict none)", parse_json(result.stdout)["systemMessage"])

    def test_override_at_prompt_time(self) -> None:
        self.start_turn("s1", STUB_DELEGATE, ORCHESTRATOR_THRESHOLD_DELEGATE="1")
        self.assertSilent(self.tool(read_payload("s1")))
        result = self.tool(read_payload("s1"))
        self.assertOk(result)
        self.assertIn("2 exploratory commands this turn, threshold 1", parse_json(result.stdout)["systemMessage"])

    def test_block_mode(self) -> None:
        self.start_turn("s1", STUB_DELEGATE)
        block = {"ORCHESTRATOR_EXPLORATION_BLOCK": "1"}
        self.assertSilent(self.tool(read_payload("s1"), **block))
        self.assertSilent(self.tool(read_payload("s1"), **block))
        result = self.tool(read_payload("s1"), **block)
        self.assertOk(result)
        hso = parse_json(result.stdout)["hookSpecificOutput"]
        with self.subTest("counter block: deny"):
            self.assertEqual(hso["permissionDecision"], "deny")
        with self.subTest("counter block: reason"):
            self.assertEqual(hso["permissionDecisionReason"], exploration_msg(3, 2, "delegate"))
        with self.subTest("counter block: no additionalContext"):
            self.assertNotIn("additionalContext", hso)
        with self.subTest("counter block: log blocked"):
            self.assertEqual([w["blocked"] for w in self.log("exploration_warning")], [True])

    def test_log_off(self) -> None:
        self.start_turn("s1", STUB_DELEGATE, ORCHESTRATOR_LOG_OFF="1")
        result = None
        for _ in range(3):
            result = self.tool(read_payload("s1"), ORCHESTRATOR_LOG_OFF="1")
        self.assertIn("additionalContext", result.stdout, "counter log off: no warning")
        self.assertFalse((self.data / "router-log.jsonl").exists(), "log file written")
        self.assertEqual(self.counts("s1"), (3, 3))

    def test_broken_state(self) -> None:
        (self.data / "state").mkdir(parents=True)
        (self.data / "state" / "b1.json").write_text("not json", encoding="utf-8")
        self.assertSilent(self.tool(read_payload("b1")))

    def test_no_state(self) -> None:
        self.assertSilent(self.tool(read_payload("nosuch")))
        self.assertIsNone(self.state("nosuch"))

    def test_bad_payload(self) -> None:
        self.start_turn("s1", STUB_DELEGATE)
        for label, payload in (("empty payload", ""), ("malformed payload", "{not json")):
            with self.subTest(label):
                self.assertSilent(self.tool(payload))


# ---------------------------------------------------------------- stop


class StopTest(SeamCase):
    def test_finalize(self) -> None:
        self.start_turn("f1", STUB_DELEGATE)
        self.hook("tool-call", read_payload("f1"))
        with self.subTest("finalize"):
            self.assertSilent(self.hook("stop", {"session_id": "f1", "stop_hook_active": False}))
        with self.subTest("finalize: one outcome"):
            outcomes = self.log("prompt_outcome")
            self.assertEqual(
                [(o["source"], o["turn"], o["n_exploratory"], o["n_agent"], o["n_tool"], o["warned"])
                 for o in outcomes],
                [("stop", 1, 1, 0, 1, False)],
            )
            self.assertRegex(outcomes[0]["ts"], TS_PATTERN)
            self.assertEqual(outcomes[0]["session_id"], "f1")
        with self.subTest("finalize: finalized"):
            self.assertIs(self.state("f1")["finalized"], True)
        with self.subTest("finalize again"):
            self.assertSilent(self.hook("stop", {"session_id": "f1"}))
            self.assertEqual(len(self.log("prompt_outcome")), 1)
        self.start_turn("f1", STUB_SELF)
        with self.subTest("finalize then prompt: no second outcome"):
            self.assertEqual(len(self.log("prompt_outcome")), 1)
        with self.subTest("finalize then prompt: turn 2"):
            self.assertEqual(self.state("f1")["turn"], 2)
        with self.subTest("finalize off switch"):
            self.assertSilent(self.hook("stop", {"session_id": "f1"}, ORCHESTRATOR_ROUTER_OFF="1"))
            self.assertIs(self.state("f1")["finalized"], False)
        with self.subTest("full off switch"):
            self.assertSilent(self.hook("stop", {"session_id": "f1"}, ORCHESTRATOR_OFF="1"))
            self.assertIs(self.state("f1")["finalized"], False)

    def test_missing_state(self) -> None:
        self.assertSilent(self.hook("stop", {"session_id": "nosuch"}))
        self.assertIsNone(self.state("nosuch"))
        self.assertEqual(self.log(), [])

    def test_empty_and_malformed_payload(self) -> None:
        for label, payload in (("finalize empty payload", ""), ("malformed payload", "{not json")):
            with self.subTest(label):
                self.assertSilent(self.hook("stop", payload))


# ---------------------------------------------------------------- unknown event


class UnknownEventTest(SeamCase):
    def test_unknown_event(self) -> None:
        for event in ("nonsense", "", "SessionStart"):
            with self.subTest(event or "empty"):
                self.assertSilent(self.hook(event, {"session_id": "s1", "prompt": "x"}))

    def test_no_event_argument(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(HOOK)], input="{}", capture_output=True, text=True, timeout=10,
            env=build_env(self.data),
        )
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, "", ""))


if __name__ == "__main__":
    unittest.main()
