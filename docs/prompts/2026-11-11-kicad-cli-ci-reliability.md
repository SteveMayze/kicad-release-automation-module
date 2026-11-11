# Phased prompt: reliable KiCad CLI in the target release workflow

Date: 2026-11-11
Applies to: `kicad-release-automation-module` (source of truth) and installed targets
(first target: a two-project KiCad repository, referred to below as "the target";
its projects are referred to as `board-a` and `board-b`).

How to use this file: give the AI assistant the "Shared context" section plus ONE phase
at a time. Do not start a phase until the previous phase's acceptance checks pass.
Each phase is one commit (or one small PR) in the module repository.

---

## Shared context (include with every phase)

### What the module does

`install.sh` copies four managed files into a target KiCad repository:

- `.github/workflows/release-gerbers.yml` (from `templates/`)
- `scripts/generate_release_artifacts.py`
- `scripts/check_release_automation_update.py`
- `scripts/find_kicad_cli.py`

and records them (version + SHA256) in `.kicad-release-automation-version.json`.
`release-artifacts.json` in the target is user-owned and preserved on reinstall.
Multi-project support (`projects[]`, `defaults.gerber`, `--project-id`, tag
`r/<project-id>/#.#.#`) was merged in PR #1.

### The failure

Target workflow, step "Install KiCad CLI from official stable binary":

```
Downloading KiCad stable binary from .../kicad-10.0.8-x86_64.AppImage.tar
kicad-cli not found in downloaded KiCad bundle.
```

### Root causes (established by review, 2026-11-11)

1. The `.AppImage.tar` is a tar wrapper around a single `.AppImage` file. It is not an
   unpacked KiCad tree, so `find -name kicad-cli` can never match. In addition
   `tar --strip-components=1` discards a single top-level member, so `/tmp/kicad` is
   probably empty. (Tar layout taken from mirror listings and third-party reports; the
   download host was not reachable from the review environment. Not a blocker because
   this approach is being dropped.)
2. Even with that fixed, the NEXT step ("Resolve kicad-cli path") only looks on `PATH`
   and would fail with "kicad-cli executable not found after installation", then
   overwrite `KICAD_CLI`. The two steps contradict each other.
3. The earlier apt-based attempts were a dead end for a different reason than the one
   in the workflow comments: the `board-a` PCB is KiCad 10 format
   (`generator_version "10.0"`), the `board-b` PCB is KiCad 9 format.
   The Ubuntu archive `kicad` package on `ubuntu-latest` is far older and cannot open
   either board. Any solution must provide KiCad >= 10.0.
4. The HTML scrape of `downloads.kicad.org/.../explore/stable` takes the first regex
   match. Nothing guarantees it is the newest, non-rc, non-lite, x86_64 build
   (the `grep: write error: Broken pipe` line is a symptom of that pipeline).
5. The module smoke test only runs `--dry-run`. No module CI job ever executes a real
   `kicad-cli` or the install step of the template. That is why the module is green
   while the target is red, and why every fix had to be discovered by pushing to the
   target.

### Latent defects found in the same workflow (not yet hit)

- Packaging zips EVERY directory under `gerber/`. The target has a committed
  `gerber/<board-a>/`, so a release of only `board-b` would
  also publish a ZIP of stale, not-regenerated `board-a` Gerbers. A committed
  subdirectory would also push a legacy single-project repo into the multi-project
  branch.
- `generate_release_artifacts.py --dry-run` still rewrites `text_variables.RELEASE` in
  the `.kicad_pro` and creates output directories.
- `${{ inputs.* }}` values are interpolated directly into bash (`run:` blocks). Pass
  them through `env:` instead.
- There is no way to exercise the workflow without publishing a GitHub Release.
- `README.md` still says target CI installs the Ubuntu KiCad package.

### Chosen direction

Run `kicad-cli` from the official KiCad container image (`kicad/kicad`, published by
the KiCad project specifically for `kicad-cli` in CI; `major.minor` tags such as
`10.0` track the latest patch release, `major.minor.patch` tags are fixed).

Use a SHIM, not a job-level `container:`:

- The job keeps running on `ubuntu-latest`, so checkout, Python, `zip`, artifact
  upload and the release action behave exactly as today.
- A small executable named `kicad-cli` is written to a temp bin directory. It does
  `docker run` on the KiCad image with the workspace mounted at the SAME absolute
  path, so the absolute paths that `generate_release_artifacts.py` already passes
  work unchanged. `KICAD_CLI` and `PATH` point at the shim.
- The Python generator stays the single entrypoint and needs no knowledge of Docker.

Reasons: no HTML scraping, no apt/PPA/Launchpad, no AppImage/FUSE, version is an
explicit tag, and the same shim runs locally and in module CI.

