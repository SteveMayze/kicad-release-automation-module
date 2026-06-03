#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${1:-$PWD}"

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "Target directory does not exist: $TARGET_DIR" >&2
  exit 1
fi

mkdir -p "$TARGET_DIR/.github/workflows"
mkdir -p "$TARGET_DIR/scripts"

cp "$SCRIPT_DIR/templates/.github/workflows/release-gerbers.yml" \
  "$TARGET_DIR/.github/workflows/release-gerbers.yml"
cp "$SCRIPT_DIR/scripts/generate_release_artifacts.py" \
  "$TARGET_DIR/scripts/generate_release_artifacts.py"

if [[ ! -f "$TARGET_DIR/release-artifacts.json" ]]; then
  cp "$SCRIPT_DIR/examples/release-artifacts.json" "$TARGET_DIR/release-artifacts.json"
  echo "Created release-artifacts.json from template."
else
  echo "release-artifacts.json already exists; left unchanged."
fi

echo "Installed KiCad release automation into: $TARGET_DIR"
echo "Next: review release-artifacts.json project.path and commit changes."
