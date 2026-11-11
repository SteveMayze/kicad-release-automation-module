#!/usr/bin/env bash
# Create a kicad-cli shim that runs kicad-cli from a KiCad container image.
#
# Usage: setup_kicad_cli_container.sh <image> <bin-dir>
#
# Writes an executable "<bin-dir>/kicad-cli" and prints its absolute path on
# stdout (everything else goes to stderr). The shim runs the image with one host
# directory mounted at the same absolute path inside the container, so absolute
# paths below that directory work unchanged.
#
# Optional environment:
#   KICAD_CLI_MOUNT_DIR  Directory made visible to kicad-cli.
#                        Default: $GITHUB_WORKSPACE, else the current directory.
#   KICAD_CLI_HOME       Writable HOME for the container.
#                        Default: "kicad-home" next to <bin-dir>.
#   KICAD_CLI_PULL_ATTEMPTS  Number of docker pull attempts (default: 3).
set -euo pipefail

log() {
  echo "$*" >&2
}

if [[ $# -ne 2 || -z "$1" || -z "$2" ]]; then
  log "Usage: $(basename "$0") <image> <bin-dir>"
  exit 2
fi

IMAGE="$1"
BIN_DIR_ARG="$2"

if ! command -v docker >/dev/null 2>&1; then
  log "docker is required to run kicad-cli from image '$IMAGE' but was not found."
  exit 1
fi

MOUNT_DIR_ARG="${KICAD_CLI_MOUNT_DIR:-${GITHUB_WORKSPACE:-$PWD}}"
if [[ ! -d "$MOUNT_DIR_ARG" ]]; then
  log "Mount directory does not exist: $MOUNT_DIR_ARG"
  exit 1
fi
MOUNT_DIR="$(cd "$MOUNT_DIR_ARG" && pwd)"

mkdir -p "$BIN_DIR_ARG"
BIN_DIR="$(cd "$BIN_DIR_ARG" && pwd)"

HOME_DIR_ARG="${KICAD_CLI_HOME:-$(dirname "$BIN_DIR")/kicad-home}"
mkdir -p "$HOME_DIR_ARG"
HOME_DIR="$(cd "$HOME_DIR_ARG" && pwd)"

SHIM="$BIN_DIR/kicad-cli"
RUN_USER="$(id -u):$(id -g)"

ATTEMPTS="${KICAD_CLI_PULL_ATTEMPTS:-3}"
PULLED=0
for ((ATTEMPT = 1; ATTEMPT <= ATTEMPTS; ATTEMPT++)); do
  if docker pull "$IMAGE" >&2; then
    PULLED=1
    break
  fi
  if [[ "$ATTEMPT" -lt "$ATTEMPTS" ]]; then
    DELAY=$((ATTEMPT * 15))
    log "docker pull attempt $ATTEMPT failed; retrying in ${DELAY}s"
    sleep "$DELAY"
  fi
done
if [[ "$PULLED" -ne 1 ]]; then
  log "Could not pull KiCad image '$IMAGE' after $ATTEMPTS attempt(s)."
  exit 1
fi

# Diagnostic: an entrypoint other than null would receive "kicad-cli" as an
# argument instead of running it.
log "Image entrypoint/cmd:"
docker inspect --format '{{json .Config.Entrypoint}} {{json .Config.Cmd}}' "$IMAGE" >&2

# Image, mount directory and home are baked in now; $PWD and "$@" are evaluated
# each time the shim runs.
{
  echo '#!/usr/bin/env bash'
  echo 'set -euo pipefail'
  printf 'KICAD_IMAGE=%q\n' "$IMAGE"
  printf 'KICAD_MOUNT_DIR=%q\n' "$MOUNT_DIR"
  printf 'KICAD_HOME=%q\n' "$HOME_DIR"
  echo 'exec docker run --rm --user "$(id -u):$(id -g)" -e HOME="$KICAD_HOME" -v "$KICAD_HOME:$KICAD_HOME" -v "$KICAD_MOUNT_DIR:$KICAD_MOUNT_DIR" -w "$PWD" "$KICAD_IMAGE" kicad-cli "$@"'
} > "$SHIM"
chmod +x "$SHIM"

if ! VERSION_OUTPUT="$(cd "$MOUNT_DIR" && "$SHIM" --version)"; then
  log "kicad-cli --version failed in image '$IMAGE'. Does the image provide kicad-cli?"
  exit 1
fi
if [[ -z "$VERSION_OUTPUT" ]]; then
  log "kicad-cli --version produced no output from image '$IMAGE'."
  exit 1
fi
log "Using KiCad CLI shim at: $SHIM"
log "kicad-cli version: $VERSION_OUTPUT"

# The container must be able to write to its HOME and to the mounted directory
# as the calling user, and files it creates must be owned by that user.
PROBE="$MOUNT_DIR/.kicad-cli-probe"
docker run --rm --user "$RUN_USER" -e HOME="$HOME_DIR" \
  -v "$HOME_DIR:$HOME_DIR" -v "$MOUNT_DIR:$MOUNT_DIR" \
  -w "$MOUNT_DIR" "$IMAGE" \
  sh -c 'touch "$HOME/.probe" "$1"' sh "$PROBE" >&2
PROBE_OWNER="$(stat -c '%u:%g' "$PROBE")"
rm -f "$PROBE" "$HOME_DIR/.probe"
log "Container-written file owner: $PROBE_OWNER (caller: $RUN_USER)"
if [[ "$PROBE_OWNER" != "$RUN_USER" ]]; then
  log "Files written by the KiCad container are not owned by the calling user."
  exit 1
fi

echo "$SHIM"
