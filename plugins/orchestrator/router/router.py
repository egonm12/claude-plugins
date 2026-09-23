"""Pure routing module shared by the orchestrator plugin's router service.

Turns a prompt into two decisions:
  route: delegate | self | skill   (skill by regex, the rest by laya `choice`)
  tier:  opus | sonnet | haiku     (laya `choice`)
No I/O here beyond the model call. This is the part that could lift into a hook.

Phrasing notes from the variant run (see README):
- Neutral option keys (a, b, c) with the meaning in the description beat named keys.
- A binary delegate-or-self question beats a three-way one. Slash commands are regex work.
- The English checkpoint beat the multilingual one, also on Dutch prompts.
"""
import re
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

import laya

DEFAULT_CHECKPOINT = "convaiinnovations/laya"
SLASH = re.compile(r"^\s*/[A-Za-z]")

ROUTE_QUESTION = {
    "type": "choice",
    "instructions": (
        "A user typed this request to a coding assistant. How much work does answering it take?"
    ),
    "criteria": {
        "a": (
            "Answering needs an investigation: reading or searching several files, comparing "
            "versions, tracing a failure, reviewing code, judging risks, or a multi-step implementation."
        ),
        "b": (
            "Answering is quick: a single known lookup, a small visible edit, a direct action like "
            "commit or push, a decision, a yes or no, or a short conversational reply."
        ),
    },
}
ROUTE_LABELS = {"a": "delegate", "b": "self"}

TIER_QUESTION = {
    "type": "choice",
    "instructions": (
        "This is a task for a worker agent. How much judgement does it need? "
        "Pick the smallest capability that can do it well."
    ),
    "criteria": {
        "a": (
            "Careful judgement: design, code review, security analysis, ambiguous requirements, "
            "or a high-stakes decision."
        ),
        "b": (
            "Normal skilled work: implementing a change, researching across files, debugging, "
            "or a multi-step task with clear goals."
        ),
        "c": (
            "Mechanical work with an obvious answer: grepping, listing files, renaming, counting, "
            "stripping comments, or reformatting."
        ),
    },
}
TIER_LABELS = {"a": "opus", "b": "sonnet", "c": "haiku"}


@dataclass
class Decision:
    route: str = "none"
    route_conf: float = 0.0
    tier: str = "none"
    tier_conf: float = 0.0
    route_probs: Dict[str, float] = field(default_factory=dict)
    tier_probs: Dict[str, float] = field(default_factory=dict)
    ms: float = 0.0
    by_regex: bool = False


def load_model(device: Optional[str] = None, checkpoint: str = DEFAULT_CHECKPOINT):
    return laya.load(checkpoint, device=device)


def device_of(model) -> str:
    return str(getattr(model, "device", "unknown"))


def _ask(model, text: str, questions: Dict[str, dict]) -> Dict[str, dict]:
    return model.predict(text, questions)["answers"]


def _relabel(probs: Dict[str, float], labels: Dict[str, str]) -> Dict[str, float]:
    return {labels[k]: float(v) for k, v in probs.items()}


def route_prompt(model, text: str) -> Decision:
    """Route and tier in one forward pass. Slash commands never reach the model."""
    if SLASH.match(text):
        return Decision(route="skill", route_conf=1.0, tier="none", by_regex=True)
    t0 = time.perf_counter()
    answers = _ask(model, text, {"route": ROUTE_QUESTION, "tier": TIER_QUESTION})
    ms = (time.perf_counter() - t0) * 1000
    r, t = answers["route"], answers["tier"]
    return Decision(
        route=ROUTE_LABELS[r["choice"]],
        route_conf=float(r["confidence"]),
        tier=TIER_LABELS[t["choice"]],
        tier_conf=float(t["confidence"]),
        route_probs=_relabel(r["probabilities"], ROUTE_LABELS),
        tier_probs=_relabel(t["probabilities"], TIER_LABELS),
        ms=ms,
    )


def tier_for_task(model, text: str) -> Decision:
    """Tier only, for the text of an Agent tool call."""
    t0 = time.perf_counter()
    answers = _ask(model, text, {"tier": TIER_QUESTION})
    ms = (time.perf_counter() - t0) * 1000
    t = answers["tier"]
    return Decision(
        tier=TIER_LABELS[t["choice"]],
        tier_conf=float(t["confidence"]),
        tier_probs=_relabel(t["probabilities"], TIER_LABELS),
        ms=ms,
    )
