#!/usr/bin/env bash
# SessionStart and PreCompact. Loads the full protocol once, so the per-turn
# reminder can stay short.
# No "set -e": this hook must fail open. A broken check should never block delegation.
set -uo pipefail
cat >/dev/null 2>&1 || true

[ "${DELEGATION_POLICY_OFF:-0}" = "1" ] && exit 0

root="${CLAUDE_PLUGIN_ROOT:-}"
protocol="$root/references/delegation-protocol.md"

if [ -n "$root" ] && [ -f "$protocol" ]; then
  cat "$protocol"
else
  echo "delegation-policy is active. Delegate work to subagents, state a model on every Agent call, never use fable, and require verified evidence in every subagent report."
fi
exit 0