Rejected: apt archive (too old), Launchpad PPAs (the original flakiness), AppImage
(scrape + extract + bundled library environment; keep only as a documented manual
fallback), job-level `container:` (image runs as a non-root user and its tool set is
not under our control).

### Ground rules for the assistant

- Change files in the MODULE repo only. Never hand-edit managed files in a target;
  targets are updated by re-running `install.sh`.
- One phase per commit. Do not refactor unrelated code. Do not touch the WSL/Windows
  path handling in `generate_release_artifacts.py`.
- Keep LF line endings (`.gitattributes` enforces this).
- Before proposing a fix for a CI failure, quote the failing log line and state the
  cause. If a fact cannot be verified (image contents, tag existence), say so and add
  a diagnostic command instead of guessing.
- Stop and report after each phase with: files changed, how each acceptance check was
  verified, anything not verified.

---

## Phase 1 - Replace the KiCad install with the container shim

Goal: the target workflow reaches "Generate Gerber and drill files" with a working
KiCad 10 CLI. Smallest possible change.

Tasks, all in `templates/.github/workflows/release-gerbers.yml`:

1. Add a workflow-level `env:` with `KICAD_IMAGE: kicad/kicad:10.0`.
2. Delete both existing steps "Install KiCad CLI from official stable binary" and
   "Resolve kicad-cli path". Replace them with ONE step "Set up KiCad CLI (container)":
   - `docker pull` the image with up to 3 attempts and a growing sleep; fail clearly
     if all attempts fail.
   - Create `$RUNNER_TEMP/kicad-bin/kicad-cli` (executable) that runs:
     `docker run --rm --user "$(id -u):$(id -g)" -e HOME=<writable temp home>`
     `-v <temp home>:<temp home> -v "$GITHUB_WORKSPACE:$GITHUB_WORKSPACE" -w "$PWD"`
     `"$KICAD_IMAGE" kicad-cli "$@"`.
     Bake the resolved image name, workspace path and temp home into the shim when it
     is generated; `$PWD` and `"$@"` must be evaluated when the shim runs.
   - Append the bin directory to `$GITHUB_PATH` and write `KICAD_CLI=<shim path>` to
     `$GITHUB_ENV`.
   - Run the shim with `--version` and fail if the output is empty.
3. Leave every other step unchanged in this phase.

Verify before relying on it (report results):

- The image has no entrypoint that swallows the `kicad-cli` argument
  (`docker inspect --format '{{json .Config.Entrypoint}} {{json .Config.Cmd}}'`).
- `kicad-cli` can write its config when run with the runner's uid and the temp HOME.
- A file written by the container into the workspace is owned by the runner user.

Acceptance checks:

- `actionlint` (or at minimum a YAML parse) passes on the template.
- In the module smoke test, the managed workflow SHA assertions still pass.
- After `./install.sh <target>` and a push to the target's default branch, a
  `workflow_dispatch` run with `release_tag=r/<project-id>/0.0.1` gets past
  "Generate Gerber and drill files" and the log shows a `10.0.x` version line.
  (This run publishes a release for that tag; delete it afterwards, or do Phase 2
  first if that is not acceptable.)

---

## Phase 2 - Make packaging correct and the workflow testable

Goal: ZIPs contain only what this run generated; the workflow can be exercised
without publishing.

Tasks:

1. `scripts/generate_release_artifacts.py`
   - `--dry-run` must not modify any `.kicad_pro` and must not create directories.
   - After a successful run, write a manifest JSON (default
     `<output-dir>/release-manifest.json`, overridable with `--manifest`) listing, per
     generated project: `id`, `project_file`, `output_dir`, and the release value.
   - Add a preflight that reads `generator_version` from each selected `.kicad_pcb`
     and compares its major version with `kicad-cli --version`. If the CLI is older
     than the board, fail with a message naming the board, both versions, and
     `KICAD_IMAGE`. Skip the check in `--dry-run` when no CLI is available.
2. Template workflow
   - Generate into a clean directory outside the tracked tree
     (`--output-dir "$RUNNER_TEMP/release-out"` does NOT work with the shim because
     only the workspace is mounted; use a workspace-relative path such as
     `.release-out/` and remove it at the start of the step).
   - Package from the manifest, not from `find gerber`. One ZIP per manifest entry,
     named `<project-id>-gerber-<release-label>.zip`. Remove the separate legacy
     branch; the manifest covers single-project mode too. Keep the legacy ZIP name
     identical to today's for single-project repos.
   - Add `workflow_dispatch` input `dry_run` (boolean, default `false`). When true:
     upload the workflow artifact but skip "Attach ZIPs to release".
   - Move every `${{ inputs.* }}`, `${{ github.ref_name }}` and step-output use inside
     `run:` blocks to `env:` variables.
   - Optional per-target override that survives reinstall: if `release-artifacts.json`
     contains `"kicad": {"image": "..."}`, use it instead of the default
     `KICAD_IMAGE`. Document it in `examples/release-artifacts.json` and the README.
