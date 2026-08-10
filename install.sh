#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${1:-$PWD}"

WORKFLOW_REL_PATH=".github/workflows/release-gerbers.yml"
SCRIPT_REL_PATH="scripts/generate_release_artifacts.py"
CONFIG_REL_PATH="release-artifacts.json"

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "Target directory does not exist: $TARGET_DIR" >&2
  exit 1
fi

mkdir -p "$TARGET_DIR/.github/workflows"
mkdir -p "$TARGET_DIR/scripts"

IS_UPDATE=false
if [[ -f "$TARGET_DIR/$WORKFLOW_REL_PATH" || -f "$TARGET_DIR/$SCRIPT_REL_PATH" ]]; then
  IS_UPDATE=true
fi

if [[ "$IS_UPDATE" == "true" ]]; then
  echo "Existing KiCad release automation detected; updating managed files."
else
  echo "No existing KiCad release automation detected; performing fresh install."
fi

cp "$SCRIPT_DIR/templates/.github/workflows/release-gerbers.yml" \
  "$TARGET_DIR/$WORKFLOW_REL_PATH"
cp "$SCRIPT_DIR/scripts/generate_release_artifacts.py" \
  "$TARGET_DIR/$SCRIPT_REL_PATH"

if [[ ! -f "$TARGET_DIR/$CONFIG_REL_PATH" ]]; then
  cp "$SCRIPT_DIR/examples/release-artifacts.json" "$TARGET_DIR/$CONFIG_REL_PATH"
  echo "Created release-artifacts.json from template."
else
  echo "release-artifacts.json already exists; preserved local configuration."
fi

echo "Installed KiCad release automation into: $TARGET_DIR"
echo "Next: review release-artifacts.json project.path and commit changes."
