#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${1:-$PWD}"

WORKFLOW_REL_PATH=".github/workflows/release-gerbers.yml"
SCRIPT_REL_PATH="scripts/generate_release_artifacts.py"
UPDATE_CHECK_SCRIPT_REL_PATH="scripts/check_release_automation_update.py"
CLI_HELPER_REL_PATH="scripts/find_kicad_cli.py"
CLI_CONTAINER_SCRIPT_REL_PATH="scripts/setup_kicad_cli_container.sh"
PACKAGE_SCRIPT_REL_PATH="scripts/package_release_artifacts.sh"
CONFIG_REL_PATH="release-artifacts.json"
METADATA_REL_PATH=".kicad-release-automation-version.json"

compute_sha256() {
  local file_path="$1"

  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file_path" | awk '{print $1}'
    return
  fi

  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file_path" | awk '{print $1}'
    return
  fi

  python3 - "$file_path" <<'PY'
import hashlib
import pathlib
import sys

file_path = pathlib.Path(sys.argv[1])
print(hashlib.sha256(file_path.read_bytes()).hexdigest())
PY
}

resolve_module_version() {
  if [[ -n "${KICAD_RELEASE_AUTOMATION_VERSION:-}" ]]; then
    printf '%s\n' "$KICAD_RELEASE_AUTOMATION_VERSION"
    return
  fi

  if git -C "$SCRIPT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if git -C "$SCRIPT_DIR" describe --tags --exact-match >/dev/null 2>&1; then
      git -C "$SCRIPT_DIR" describe --tags --exact-match
      return
    fi

    git -C "$SCRIPT_DIR" describe --tags --always --dirty 2>/dev/null || true
    return
  fi

  printf '%s\n' "unknown"
}

resolve_module_repo_url() {
  if [[ -n "${KICAD_RELEASE_AUTOMATION_REPO_URL:-}" ]]; then
    printf '%s\n' "$KICAD_RELEASE_AUTOMATION_REPO_URL"
    return
  fi

  if git -C "$SCRIPT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "$SCRIPT_DIR" remote get-url origin 2>/dev/null || true
    return
  fi

  printf '\n'
}

resolve_module_repo_slug() {
  if [[ -n "${KICAD_RELEASE_AUTOMATION_REPO:-}" ]]; then
    printf '%s\n' "$KICAD_RELEASE_AUTOMATION_REPO"
    return
  fi

  local repo_url
  repo_url="$(resolve_module_repo_url)"

  if [[ "$repo_url" =~ github\.com[:/]([^/]+)/([^/.]+)(\.git)?$ ]]; then
    printf '%s/%s\n' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
    return
  fi

  printf '\n'
}

write_metadata_file() {
  local module_version
  local module_repo
  local module_repo_url
  local installed_at
  local script_sha
  local helper_sha
  local cli_helper_sha
  local cli_container_sha
  local package_sha
  local workflow_sha

  module_version="$(resolve_module_version)"
  module_repo="$(resolve_module_repo_slug)"
  module_repo_url="$(resolve_module_repo_url)"
  installed_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  script_sha="$(compute_sha256 "$TARGET_DIR/$SCRIPT_REL_PATH")"
  helper_sha="$(compute_sha256 "$TARGET_DIR/$UPDATE_CHECK_SCRIPT_REL_PATH")"
  cli_helper_sha="$(compute_sha256 "$TARGET_DIR/$CLI_HELPER_REL_PATH")"
  cli_container_sha="$(compute_sha256 "$TARGET_DIR/$CLI_CONTAINER_SCRIPT_REL_PATH")"
  package_sha="$(compute_sha256 "$TARGET_DIR/$PACKAGE_SCRIPT_REL_PATH")"
  workflow_sha="$(compute_sha256 "$TARGET_DIR/$WORKFLOW_REL_PATH")"

  cat > "$TARGET_DIR/$METADATA_REL_PATH" <<EOF
{
  "schema_version": 2,
  "installed_at": $(printf '%s' "$installed_at" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
  "module_repo": $(printf '%s' "$module_repo" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
  "module_repo_url": $(printf '%s' "$module_repo_url" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
  "module_version": $(printf '%s' "$module_version" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
  "installed_version": $(printf '%s' "$module_version" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
  "managed_files": {
    "scripts/generate_release_artifacts.py": {
      "version": $(printf '%s' "$module_version" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
      "sha256": $(printf '%s' "$script_sha" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
      "installed_at": $(printf '%s' "$installed_at" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')
    },
    "scripts/check_release_automation_update.py": {
      "version": $(printf '%s' "$module_version" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
      "sha256": $(printf '%s' "$helper_sha" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
      "installed_at": $(printf '%s' "$installed_at" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')
    },
    "scripts/find_kicad_cli.py": {
      "version": $(printf '%s' "$module_version" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
      "sha256": $(printf '%s' "$cli_helper_sha" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
      "installed_at": $(printf '%s' "$installed_at" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')
    },
    "scripts/setup_kicad_cli_container.sh": {
      "version": $(printf '%s' "$module_version" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
      "sha256": $(printf '%s' "$cli_container_sha" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
      "installed_at": $(printf '%s' "$installed_at" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')
    },
    "scripts/package_release_artifacts.sh": {
      "version": $(printf '%s' "$module_version" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
      "sha256": $(printf '%s' "$package_sha" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
      "installed_at": $(printf '%s' "$installed_at" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')
    },
    ".github/workflows/release-gerbers.yml": {
      "version": $(printf '%s' "$module_version" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
      "sha256": $(printf '%s' "$workflow_sha" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
      "installed_at": $(printf '%s' "$installed_at" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')
    }
  }
}
EOF

  echo "Recorded installed module metadata: $METADATA_REL_PATH"
}

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
cp "$SCRIPT_DIR/scripts/check_release_automation_update.py" \
  "$TARGET_DIR/$UPDATE_CHECK_SCRIPT_REL_PATH"
cp "$SCRIPT_DIR/scripts/find_kicad_cli.py" \
  "$TARGET_DIR/$CLI_HELPER_REL_PATH"
cp "$SCRIPT_DIR/scripts/setup_kicad_cli_container.sh" \
  "$TARGET_DIR/$CLI_CONTAINER_SCRIPT_REL_PATH"
cp "$SCRIPT_DIR/scripts/package_release_artifacts.sh" \
  "$TARGET_DIR/$PACKAGE_SCRIPT_REL_PATH"
chmod +x "$TARGET_DIR/$CLI_CONTAINER_SCRIPT_REL_PATH" "$TARGET_DIR/$PACKAGE_SCRIPT_REL_PATH" 2>/dev/null || true

if [[ ! -f "$TARGET_DIR/$CONFIG_REL_PATH" ]]; then
  cp "$SCRIPT_DIR/examples/release-artifacts.json" "$TARGET_DIR/$CONFIG_REL_PATH"
  echo "Created release-artifacts.json from template."
else
  echo "release-artifacts.json already exists; preserved local configuration."
fi

write_metadata_file

echo "Installed KiCad release automation into: $TARGET_DIR"
echo "Next: review release-artifacts.json project.path and commit changes."
