"""Every text the hooks show, in one place.

Texts copied from the bash scripts stay word for word, because tests and
users match on them.
"""

from __future__ import annotations

PROTOCOL_FALLBACK = ("orchestrator is active. Delegate reading and searching to workers, state a model on every "
                     "Agent call, never use fable, and require verified evidence in every worker report.")
REMINDER_FALLBACK = ("Before you start, decide whether this needs workers. "
                     "Delegate research, keep actions and decisions.")
REMINDER_MARK = "> Before you start:"
FORK_WARNING = ("This is a fork. It ignores any model override and runs on the session model, which this hook "
                "cannot read. It also inherits your full conversation. Confirm the session is not on Fable, and "
                "say in your next message why a fork was needed instead of a fresh worker.")
MISSING_WARNING = ("This Agent call sets no model. The effective model comes from the agent definition or the "
                   "configured default, which this hook cannot read. Set model explicitly so the choice is "
                   "stated, or confirm the agent definition pins a non-Fable model.")
UNKNOWN_WARNING = ('This Agent call sets model "{model}", which is not in the allowed list ({allowed}). '
                   "Check it for a typo. If you meant it, say why in your next message.")
DENY_TEXT = ('Blocked by orchestrator: this Agent call asks for Fable (model "{model}").\n\n'
             "Fable workers are not allowed. Re-issue the call with one of: {allowed}.\n"
             "The orchestrator protocol says which model fits which work.\n\n"
             "Task was: {task}\n")
HINT_TEXT = ("orchestrator router: this prompt looks like an investigation (delegate, confidence {conf:.2f}, "
             "tier {tier}). Delegate the research to a worker before running commands.")
COUNTER_TEXT = ("orchestrator router: {count} exploratory commands this turn, threshold {threshold} "
                "(verdict {route}). Hand the rest of the research to a worker.")
START_TEXT = "orchestrator router: starting the router daemon on {url}. First answers arrive after the model loads."
SET_TEXT = 'the router set model "{tier}" for this worker.'
REPLACED_TEXT = 'the router set model "{tier}" for this worker, replacing "{given}".'
