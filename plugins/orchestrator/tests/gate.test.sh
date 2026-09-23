#!/usr/bin/env bash
# Offline tests for the orchestrator package. Needs bash and jq.
# Run from anywhere: bash plugins/orchestrator/tests/gate.test.sh

set -uo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
gate="$root/hooks/scripts/agent-model-gate.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

pass=0
fail=0

ok() { pass=$((pass + 1)); }
not_ok() { fail=$((fail + 1)); printf 'FAIL: %s\n' "$1"; }

# check NAME SCRIPT PAYLOAD EXPECTED_EXIT STDOUT_PATTERN STDERR_PATTERN [ENV...]
# An empty pattern means that stream must be empty.
check() {
  local name="$1" script="$2" payload="$3" want_exit="$4" want_out="$5" want_err="$6"
  shift 6
  printf '%s' "$payload" | env "$@" bash "$script" >"$tmp/out" 2>"$tmp/err"
  local got_exit=$?
  if [ "$got_exit" != "$want_exit" ]; then
    not_ok "$name: exit $got_exit, want $want_exit"; return
  fi
  if [ -z "$want_out" ]; then
    [ -s "$tmp/out" ] && { not_ok "$name: stdout not empty: $(cat "$tmp/out")"; return; }
  else
    grep -Eq "$want_out" "$tmp/out" || { not_ok "$name: stdout does not match /$want_out/: $(cat "$tmp/out")"; return; }
  fi
  if [ -z "$want_err" ]; then
    [ -s "$tmp/err" ] && { not_ok "$name: stderr not empty: $(cat "$tmp/err")"; return; }
  else
    grep -Eq "$want_err" "$tmp/err" || { not_ok "$name: stderr does not match /$want_err/"; return; }
  fi
  ok
}

agent() { printf '{"tool_name":"Agent","tool_input":%s}' "$1"; }
warn='"additionalContext":'

# Hard rule: Fable is denied.
check "fable short name"  "$gate" "$(agent '{"model":"fable","description":"x"}')" 2 "" "Blocked by orchestrator"
check "fable full id"     "$gate" "$(agent '{"model":"claude-fable-5-1"}')"        2 "" "Blocked by orchestrator"
check "fable upper case"  "$gate" "$(agent '{"model":"FABLE"}')"                   2 "" "Blocked by orchestrator"
check "fable via Task"    "$gate" '{"tool_name":"Task","tool_input":{"model":"fable"}}' 2 "" "Blocked by orchestrator"
check "fable listed"      "$gate" "$(agent '{"model":"fable"}')" 2 "" "Blocked by orchestrator" ORCHESTRATOR_MODELS=opus,fable
check "fable in object"   "$gate" "$(agent '{"model":{"name":"fable"}}')"          2 "" "Blocked by orchestrator"

# Allowed models pass silently.
check "opus"              "$gate" "$(agent '{"model":"opus"}')"                    0 "" ""
check "sonnet"            "$gate" "$(agent '{"model":"sonnet"}')"                  0 "" ""
check "haiku"             "$gate" "$(agent '{"model":"haiku"}')"                   0 "" ""
check "full id"           "$gate" "$(agent '{"model":"claude-sonnet-5"}')"         0 "" ""
check "full id dated"     "$gate" "$(agent '{"model":"claude-haiku-4-5-20251001"}')" 0 "" ""
check "full id 1m"        "$gate" "$(agent '{"model":"claude-opus-5-5[1m]"}')"     0 "" ""
check "mixed case"        "$gate" "$(agent '{"model":"Sonnet"}')"                  0 "" ""

# Warnings reach Claude through additionalContext.
check "typo"              "$gate" "$(agent '{"model":"sonet"}')"                   0 "$warn.*not in the allowed list" ""
check "other vendor"      "$gate" "$(agent '{"model":"gpt-5"}')"                   0 "$warn.*not in the allowed list" ""
check "prefix trick"      "$gate" "$(agent '{"model":"claude-sonnetx"}')"          0 "$warn.*not in the allowed list" ""
check "no model"          "$gate" "$(agent '{"description":"x"}')"                 0 "$warn.*sets no model" ""
check "fork"              "$gate" "$(agent '{"subagent_type":"fork","model":"opus"}')" 0 "$warn.*This is a fork" ""
check "custom list"       "$gate" "$(agent '{"model":"sonnet"}')" 0 "$warn.*allowed list \(opus\)" "" ORCHESTRATOR_MODELS=opus

# Other tools and bad input pass untouched.
check "other tool"        "$gate" '{"tool_name":"Bash","tool_input":{"model":"fable"}}' 0 "" ""
check "empty payload"     "$gate" ''                                                0 "" ""
check "malformed payload" "$gate" '{not json'                                       0 "" ""

# Off switch and debug capture.
check "off switch"        "$gate" "$(agent '{"model":"fable"}')" 0 "" "" ORCHESTRATOR_OFF=1
check "debug capture"     "$gate" "$(agent '{"model":"opus"}')"  0 "" "" ORCHESTRATOR_DEBUG="$tmp/debug.jsonl"
grep -q '"model":"opus"' "$tmp/debug.jsonl" 2>/dev/null && ok || not_ok "debug capture: payload not written"

# Reduced mode: a copy of the gate that cannot find jq.
nojq="$tmp/gate-nojq.sh"
sed 's/command -v jq /command -v jq-missing-for-test /' "$gate" >"$nojq"
grep -q 'jq-missing-for-test' "$nojq" || not_ok "reduced mode: could not build the no-jq copy"
check "no jq: fable"      "$nojq" "$(agent '{"model":"fable"}')"   2 "" "Blocked by orchestrator"
check "no jq: opus"       "$nojq" "$(agent '{"model":"opus"}')"    0 "reduced mode" ""
check "no jq: other tool" "$nojq" '{"tool_name":"Bash","tool_input":{}}' 0 "" ""

# Package files.
jq -e . "$root/hooks/hooks.json" >/dev/null && ok || not_ok "hooks.json is not valid JSON"
jq -e . "$root/.claude-plugin/plugin.json" >/dev/null && ok || not_ok "plugin.json is not valid JSON"

# Drift: the four reporting rules must match word for word in the protocol and every worker.
rules() { grep -E '^[1-4]\. ' "$1"; }
protocol="$root/references/orchestrator-protocol.md"
[ "$(rules "$protocol" | wc -l | tr -d ' ')" = "4" ] && ok || not_ok "drift: protocol does not have exactly four numbered rules"
for worker in "$root"/agents/*.md; do
  [ "$(rules "$worker")" = "$(rules "$protocol")" ] && ok || not_ok "drift: reporting rules in $(basename "$worker") differ from the protocol"
done

# Drift: the protocol's model table must list exactly the gate's default models.
table=$(grep -Eo '^\| `[a-z]+` \|' "$protocol" | tr -d '|` ' | paste -sd, -)
default=$(grep -Eo 'ORCHESTRATOR_MODELS:-[a-z,]+' "$gate" | sed 's/.*:-//')
[ "$table" = "$default" ] && ok || not_ok "drift: protocol model table ($table) differs from the gate default ($default)"

# The tool-neutral instructions must not name models.
grep -Eiq 'opus|sonnet|haiku|fable' "$root/.apm/instructions/orchestrator.instructions.md" \
  && not_ok "instructions name a model, but they must stay tool-neutral" || ok

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = "0" ]
