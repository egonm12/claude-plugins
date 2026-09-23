#!/usr/bin/env bash
# SessionStart. Loads the full protocol into Claude's context. SessionStart
# also fires after compaction, with source "compact", so this reloads it then.
# No "set -e": this hook must fail open. A broken check should never block delegation.
set -uo pipefail
cat >/dev/null 2>&1 || true

[ "${ORCHESTRATOR_OFF:-0}" = "1" ] && exit 0

root="${CLAUDE_PLUGIN_ROOT:-}"
protocol="$root/references/orchestrator-protocol.md"

if [ -n "$root" ] && [ -f "$protocol" ]; then
  cat "$protocol"
else
  echo "orchestrator is active. Delegate reading and searching to workers, state a model on every Agent call, never use fable, and require verified evidence in every worker report."
fi
exit 0
