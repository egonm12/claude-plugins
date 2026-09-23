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


def route(route: str, probs: dict, by_regex: bool = False) -> rules.RouteVerdict:
    return rules.RouteVerdict(route=route, route_probs=probs, by_regex=by_regex)


class MarginTest(unittest.TestCase):
    def test_margin_is_the_gap_between_delegate_and_self(self) -> None:
        self.assertEqual(rules.route_margin({"delegate": 0.4721, "self": 0.5279}), 0.0558)
        self.assertEqual(rules.route_margin({"delegate": 0.66, "self": 0.34}), 0.32)

    def test_no_margin_without_both_numbers(self) -> None:
        for probs in ({}, {"delegate": 0.56}, {"delegate": 0.5, "self": "x"}, {"delegate": True, "self": 0.5}):
            self.assertIsNone(rules.route_margin(probs), probs)

    def test_close_verdict_is_unsure(self) -> None:
        self.assertEqual(rules.effective_route(route("self", {"delegate": 0.4721, "self": 0.5279}), 0.15), "unsure")
        self.assertEqual(rules.effective_route(route("delegate", {"delegate": 0.55, "self": 0.45}), 0.15), "unsure")

    def test_clear_verdict_keeps_its_route(self) -> None:
        self.assertEqual(rules.effective_route(route("delegate", {"delegate": 0.66, "self": 0.34}), 0.15), "delegate")
        self.assertEqual(rules.effective_route(route("self", {"delegate": 0.35, "self": 0.65}), 0.15), "self")

    def test_margin_on_the_limit_is_not_unsure(self) -> None:
        self.assertEqual(rules.effective_route(route("self", {"delegate": 0.25, "self": 0.75}), 0.5), "self")

    def test_regex_verdict_and_missing_probs_keep_their_route(self) -> None:
        self.assertEqual(rules.effective_route(route("skill", {"delegate": 0.5, "self": 0.5}, True), 0.15), "skill")
        self.assertEqual(rules.effective_route(route("delegate", {}), 0.15), "delegate")
        self.assertEqual(rules.effective_route(route("none", {}), 0.15), "none")


class ShortPromptTest(unittest.TestCase):
    def test_short_follow_ups(self) -> None:
        for text in ("continue", "yes do it", "go on", "  go   on \n"):
            self.assertTrue(rules.is_short(text, 3), text)

    def test_longer_or_empty_prompts(self) -> None:
        for text in ("yes, branch and open a PR", "please do it now", "", "   "):
            self.assertFalse(rules.is_short(text, 3), text)

    def test_zero_disables(self) -> None:
        self.assertFalse(rules.is_short("continue", 0))


class WorkerReportTest(unittest.TestCase):
    def test_agent_message_and_task_notification_are_worker_reports(self) -> None:
        for text in ('<agent-message from="a2c95a8d059e8622e">body</agent-message>',
                     "<task-notification>\n<task-id>1</task-id>",
                     "  \n <agent-message from=\"x\">", "\t<task-notification>"):
            self.assertTrue(rules.is_worker_report(text), text)

    def test_a_typed_prompt_is_not_a_worker_report(self) -> None:
        for text in ("why does the build fail", "", "   ", "please read <agent-message> in the log"):
            self.assertFalse(rules.is_worker_report(text), text)


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


class NormalizeTierTest(unittest.TestCase):
    def test_exact_names(self) -> None:
        for model, want in (("opus", "opus"), ("SONNET", "sonnet"), (" Haiku ", "haiku")):
            self.assertEqual(rules.normalize_tier(model), want, model)

    def test_not_a_tier_name(self) -> None:
        for model in (None, "", "claude-opus-5-5", "gpt-5", {"name": "opus"}, "fable"):
            self.assertIsNone(rules.normalize_tier(model), model)


class TierMarginTest(unittest.TestCase):
    def test_gap_between_top_two(self) -> None:
        self.assertEqual(rules.tier_margin({"opus": 0.3317, "sonnet": 0.292, "haiku": 0.3764}), 0.0447)
        self.assertEqual(rules.tier_margin({"opus": 0.6, "sonnet": 0.3, "haiku": 0.1}), 0.3)

    def test_missing_or_short(self) -> None:
        for probs in ({}, {"opus": 0.5}, {"opus": "x", "sonnet": 0.5}):
            self.assertIsNone(rules.tier_margin(probs), probs)

    def test_non_numeric_values_are_ignored(self) -> None:
        self.assertEqual(rules.tier_margin({"opus": "x", "sonnet": 0.5, "haiku": 0.2}), 0.3)

    def test_unknown_keys_are_ignored(self) -> None:
        self.assertIsNone(rules.tier_margin({"opus": 0.5, "gpt": 0.9}))


