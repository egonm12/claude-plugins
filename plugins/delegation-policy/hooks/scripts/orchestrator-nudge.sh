#!/usr/bin/env bash
# UserPromptSubmit reminder. Kept to a few lines because it costs tokens on every turn.
# No "set -e": this hook must fail open. A broken check should never block delegation.
set -uo pipefail
cat >/dev/null 2>&1 || true

[ "${DELEGATION_POLICY_OFF:-0}" = "1" ] && exit 0

cat <<'TXT'
delegation-policy: you are the orchestrator. Delegate the reading and searching to subagents, keep the judgement. Pass model explicitly: opus for judgement, sonnet for implementation, haiku for mechanical work. Never fable. Tell every subagent to verify its claims and cite file:line evidence, never to assume. You still own the final quality check.
TXT
exit 0
