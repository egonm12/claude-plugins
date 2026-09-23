"""Unit tests for the pure decisions in rules.py."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))

from orchestrator_hooks import rules  # noqa: E402


class ExploratoryTest(unittest.TestCase):
    def test_reading_tools_always_count(self) -> None:
        for tool in ("Read", "Grep", "Glob", "WebFetch", "WebSearch"):
            self.assertTrue(rules.is_exploratory(tool, ""), tool)

    def test_other_tools_never_count(self) -> None:
        for tool in ("Edit", "Write", "Agent", "Task", "", "bash"):
            self.assertFalse(rules.is_exploratory(tool, "cat x"), tool)

    def test_reading_bash_commands_count(self) -> None:
        for command in (
            "cat x", "git diff", "cd x && rg foo", "cd x; ls", "cat a | wc -l",
            "sed -n 1p f", "head -n 5 x", "tail -f log", "grep -r foo .", "find . -name x",
            "git log --oneline", "git show HEAD", "git status", "git blame x", "  cat x",
            "cd /tmp; git status", "ls",
        ):
            self.assertTrue(rules.is_exploratory("Bash", command), command)

    def test_changing_bash_commands_do_not_count(self) -> None:
        for command in (
            "echo hi | grep x", "npm test", "git commit -m x", "sed -i s/a/b/ f", "echo hi",
            "git push", "cd /tmp && npm test", "catalog", "lsof", "python x.py",
            "mkdir x && ls", "",
        ):
            self.assertFalse(rules.is_exploratory("Bash", command), command)

    def test_only_the_first_line_decides(self) -> None:
        self.assertFalse(rules.is_exploratory("Bash", "npm test\ncat x"))
        self.assertTrue(rules.is_exploratory("Bash", "cat x\nnpm test"))


class ThresholdTest(unittest.TestCase):
    def test_defaults(self) -> None:
        self.assertEqual(rules.threshold_for("delegate", {}), 2)
        self.assertEqual(rules.threshold_for("self", {}), 5)
        self.assertEqual(rules.threshold_for("skill", {}), 3)
        self.assertEqual(rules.threshold_for("none", {}), 3)

    def test_overrides(self) -> None:
        env = {
            "ORCHESTRATOR_THRESHOLD_DELEGATE": "4",
            "ORCHESTRATOR_THRESHOLD_SELF": "7",
            "ORCHESTRATOR_THRESHOLD_DEFAULT": "1",
        }
        self.assertEqual(rules.threshold_for("delegate", env), 4)
        self.assertEqual(rules.threshold_for("self", env), 7)
        self.assertEqual(rules.threshold_for("skill", env), 1)
        self.assertEqual(rules.threshold_for("none", env), 1)

    def test_non_numeric_override_falls_back(self) -> None:
        env = {
            "ORCHESTRATOR_THRESHOLD_DELEGATE": "abc",
            "ORCHESTRATOR_THRESHOLD_SELF": "-1",
            "ORCHESTRATOR_THRESHOLD_DEFAULT": "",
        }
        self.assertEqual(rules.threshold_for("delegate", env), 2)
        self.assertEqual(rules.threshold_for("self", env), 5)
        self.assertEqual(rules.threshold_for("none", env), 3)


class FableTest(unittest.TestCase):
    def test_fable_forms(self) -> None:
        for value in ("fable", "FABLE", "claude-fable-5-1", {"name": "fable"}, ["Fable"]):
            self.assertTrue(rules.is_fable(value), value)

    def test_not_fable(self) -> None:
        for value in ("opus", "", None, {"name": "opus"}, 5):
            self.assertFalse(rules.is_fable(value), value)


class KnownModelTest(unittest.TestCase):
    allowed = ["opus", "sonnet", "haiku"]

    def test_known(self) -> None:
        for model in ("opus", "sonnet", "haiku", "claude-sonnet-5",
                      "claude-haiku-4-5-20251001", "claude-opus-5-5[1m]", "Sonnet", "CLAUDE-OPUS-5"):
            self.assertTrue(rules.is_known_model(model, self.allowed), model)

    def test_unknown(self) -> None:
        for model in ("sonet", "gpt-5", "claude-sonnetx", "claude-", ""):
            self.assertFalse(rules.is_known_model(model, self.allowed), model)

    def test_custom_list(self) -> None:
        self.assertTrue(rules.is_known_model("opus", ["opus"]))
        self.assertFalse(rules.is_known_model("sonnet", ["opus"]))

    def test_allowed_models_parsing(self) -> None:
        self.assertEqual(rules.allowed_models(" Opus, sonnet ,,haiku"), ["opus", "sonnet", "haiku"])
        self.assertEqual(rules.allowed_list_text("Opus, sonnet"), "opus, sonnet")


class VerdictTest(unittest.TestCase):
    def test_full_route_answer(self) -> None:
        verdict = rules.parse_route_verdict({
            "route": "delegate", "route_conf": 0.123, "route_probs": {"delegate": 0.56},
            "tier": "sonnet", "tier_conf": 0.2, "tier_probs": {"sonnet": 0.5},
            "latency_ms": 114.2, "by_regex": False,
        })
        self.assertEqual(verdict.to_dict(), {
            "route": "delegate", "route_conf": 0.123, "route_probs": {"delegate": 0.56},
            "tier": "sonnet", "tier_conf": 0.2, "tier_probs": {"sonnet": 0.5}, "by_regex": False,
        })

    def test_skill_answer(self) -> None:
        verdict = rules.parse_route_verdict({
            "route": "skill", "route_conf": 1.0, "route_probs": {}, "tier": "none",
            "tier_conf": 0.0, "tier_probs": {}, "by_regex": True,
        })
        self.assertEqual((verdict.route, verdict.tier, verdict.by_regex), ("skill", "none", True))

    def test_empty_object(self) -> None:
        self.assertEqual(rules.parse_route_verdict({}).to_dict(), {
            "route": "none", "route_conf": 0, "route_probs": {}, "tier": "none",
            "tier_conf": 0, "tier_probs": {}, "by_regex": False,
        })
        self.assertEqual(rules.parse_tier_verdict({}).to_dict(),
                         {"tier": "none", "tier_conf": 0, "tier_probs": {}})

    def test_junk_types(self) -> None:
        route = rules.parse_route_verdict({
            "route": "maybe", "route_conf": "high", "route_probs": [1], "tier": 3,
            "tier_conf": True, "tier_probs": "x", "by_regex": "yes",
        })
        self.assertEqual(route.to_dict(), {
            "route": "none", "route_conf": 0, "route_probs": {}, "tier": "none",
            "tier_conf": 0, "tier_probs": {}, "by_regex": False,
        })
        tier = rules.parse_tier_verdict({"tier": "gpt", "tier_conf": None, "tier_probs": 1})
        self.assertEqual(tier.to_dict(), {"tier": "none", "tier_conf": 0, "tier_probs": {}})
        for junk in (None, [], "text", 3):
            self.assertEqual(rules.parse_route_verdict(junk).route, "none")
            self.assertEqual(rules.parse_tier_verdict(junk).tier, "none")

    def test_tier_answer(self) -> None:
        tier = rules.parse_tier_verdict({"tier": "haiku", "tier_conf": 0.4, "tier_probs": {"haiku": 0.4}})
        self.assertEqual(tier.to_dict(), {"tier": "haiku", "tier_conf": 0.4, "tier_probs": {"haiku": 0.4}})


class NamedSubagentTest(unittest.TestCase):
    def test_full_type(self) -> None:
        self.assertTrue(rules.user_named_subagent(
            "please use orchestrator:verifying-worker here", "orchestrator:verifying-worker"))

    def test_last_segment(self) -> None:
        self.assertTrue(rules.user_named_subagent(
            "use the verifying-worker", "orchestrator:verifying-worker"))

    def test_case_differences(self) -> None:
        self.assertTrue(rules.user_named_subagent("Use The Explore agent", "explore"))
        self.assertTrue(rules.user_named_subagent("use the explore agent", "Explore"))

    def test_empty_type(self) -> None:
        self.assertFalse(rules.user_named_subagent("use anything", ""))
        self.assertFalse(rules.user_named_subagent("use anything", "  "))

    def test_not_named(self) -> None:
        self.assertFalse(rules.user_named_subagent("why does the build fail", "general-purpose"))
        self.assertFalse(rules.user_named_subagent("", "general-purpose"))

    def test_word_inside_another_word_is_not_named(self) -> None:
        self.assertFalse(rules.user_named_subagent("give me an explanation", "Plan"))

    def test_whole_word_is_named(self) -> None:
        self.assertTrue(rules.user_named_subagent("make a plan first", "Plan"))

    def test_last_segment_in_any_case(self) -> None:
        self.assertTrue(rules.user_named_subagent("use the verifying-worker", "orchestrator:verifying-worker"))
        self.assertTrue(rules.user_named_subagent("Use the Verifying-Worker", "orchestrator:verifying-worker"))

    def test_trailing_letter_makes_another_word(self) -> None:
        self.assertFalse(rules.user_named_subagent("use the verifying-workers", "orchestrator:verifying-worker"))

    def test_neighbouring_digit_underscore_or_hyphen_blocks_the_match(self) -> None:
        for prompt in ("plan2 it", "my_plan", "pre-plan it", "plan-b"):
            self.assertFalse(rules.user_named_subagent(prompt, "Plan"), prompt)

    def test_punctuation_around_the_word_is_a_boundary(self) -> None:
        for prompt in ("plan.", "(plan)", "\"plan\"", "plan, then act"):
            self.assertTrue(rules.user_named_subagent(prompt, "Plan"), prompt)

    def test_empty_type_is_false(self) -> None:
        self.assertFalse(rules.user_named_subagent("make a plan first", ""))


class PortTest(unittest.TestCase):
    def test_with_port(self) -> None:
        self.assertEqual(rules.port_from_url("http://127.0.0.1:1"), 1)
        self.assertEqual(rules.port_from_url("http://localhost:9000/api"), 9000)

    def test_without_port(self) -> None:
        self.assertEqual(rules.port_from_url("http://127.0.0.1"), 8790)
        self.assertEqual(rules.port_from_url("http://127.0.0.1/x", default=1234), 1234)

    def test_junk(self) -> None:
        for url in ("", "not a url", "http://host:abc", "127.0.0.1:80"):
            self.assertEqual(rules.port_from_url(url), 8790, url)


if __name__ == "__main__":
    unittest.main()
