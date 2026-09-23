"""Pure decisions. No file system, no network, no clock."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .config import DEFAULT_PORT, env_int

READING_TOOLS = frozenset({"Read", "Grep", "Glob", "WebFetch", "WebSearch"})
ROUTES = ("delegate", "self", "skill")
# Routes the hooks act on. "unsure" is a model verdict too close to call.
EFFECTIVE_ROUTES = ROUTES + ("unsure",)
TIERS = ("opus", "sonnet", "haiku")
# Weakest to strongest, for comparing a given model against the router's tier.
TIER_RANK = {"haiku": 0, "sonnet": 1, "opus": 2}
# Prompt text that is a worker hand-back or a background task notice, not something the user typed.
WORKER_REPORT_PREFIXES = ("<agent-message", "<task-notification")
# Words that mark a worker call as judgement work, so the model pick never drops it to haiku.
JUDGEMENT_WORDS = ("review", "reviews", "reviewer", "reviewing", "audit", "auditing", "security", "design",
                    "spec", "specs", "specification", "architecture")

# One leading "cd <path> &&" or "cd <path>;" is skipped before the first word decides.
_CD_PREFIX = re.compile(r"^\s*cd\s+[^;&]+(&&|;)")
_READING_COMMAND = re.compile(
    r"^((cat|head|tail|grep|rg|find|ls|wc)|sed\s+-n|git\s+(log|diff|show|status|blame))(\s|$)"
)
_PORT = re.compile(r"^[a-zA-Z]+://[^/:]+:([0-9]+)(/.*)?$")


def is_exploratory(tool_name: str, command: str) -> bool:
    """True when the call reads rather than changes."""
    if tool_name in READING_TOOLS:
        return True
    if tool_name != "Bash":
        return False
    first_line = (command or "").split("\n", 1)[0]
    stripped = _CD_PREFIX.sub("", first_line, count=1).lstrip()
    return bool(_READING_COMMAND.match(stripped))


def threshold_for(route: str, env: Mapping[str, str]) -> int:
    """The exploration threshold that a route verdict sets."""
    if route == "delegate":
        return env_int(env, "ORCHESTRATOR_THRESHOLD_DELEGATE", 2)
    if route == "self":
        return env_int(env, "ORCHESTRATOR_THRESHOLD_SELF", 5)
    return env_int(env, "ORCHESTRATOR_THRESHOLD_DEFAULT", 3)


def model_text(model: Any) -> str:
    """The model as text: a string as is, anything else as compact JSON."""
    if model is None:
        return ""
    if isinstance(model, str):
        return model
    return json.dumps(model, separators=(",", ":"), ensure_ascii=False)


def is_fable(model: Any) -> bool:
    """True when the model mentions Fable anywhere, also inside an object."""
    return "fable" in model_text(model).lower()


def allowed_models(raw: str) -> List[str]:
    """The allowed list as lower-case entries without blanks."""
    entries = (entry.strip().lower() for entry in raw.split(","))
    return [entry for entry in entries if entry]


def allowed_list_text(raw: str) -> str:
    """The allowed list as the gate prints it, such as "opus, sonnet, haiku"."""
    return raw.lower().replace(" ", "").replace(",", ", ")


def is_known_model(model: str, allowed: List[str]) -> bool:
    """True for a short name from the list or a full ID for one."""
    lower = model.lower()
    for entry in allowed:
        if lower in (entry, "claude-" + entry) or lower.startswith("claude-" + entry + "-"):
            return True
    return False


def _number(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return 0


def _object(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _choice(value: Any, choices: tuple) -> str:
    return value if isinstance(value, str) and value in choices else "none"


@dataclass
class TierVerdict:
    tier: str = "none"
    tier_conf: float = 0
    tier_probs: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"tier": self.tier, "tier_conf": self.tier_conf, "tier_probs": self.tier_probs}


@dataclass
class RouteVerdict:
    route: str = "none"
    route_conf: float = 0
    route_probs: Dict[str, Any] = field(default_factory=dict)
    tier: str = "none"
    tier_conf: float = 0
    tier_probs: Dict[str, Any] = field(default_factory=dict)
    by_regex: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route": self.route, "route_conf": self.route_conf, "route_probs": self.route_probs,
            "tier": self.tier, "tier_conf": self.tier_conf, "tier_probs": self.tier_probs,
            "by_regex": self.by_regex,
        }


def parse_route_verdict(obj: Any) -> RouteVerdict:
    """A route answer with unknown values set to none, 0 or an empty object."""
    answer = _object(obj)
    return RouteVerdict(
        route=_choice(answer.get("route"), ROUTES),
        route_conf=_number(answer.get("route_conf")),
        route_probs=_object(answer.get("route_probs")),
        tier=_choice(answer.get("tier"), TIERS),
        tier_conf=_number(answer.get("tier_conf")),
        tier_probs=_object(answer.get("tier_probs")),
        by_regex=answer.get("by_regex") is True,
    )


def parse_tier_verdict(obj: Any) -> TierVerdict:
    """A tier answer with unknown values set to none, 0 or an empty object."""
    answer = _object(obj)
    return TierVerdict(
        tier=_choice(answer.get("tier"), TIERS),
        tier_conf=_number(answer.get("tier_conf")),
        tier_probs=_object(answer.get("tier_probs")),
    )


def route_margin(route_probs: Mapping[str, Any]) -> Optional[float]:
    """The gap between the delegate and self probabilities, or None when either is missing."""
    delegate, self_ = route_probs.get("delegate"), route_probs.get("self")
    if not all(isinstance(p, (int, float)) and not isinstance(p, bool) for p in (delegate, self_)):
        return None
    return round(abs(delegate - self_), 6)


def effective_route(verdict: RouteVerdict, limit: float) -> str:
    """The route the hooks act on: "unsure" when the model verdict is closer than the limit."""
    margin = route_margin(verdict.route_probs)
    if verdict.by_regex or margin is None or verdict.route not in ("delegate", "self"):
        return verdict.route
    return "unsure" if margin < limit else verdict.route


def is_short(text: str, limit: int) -> bool:
    """True when the text has at least one word and at most the limit. A limit of 0 is always False."""
    return 0 < len((text or "").split()) <= limit


def is_worker_report(text: str) -> bool:
    """True when the prompt text is a worker hand-back or a task notice, not a user prompt."""
    return (text or "").lstrip().startswith(WORKER_REPORT_PREFIXES)


def _names_word(text: str, word: str) -> bool:
    """True when the word appears with no letter, digit, underscore or hyphen right next to it."""
    return bool(word) and re.search(r"(?<![\w-])" + re.escape(word) + r"(?![\w-])", text) is not None


def user_named_subagent(prompt: str, subagent_type: str) -> bool:
    """True when the prompt names the subagent type, or its last segment after a colon, as a whole word."""
    wanted = (subagent_type or "").strip().lower()
    if not wanted:
        return False
    text = (prompt or "").lower()
    return _names_word(text, wanted) or _names_word(text, wanted.rsplit(":", 1)[-1])


def normalize_tier(model: Any) -> Optional[str]:
    """The model as one of the three tiers, case-insensitive, or None when it is not exactly one of them."""
    text = model_text(model).strip().lower()
    return text if text in TIERS else None


def tier_margin(tier_probs: Mapping[str, Any]) -> Optional[float]:
    """The gap between the top and second tier probabilities, or None with fewer than two numbers."""
    values = sorted(
        v for k, v in tier_probs.items()
        if k in TIERS and isinstance(v, (int, float)) and not isinstance(v, bool)
    )
    if len(values) < 2:
        return None
    return round(values[-1] - values[-2], 6)


def names_judgement_work(text: str) -> bool:
    """True when a judgement word appears in the text as a whole word. A hyphen counts as a boundary."""
    lowered = (text or "").lower()
    return any(re.search(r"\b" + word + r"\b", lowered) for word in JUDGEMENT_WORDS)


def pick_tier(given: Any, router_tier: str, tier_probs: Mapping[str, Any], guard: float,
              judgement: bool) -> Tuple[Optional[str], str, Optional[float]]:
    """The tier for a worker call, the reason for it, and the tier margin.

    Called only when the router gave a tier. None as the tier means keep the given model as is.
    An upgrade to a stronger tier is always applied. A downgrade to a weaker tier is applied only
    when the margin between the top two tier probabilities is at least the guard, unless the guard
    is 0 or less, which disables the check. The judgement floor runs last and never leaves haiku
    as the result when the task reads as judgement work.
    """
    margin = tier_margin(tier_probs)
    given_tier = normalize_tier(given)
    if given_tier is None:
        tier, reason = router_tier, "no_model_given"
    else:
        given_rank, router_rank = TIER_RANK[given_tier], TIER_RANK[router_tier]
        if router_rank > given_rank:
            tier, reason = router_tier, "upgrade"
        elif router_rank < given_rank:
            if guard <= 0 or (margin is not None and margin >= guard):
                tier, reason = router_tier, "downgrade"
            else:
                tier, reason = None, "downgrade_blocked"
        else:
            tier, reason = given_tier, "no_change"
    if tier == "haiku" and judgement:
        tier, reason = "sonnet", "judgement_floor"
    return tier, reason, margin


def port_from_url(url: str, default: int = DEFAULT_PORT) -> int:
    """The port in a URL such as http://127.0.0.1:8790, or the default."""
    match = _PORT.match(url or "")
    return int(match.group(1)) if match else default
