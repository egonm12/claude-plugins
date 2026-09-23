#!/usr/bin/env bash
# PreToolUse gate for the Agent tool.
#
# Denies a worker that asks for Fable. This is the one hard rule.
# Warns when the model is missing, unknown, or cannot be read from the call.
# Fails open on everything except Fable: an internal problem lets the call through.

# No "set -e": a broken check should never block delegation.
set -uo pipefail

payload=$(cat 2>/dev/null || true)

# Escape hatch. Set this to switch the whole package off for a session.
if [ "${ORCHESTRATOR_OFF:-0}" = "1" ]; then
  exit 0
fi

# Debug aid. Set ORCHESTRATOR_DEBUG to a file path to capture the real
# hook payload, then inspect it to see which fields Claude Code actually sends.
if [ -n "${ORCHESTRATOR_DEBUG:-}" ]; then
  printf '%s\n' "$payload" >>"$ORCHESTRATOR_DEBUG" 2>/dev/null || true
fi

# Homebrew and /usr/local are often missing from the hook PATH.
PATH="$PATH:/opt/homebrew/bin:/usr/local/bin"
export PATH

# Models a worker may use without a warning. Fable is denied even if listed.
allowed_models="${ORCHESTRATOR_MODELS:-opus,sonnet,haiku}"
allowed_list=$(printf '%s' "$allowed_models" | tr '[:upper:]' '[:lower:]' | tr -d ' ' | sed 's/,/, /g')

deny_fable() {
  cat >&2 <<MSG
Blocked by orchestrator: this Agent call asks for Fable (model "$1").

Fable workers are not allowed. Re-issue the call with one of: $allowed_list.
The orchestrator protocol says which model fits which work.

Task was: ${2:-<no description>}
MSG
  exit 2
}

# Reduced mode. Without jq the gate cannot read fields, so it searches the raw
# payload instead. It may over-block, for example a description that mentions
# Fable, but it never lets a Fable call through.
if ! command -v jq >/dev/null 2>&1; then
  if printf '%s' "$payload" | grep -Eq '"tool_name"[[:space:]]*:[[:space:]]*"(Agent|Task)"'; then
    if printf '%s' "$payload" | grep -qi 'fable'; then
      deny_fable "unknown, found by text search" ""
    fi
    printf '%s\n' '{"systemMessage":"orchestrator: jq is not installed, so the model gate runs in reduced mode. It blocks any Agent call that mentions Fable and checks nothing else. Install jq to restore the full gate."}'
  fi
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
  *fable*) deny_fable "$model" "$description" ;;
esac

# A model is known when it is a short name from the list, such as "sonnet",
# or a full ID for one, such as "claude-sonnet-5".
is_known_model() {
  local entry
  local IFS=','
  for entry in $allowed_models; do
    entry=$(printf '%s' "$entry" | tr '[:upper:]' '[:lower:]' | tr -d ' ')
    [ -z "$entry" ] && continue
    case "$1" in
      "$entry" | "claude-$entry" | "claude-$entry-"*) return 0 ;;
    esac
  done
  return 1
}

# Rule 2: warn about what the gate cannot resolve or does not recognise.
warning=""

if [ "$subagent_type" = "fork" ]; then
  warning="This is a fork. It ignores any model override and runs on the session model, which this hook cannot read. It also inherits your full conversation. Confirm the session is not on Fable, and say in your next message why a fork was needed instead of a fresh worker."
elif [ -z "$model" ]; then
  warning="This Agent call sets no model. The effective model comes from the agent definition or the configured default, which this hook cannot read. Set model explicitly so the choice is stated, or confirm the agent definition pins a non-Fable model."
elif ! is_known_model "$lower_model"; then
  warning="This Agent call sets model \"$model\", which is not in the allowed list ($allowed_list). Check it for a typo. If you meant it, say why in your next message."
fi

# additionalContext reaches Claude. systemMessage is shown to the user only.
if [ -n "$warning" ]; then
  jq -n --arg msg "orchestrator: $warning" \
    '{systemMessage: $msg, hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $msg}}'
fi

exit 0