class JudgementWordsTest(unittest.TestCase):
    def test_named_words(self) -> None:
        for text in ("Spec review of notifier diff", "a security audit", "system design doc",
                      "the architecture", "code reviewer", "keeps reviewing it", "write the specs"):
            self.assertTrue(rules.names_judgement_work(text), text)

    def test_hyphen_counts_as_a_boundary(self) -> None:
        self.assertTrue(rules.names_judgement_work("Read-only spec-conformance review"))

    def test_not_judgement_work(self) -> None:
        for text in ("count the files in src", "", "reviewership", "prereview", "specialist"):
            self.assertFalse(rules.names_judgement_work(text), text)


class PickTierTest(unittest.TestCase):
    def test_no_given_model_uses_the_router_tier(self) -> None:
        tier, reason, margin = rules.pick_tier(None, "sonnet", {}, 0.15, False)
        self.assertEqual((tier, reason, margin), ("sonnet", "no_model_given", None))

    def test_a_given_model_that_does_not_normalise_counts_as_no_model(self) -> None:
        tier, reason, margin = rules.pick_tier("gpt-5", "opus", {}, 0.15, False)
        self.assertEqual((tier, reason), ("opus", "no_model_given"))

    def test_upgrade_is_free(self) -> None:
        tier, reason, margin = rules.pick_tier("haiku", "opus", {"opus": 0.34, "sonnet": 0.33, "haiku": 0.33},
                                               0.15, False)
        self.assertEqual((tier, reason), ("opus", "upgrade"))

    def test_downgrade_applies_with_enough_margin(self) -> None:
        tier, reason, margin = rules.pick_tier("opus", "haiku", {"opus": 0.1, "sonnet": 0.1, "haiku": 0.8},
                                               0.15, False)
        self.assertEqual((tier, reason, margin), ("haiku", "downgrade", 0.7))

    def test_downgrade_blocked_on_a_close_call(self) -> None:
        # The real case: opus 0.3317, sonnet 0.292, haiku 0.3764. Claude gave opus.
        tier, reason, margin = rules.pick_tier("opus", "haiku",
                                               {"opus": 0.3317, "sonnet": 0.292, "haiku": 0.3764}, 0.15, False)
        self.assertEqual((tier, reason, margin), (None, "downgrade_blocked", 0.0447))

    def test_downgrade_blocked_without_a_margin(self) -> None:
        tier, reason, margin = rules.pick_tier("opus", "haiku", {}, 0.15, False)
        self.assertEqual((tier, reason, margin), (None, "downgrade_blocked", None))

    def test_guard_zero_always_allows_the_downgrade(self) -> None:
        tier, reason, margin = rules.pick_tier("opus", "haiku", {}, 0, False)
        self.assertEqual((tier, reason), ("haiku", "downgrade"))

    def test_no_change_when_tiers_already_match(self) -> None:
        tier, reason, margin = rules.pick_tier("sonnet", "sonnet", {"opus": 0.34, "sonnet": 0.33, "haiku": 0.33},
                                               0.15, False)
        self.assertEqual((tier, reason), ("sonnet", "no_change"))

    def test_judgement_floor_raises_haiku_to_sonnet(self) -> None:
        for given, router in ((None, "haiku"), ("haiku", "haiku")):
            with self.subTest((given, router)):
                tier, reason, margin = rules.pick_tier(given, router, {}, 0.15, True)
                self.assertEqual((tier, reason), ("sonnet", "judgement_floor"))

    def test_judgement_floor_does_nothing_when_the_result_is_not_haiku(self) -> None:
        tier, reason, margin = rules.pick_tier(None, "sonnet", {}, 0.15, True)
        self.assertEqual((tier, reason), ("sonnet", "no_model_given"))

    def test_judgement_floor_does_not_undo_a_blocked_downgrade(self) -> None:
        tier, reason, margin = rules.pick_tier("opus", "haiku", {}, 0.15, True)
        self.assertEqual((tier, reason), (None, "downgrade_blocked"))


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
