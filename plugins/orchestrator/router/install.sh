#!/usr/bin/env bash
# Installs the orchestrator router: a small Python environment with laya, plus
# a one-time model download so the first real session does not wait for it.
#
# Run this once after you add the orchestrator package. It creates the
# environment under the plugin's data directory, never inside the repo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAYA_VERSION="${ORCHESTRATOR_LAYA_VERSION:-0.3.11}"

# The data directory must be the one Claude Code gives this package's hooks.
# A CLAUDE_PLUGIN_DATA in your shell can belong to another package, so it
# only counts when it names an orchestrator directory.
data_dir() {
  case "$(basename "${CLAUDE_PLUGIN_DATA:-}")" in
    orchestrator-*) printf '%s' "$CLAUDE_PLUGIN_DATA"; return ;;
  esac
  # Installed from a marketplace: the cache path names the marketplace.
  case "$SCRIPT_DIR" in
    "$HOME"/.claude/plugins/cache/*/orchestrator/*/router)
      local marketplace
      marketplace=$(printf '%s' "$SCRIPT_DIR" | sed -E 's#.*/plugins/cache/([^/]+)/orchestrator/.*#\1#')
      printf '%s' "$HOME/.claude/plugins/data/orchestrator-$marketplace"
      return ;;
  esac
  # A repository checkout: use the marketplace install's directory when it exists.
  if [ -d "$HOME/.claude/plugins/data/orchestrator-egonm12-plugins" ]; then
    printf '%s' "$HOME/.claude/plugins/data/orchestrator-egonm12-plugins"
    return
  fi
  printf '%s' "$HOME/.claude/orchestrator"
}

DATA_DIR="$(data_dir)"
VENV_DIR="$DATA_DIR/router-venv"

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
