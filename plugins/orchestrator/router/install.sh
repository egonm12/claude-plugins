#!/usr/bin/env bash
# Installs the orchestrator router: a small Python environment with laya, plus
# a one-time model download so the first real session does not wait for it.
#
# Run this once after you add the orchestrator package. It creates the
# environment under the plugin's data directory, never inside the repo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${CLAUDE_PLUGIN_DATA:-$HOME/.claude/orchestrator}"
VENV_DIR="$DATA_DIR/router-venv"
LAYA_VERSION="${ORCHESTRATOR_LAYA_VERSION:-0.3.7}"

mkdir -p "$DATA_DIR"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "orchestrator router: creating the Python environment at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
else
  echo "orchestrator router: reusing the Python environment at $VENV_DIR"
fi

echo "orchestrator router: upgrading pip"
"$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip

echo "orchestrator router: installing laya==$LAYA_VERSION"
"$VENV_DIR/bin/python" -m pip install --quiet "laya==$LAYA_VERSION"

echo "orchestrator router: downloading the checkpoint (this can take a while)"
"$VENV_DIR/bin/python" -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
import router
m = router.load_model()
print(router.route_prompt(m, 'hello'))
"

echo "orchestrator router: install done."
echo
echo "Check the daemon's health once a Claude Code session has started it:"
echo "  curl -s http://127.0.0.1:8790/health"
echo
echo "You do not need to start the daemon yourself. The SessionStart hook"
echo "starts it on the next Claude Code session, the first time it is needed."
