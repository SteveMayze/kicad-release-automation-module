# CLAUDE.md

Guidance for AI assistants working in this repository.

## What this repository is

A module that installs KiCad release automation into other ("target") KiCad
repositories. `install.sh` copies the managed files (the workflow under
`templates/` and the scripts under `scripts/`) into a target and records them in
`.kicad-release-automation-version.json`. The target's `release-artifacts.json` is
owned by the target and is preserved on reinstall.

Phased work plans live in `docs/prompts/`. When asked to carry out a phase, read
the whole file first, do that phase only, and stop when its acceptance checks are
reported.

## Privacy: nothing identifying or private in tracked files

Applies to every tracked file, commit message, tag message, PR text and CI log
output produced from this repository.

- No personal data: real names, email addresses, usernames or account handles,
  phone numbers, postal addresses.
- No machine-specific paths (home directories, drive letters with personal folder
  names, WSL mount paths that reveal a user or folder layout). Use placeholders
  such as `<target-repo>` or `/path/to/target`.
- No host names, IP addresses, internal URLs or network details.
- No secrets of any kind: tokens, keys, passwords, cookies, registry credentials.
  Workflows use `${{ secrets.* }}` / `GITHUB_TOKEN` only.
- No names or contents of private target repositories or their boards. In docs,
  tests and examples use neutral names (`example/owner`, `board-a`, `demo`).
  Test fixtures must be purpose-made boards, never copies of real designs.
- Do not paste raw CI logs or command output into tracked files without removing
  the items above.
- Repository owner/URL values needed at runtime are resolved from git or from
  environment variables, as `install.sh` already does. Do not hardcode them.
- Scratch output, local notes and anything containing the items above goes in
  ignored locations (`.tmp*/`), never in a tracked path.
- Before every commit, read the staged diff (`git diff --cached`) specifically for
  these items. If something private is already tracked, stop and report it; do not
  rewrite history without being asked.

## Working rules

- Change files in this module repository only. Never hand-edit managed files in a
  target repository; targets are updated by re-running `install.sh`.
- One phase or one logical change per commit. Do not refactor unrelated code.
- Do not change the WSL/Windows path handling in
  `scripts/generate_release_artifacts.py` unless the task is about it.
- Line endings are LF for `.sh`, `.py`, `.yml`, `.yaml`, `.json`, `.md`
  (`.gitattributes`). Keep scripts ASCII.
- When a managed file is added, removed or renamed, update every place that lists
  them: `install.sh` (copy and metadata), `uninstall.sh`,
  `scripts/check_release_automation_update.py`, the smoke-test assertions
  (including the managed-file count) and the README.
- User-visible changes get a `CHANGELOG.md` entry under "Unreleased".
- Do not commit, push, tag, publish a release or trigger a workflow unless asked.
  Tag module releases only from a clean working tree.

## Diagnosing failures

- Quote the failing log line and state the cause before proposing a fix.
- If a fact cannot be verified (contents of a download or container image, whether
  a tag exists, behaviour of a hosted runner), say so and add a diagnostic command
  instead of guessing.
- A fix for a CI failure in a target is made in the template here, covered by a
  module test where possible, then rolled out with `install.sh`.
- Tag-triggered runs in a target use the workflow file from the tagged commit.
  Test fixes with `workflow_dispatch`, not by re-pushing a tag.

## Checks before reporting done

- `bash -n install.sh uninstall.sh`
- `python3 -m py_compile scripts/*.py`
- Workflow YAML parses (`actionlint` if available) for `.github/workflows/` and
  `templates/.github/workflows/`.
- Run the dry-run commands from `.github/workflows/module-smoke-test.yml` against a
  scratch target under `.tmp*/` when scripts or the installer changed.
- Report: files changed, how each check was verified, and anything not verified.
