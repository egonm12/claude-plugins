"""The model gate for worker calls.

Denies a worker that asks for Fable. This is the one hard rule. Warns when
the model is missing or unknown, and on a fork, whose model it cannot read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from . import rules
from .messages import DENY_TEXT, FORK_WARNING, MISSING_WARNING, UNKNOWN_WARNING
from .output import PREFIX
from .payload import field_text

# The kinds of warning. The handler drops the model warnings when the router set a model.
FORK = "fork"
MISSING_MODEL = "missing_model"
UNKNOWN_MODEL = "unknown_model"


@dataclass
class GateVerdict:
    deny: str = ""
    warning: str = ""
    kind: str = ""

    @property
    def about_model(self) -> bool:
        """True for the missing-model and unknown-model warnings, which a model pick makes stale."""
        return self.kind in (MISSING_MODEL, UNKNOWN_MODEL)


def check(tool_input: Dict[str, Any], models: str) -> GateVerdict:
    """The gate's decision on the original tool input."""
    model = field_text(tool_input, "model")
    allowed = rules.allowed_list_text(models)
    if rules.is_fable(tool_input.get("model")):
        task = field_text(tool_input, "description") or "<no description>"
        return GateVerdict(deny=DENY_TEXT.format(model=model, allowed=allowed, task=task))
    if field_text(tool_input, "subagent_type") == "fork":
        return GateVerdict(warning=PREFIX + FORK_WARNING, kind=FORK)
    if not model:
        return GateVerdict(warning=PREFIX + MISSING_WARNING, kind=MISSING_MODEL)
    if not rules.is_known_model(model, rules.allowed_models(models)):
        return GateVerdict(warning=PREFIX + UNKNOWN_WARNING.format(model=model, allowed=allowed), kind=UNKNOWN_MODEL)
    return GateVerdict()
