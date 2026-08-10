#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-$PWD}"

WORKFLOW_REL_PATH=".github/workflows/release-gerbers.yml"
SCRIPT_REL_PATH="scripts/generate_release_artifacts.py"
CONFIG_REL_PATH="release-artifacts.json"

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "Target directory does not exist: $TARGET_DIR" >&2
  exit 1
fi

echo "Removing managed KiCad release automation files from: $TARGET_DIR"

if [[ -f "$TARGET_DIR/$WORKFLOW_REL_PATH" ]]; then
  rm -f "$TARGET_DIR/$WORKFLOW_REL_PATH"
  echo "Removed: $WORKFLOW_REL_PATH"
else
  echo "Not present: $WORKFLOW_REL_PATH"
fi

if [[ -f "$TARGET_DIR/$SCRIPT_REL_PATH" ]]; then
  rm -f "$TARGET_DIR/$SCRIPT_REL_PATH"
  echo "Removed: $SCRIPT_REL_PATH"
else
  echo "Not present: $SCRIPT_REL_PATH"
fi

if [[ -f "$TARGET_DIR/$CONFIG_REL_PATH" ]]; then
  echo "Preserved local config: $CONFIG_REL_PATH"
fi

# Clean up empty directories created by install.sh.
rmdir --ignore-fail-on-non-empty "$TARGET_DIR/.github/workflows" 2>/dev/null || true
rmdir --ignore-fail-on-non-empty "$TARGET_DIR/.github" 2>/dev/null || true
rmdir --ignore-fail-on-non-empty "$TARGET_DIR/scripts" 2>/dev/null || true

echo "Uninstall complete."
