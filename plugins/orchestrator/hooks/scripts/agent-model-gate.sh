#!/usr/bin/env bash
# PreToolUse gate for the Agent tool.
#
# Denies a subagent that explicitly asks for Fable.
# Warns when the effective model cannot be read from the tool call.
# Fails open: any internal problem lets the call through.

# No "set -e": this hook must fail open. A broken check should never block delegation.
set -uo pipefail

payload=$(cat 2>/dev/null || true)

# Escape hatch. Set this to switch the whole plugin off for a session.
if [ "${ORCHESTRATOR_OFF:-0}" = "1" ]; then
  exit 0
fi

# Debug aid. Set ORCHESTRATOR_DEBUG to a file path to capture the real
# hook payload, then inspect it to see which fields Claude Code actually sends.
if [ -n "${ORCHESTRATOR_DEBUG:-}" ]; then
  printf '%s\n' "$payload" >>"$ORCHESTRATOR_DEBUG" 2>/dev/null || true
fi

# Homebrew and mise are often missing from the hook PATH.
PATH="$PATH:/opt/homebrew/bin:/usr/local/bin"
export PATH

if ! command -v jq >/dev/null 2>&1; then
  exit 0
fi

read_field() {
  printf '%s' "$payload" | jq -r "$1 // \"\"" 2>/dev/null || printf ''
}

tool_name=$(read_field '.tool_name')
# The tool schema calls this "Agent". Hook payloads have also been seen as
# "Task". Accept both so the gate cannot silently become a no-op.
case "$tool_name" in
  Agent|Task) ;;
  *) exit 0 ;;
esac

model=$(read_field '.tool_input.model')
subagent_type=$(read_field '.tool_input.subagent_type')
description=$(read_field '.tool_input.description')

lower_model=$(printf '%s' "$model" | tr '[:upper:]' '[:lower:]')

# Rule 1: deny what the gate can see is off policy.
case "$lower_model" in
  *fable*)
    cat >&2 <<MSG
Blocked by orchestrator: this Agent call sets model "$model".

Fable subagents are not allowed in this workspace. Re-issue the call with one of:
  model: "opus"    for judgement, design, review, and ambiguous work
  model: "sonnet"  for normal implementation and research
  model: "haiku"   for mechanical work such as grepping, listing, or reformatting

Task was: ${description:-<no description>}
MSG
    exit 2
    ;;
esac

# Rule 2: warn about what the gate cannot resolve.
warning=""

if [ "$subagent_type" = "fork" ]; then
  warning="This is a fork. It ignores any model override and runs on the session model, which this hook cannot read. It also inherits your full conversation. Confirm the session is not on Fable, and say in your next message why a fork was needed instead of a fresh subagent."
elif [ -z "$model" ]; then
  warning="This Agent call sets no model. The effective model comes from the agent definition or the configured default, which this hook cannot read. Set model explicitly so the choice is stated, or confirm the agent definition pins a non-Fable model."
fi

# additionalContext reaches Claude. systemMessage is shown to the user only.
if [ -n "$warning" ]; then
  jq -n --arg msg "orchestrator: $warning" \
    '{systemMessage: $msg, hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $msg}}'
fi

exit 0
