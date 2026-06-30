#!/usr/bin/env bash
# install.sh — deploy memos-hermes-remote to a Hermes Agent installation.
#
# Writes the shim into ~/.hermes/memos-plugin/, writes .memos-node-bin, and
# creates the provider symlink so Hermes can discover memtensor.
#
# Environment variables honoured:
#   MEMOS_HOME     where ~/.hermes lives  (default: $HOME/.hermes)
#   SCRIPT_DIR     where this script lives (default: cwd)

set -euo pipefail

MEMOS_HOME="${MEMOS_HOME:-$HOME/.hermes}"
SCRIPT_DIR="${SCRIPT_DIR:-$(cd "$(dirname "$0")" && pwd)}"
PLUGIN_DIR="$MEMOS_HOME/memos-plugin"
PROVIDER_SRC="$PLUGIN_DIR/adapters/hermes/memos_provider"

# ----- checks ------------------------------------------------------
if [ ! -f "$SCRIPT_DIR/shim.py" ]; then
  echo "ERROR: shim.py not found in $SCRIPT_DIR"
  echo "       Run this from the cloned repo, or set SCRIPT_DIR."
  exit 1
fi

if [ ! -d "$PLUGIN_DIR" ]; then
  echo "WARNING: $PLUGIN_DIR does not exist — the MemOS plugin may not be installed."
  echo "         Run 'hermes setup memos' first, or install manually."
fi

# ----- deploy shim -------------------------------------------------
mkdir -p "$PLUGIN_DIR"
cp "$SCRIPT_DIR/shim.py" "$PLUGIN_DIR/shim.py"
chmod +x "$PLUGIN_DIR/shim.py"
echo "✓ shim.py → $PLUGIN_DIR/shim.py"

# ----- write .memos-node-bin ---------------------------------------
echo "$PLUGIN_DIR/shim.py" > "$PLUGIN_DIR/.memos-node-bin"
echo "✓ .memos-node-bin → $PLUGIN_DIR/shim.py"

# ----- provider discovery symlink -----------------------------------
if [ -d "$PROVIDER_SRC" ]; then
  rm -f "$MEMOS_HOME/plugins/memtensor"
  ln -sfn "$PROVIDER_SRC" "$MEMOS_HOME/plugins/memtensor"
  echo "✓ provider symlink → $MEMOS_HOME/plugins/memtensor"
else
  echo "⚠  provider source not found at $PROVIDER_SRC — the plugin may need manual setup"
fi

# ----- next steps ---------------------------------------------------
cat << 'BANNER'

Done.  Next steps:

1.  Set environment variables:
      export MEMOS_HOST=<remote-ip>
      export MEMOS_SSH_HOST=<ssh-alias>

2.  Add to ~/.hermes/config.yaml:
      memory:
        provider: memtensor

3.  Restart Hermes.
      If Hermes is running as a desktop app, quit and re-open.
BANNER