3. Update the module smoke test for the changed dry-run behaviour and the manifest.

Acceptance checks:

- Smoke test green.
- Local: in a repo with a committed `gerber/<other-project>/` directory, a selective
  run produces exactly one ZIP and no ZIP for the unselected project.
- Local: `git status` is clean after a `--dry-run` with `--release` set.
- Target: `workflow_dispatch` with `release_tag=r/<project-id>/0.0.1`,
  `dry_run=true` succeeds, uploads one ZIP, creates no release.
- Target: same with `project_ids` empty and a plain `r0.0.1` tag still fails with the
  existing "Legacy plain tag mode is not allowed" message.

---

## Phase 3 - Module CI that runs a real kicad-cli

Goal: this class of failure is caught in a module PR, not in a target.

Tasks:

1. Move the shim creation into a managed script, `scripts/setup_kicad_cli_container.sh`
   (arguments: image, bin dir; prints the shim path). The template workflow calls the
   script instead of inlining it. Register the new managed file everywhere the other
   three scripts are registered: `install.sh` (copy + metadata), `uninstall.sh`,
   `check_release_automation_update.py --verify`, the smoke-test assertions
   (including the managed-file count), README file lists.
2. Add fixture boards under `tests/fixtures/` that a real KiCad 10 CLI can plot: one
   minimal two-layer board saved by KiCad 10, and one saved by KiCad 9 (to prove the
   mixed-version case from the first target). Keep them tiny; no 3D models.
3. Add job `e2e-real-kicad` to `.github/workflows/module-smoke-test.yml`:
   - `./install.sh` into a temp directory that is a git repo containing the fixtures
     and a two-project `release-artifacts.json`.
   - Run `scripts/setup_kicad_cli_container.sh`, then
     `generate_release_artifacts.py --release 0.0.1 --project-id <one id>`.
   - Assert: Gerber files for each configured layer and a drill file exist for the
     selected project, nothing exists for the unselected project, the manifest is
     correct, files are owned by the runner user.
   - Run the same packaging commands the template uses (extract them into a script or
     a composite step if needed so the test and the template cannot drift).
4. Add `actionlint` over `.github/workflows/*.yml` and
   `templates/.github/workflows/*.yml` to the smoke test.

Acceptance checks:

- The new job fails if `KICAD_IMAGE` is set to an image without `kicad-cli`
  (demonstrate once, then revert).
- Full module smoke test green on a PR.

---

## Phase 4 - Docs, release, roll out to the target

Tasks:

1. `README.md`: replace the "installs the Ubuntu KiCad package" note with the
   container approach; document `KICAD_IMAGE`, the optional config override, the
   `dry_run` input, running the shim locally, and the rule that tag-triggered runs use
   the workflow file from the tagged commit (so fixes are tested with
   `workflow_dispatch`, not by re-pushing a tag).
2. `install.sh`: fix the closing hint so it mentions `projects[]` as well as
   `project.path`.
3. `CHANGELOG.md`: move Unreleased into a new version; note the breaking points
   (new managed file, output directory, manifest).
4. `PROJECT_TRACKING.md`: tick/add items.
5. Tag a module release from a CLEAN tree (the target currently records
   a `-dirty` module version).
6. Target rollout: run `install.sh` from the tagged module,
   `check_release_automation_update.py --verify`, commit, then
   `workflow_dispatch` with `dry_run=true` for each project id, then one real tag
   `r/<project-id>/#.#.#`.
7. Target cleanup (ask the owner first): the committed `gerber/` directory is no
   longer read by the workflow; decide whether to keep it as a manual export or
   remove and ignore it.

Acceptance checks:

- `--verify` reports all managed files matching in the target.
- One real tagged release per project, each with exactly one ZIP whose contents were
  opened and checked (layer files + drill file present, sizes non-zero).

---

## Phase 5 (optional, only if needed)

- Registry resilience: if Docker Hub pulls are ever rate-limited, add a second
  attempt against the KiCad GHCR mirror. Confirm the exact tag names on the mirror
  first; they may differ from Docker Hub (arch-suffixed tags were seen).
- Reproducibility: allow pinning `KICAD_IMAGE` by digest in `release-artifacts.json`.
- Central fixes without reinstall: turn the template into a thin caller of a reusable
  workflow (`workflow_call`) hosted in the module repo. Only viable if the module repo
  is public or shared with the targets; changes the upgrade model, so decide
  deliberately.
