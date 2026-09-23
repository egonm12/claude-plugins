#!/usr/bin/env bash
# UserPromptSubmit. Puts the delegation trigger next to every new prompt.
# The text is the one line in the protocol that starts with "> Before you start:",
# so the reminder cannot drift from the protocol.
# No "set -e": this hook must fail open. A broken check should never block a prompt.
set -uo pipefail
cat >/dev/null 2>&1 || true

[ "${ORCHESTRATOR_OFF:-0}" = "1" ] && exit 0

root="${CLAUDE_PLUGIN_ROOT:-}"
protocol="$root/references/orchestrator-protocol.md"

line=""
if [ -n "$root" ] && [ -f "$protocol" ]; then
  line=$(grep -m1 '^> Before you start:' "$protocol" 2>/dev/null | sed 's/^> //')
fi

if [ -n "$line" ]; then
  printf 'orchestrator: %s\n' "$line"
else
  echo "orchestrator: Before you start, decide whether this needs workers. Delegate research, keep actions and decisions."
fi
exit 0
