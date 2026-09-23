"""Pure decisions. No file system, no network, no clock."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping

from .config import DEFAULT_PORT, env_int

READING_TOOLS = frozenset({"Read", "Grep", "Glob", "WebFetch", "WebSearch"})
ROUTES = ("delegate", "self", "skill")
TIERS = ("opus", "sonnet", "haiku")

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


def port_from_url(url: str, default: int = DEFAULT_PORT) -> int:
    """The port in a URL such as http://127.0.0.1:8790, or the default."""
    match = _PORT.match(url or "")
    return int(match.group(1)) if match else default
