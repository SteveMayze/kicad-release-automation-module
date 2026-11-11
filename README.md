# KiCad Release Automation Module

Reusable GitHub Actions + script tooling for KiCad release artifact generation.

## Repository model

This repository serves two purposes:

- Distribute reusable workflow/script templates for target KiCad projects.
- Run module-only CI/release workflows to validate and publish this module.

Module workflows in this repository do not generate production Gerbers for this repository itself. Production Gerber generation runs in each target KiCad project after installation.

## Contents

- `templates/.github/workflows/release-gerbers.yml`
- `scripts/generate_release_artifacts.py`
- `scripts/check_release_automation_update.py`
- `scripts/find_kicad_cli.py`
- `scripts/setup_kicad_cli_container.sh`
- `scripts/package_release_artifacts.sh`
- `examples/release-artifacts.json`
- `tests/fixtures/` (small purpose-made boards used by module CI only; not installed into targets)
- `install.sh`

## Install into a KiCad project

From this module directory:

```bash
chmod +x install.sh
./install.sh /path/to/your/kicad-project-repo
```

This installs:

- `.github/workflows/release-gerbers.yml`
- `scripts/generate_release_artifacts.py`
- `scripts/check_release_automation_update.py`
- `scripts/find_kicad_cli.py`
- `scripts/setup_kicad_cli_container.sh` (creates the `kicad-cli` shim that runs the KiCad container image)
- `scripts/package_release_artifacts.sh` (builds one ZIP per project in the release manifest)
- `release-artifacts.json` (only if it does not already exist)
- `.kicad-release-automation-version.json`

If you run `install.sh` again on an existing target project, it performs an update:

- refreshes the managed workflow/script files to the latest versions from this module
- preserves your existing `release-artifacts.json` configuration

To remove installed files from a target project while keeping your local config, run:

```bash
chmod +x uninstall.sh
./uninstall.sh /path/to/your/kicad-project-repo
```

## Local pre-release validation

Before creating a target project release tag, run local checks in the target repository:

```bash
# Preferred explicit form for a selected project
python3 scripts/generate_release_artifacts.py \
	--config release-artifacts.json \
	--project-id board-a \
	--release 0.0.0 \
	--dry-run \
	--no-update-release-variable

# Compatibility shorthand: project-id/semver is also accepted
python3 scripts/generate_release_artifacts.py \
	--config release-artifacts.json \
	--release board-a/0.0.0 \
	--dry-run \
	--no-update-release-variable
```

Recommended validation sequence:

1. Re-run `install.sh` from the desired module version in this repository.
2. Run the dry-run command above in the target repository.
3. If dry-run output is correct, run a non-dry-run execution locally (requires `kicad-cli`, installed or through the container shim described in "KiCad CLI in target CI"), or run the workflow manually with `dry_run` enabled, before pushing a release tag.

## Locate KiCad CLI

If `kicad-cli` is not on your PATH, the quickest check is:

```bash
python3 scripts/find_kicad_cli.py
```

On WSL, this also scans the common Windows KiCad install paths under `/mnt/c/Program Files/...` and `/mnt/c/Program Files (x86)/...`.

To use the discovered path explicitly, export it before running the release script:

```bash
export KICAD_CLI="$(python3 scripts/find_kicad_cli.py)"
```

## Check for module updates

After installing into a target KiCad repository, you can check whether a newer module release exists:

```bash
python3 scripts/check_release_automation_update.py
```

The installer writes `.kicad-release-automation-version.json` into the target repository. The update-check script reads that metadata, queries the latest GitHub release for the module repository, and compares it with the installed version.

Useful options:

- `--repo owner/repo`: override the module repository slug when metadata is missing or you want to check a fork
- `--metadata path/to/.kicad-release-automation-version.json`: read a non-default metadata file
- `--verify`: verify managed scripts/workflow versions and SHA256 checksums against installed metadata
- `--json`: emit machine-readable output

Example output:

```text
Metadata file: /path/to/target/.kicad-release-automation-version.json
Module repository: owner/kicad-release-automation-module
Installed version: module-v1.2.0
Latest release: module-v1.3.0
Update available: yes
```

## Configure in target project

Edit `release-artifacts.json` in the target project:

- Legacy single-project mode (still supported):
  - `project.path`: path to the target `.kicad_pro`
  - `gerber.include_layers`: layers to export
  - `gerber.additional_files`: optional extra files copied into the root of the Gerber output directory and ZIP
- Multi-project mode:
  - `projects[]`: list of projects with `id` and `path`
  - `defaults.gerber`: shared Gerber config applied to each project unless overridden
  - `projects[].gerber`: per-project Gerber overrides
- Optional, both modes:
  - `kicad.image`: KiCad container image the release workflow uses for `kicad-cli`. Overrides the workflow default (`KICAD_IMAGE`, `kicad/kicad:10.0`) and survives reinstall because it lives in your config. Remove the `kicad` block to follow the module default. The image's KiCad major version must not be older than the version your boards were saved with.

Example:

```json
{
  "kicad": {
    "image": "kicad/kicad:10.0"
  },
  "defaults": {
    "gerber": {
      "include_layers": [
        "F.Cu",
        "In1.Cu",
        "In2.Cu",
        "B.Cu",
        "F.Paste",
        "B.Paste",
        "F.SilkS",
        "B.SilkS",
        "F.Mask",
        "B.Mask",
        "Edge.Cuts"
      ],
      "additional_files": []
    }
  },
  "projects": [
    {
      "id": "board-a",
      "path": "kicad/board-a/board-a.kicad_pro"
    },
    {
      "id": "board-b",
      "path": "kicad/board-b/board-b.kicad_pro",
      "gerber": {
        "additional_files": [
          "fab/board-b-note.txt"
        ]
      }
    }
  ]
}
```

`gerber.additional_files` behavior:

- paths may be relative to the repository root or absolute
- when running under WSL, Windows drive-letter paths (for example `D:\boards\demo.kicad_pro`) are accepted and converted to `/mnt/d/boards/demo.kicad_pro`
- UNC paths (`\\server\share\...`) are intentionally not supported; mount the share and use the mounted path
- each entry must resolve to an existing regular file
- files are copied into the Gerber output directory root using their basename
- two configured files cannot share the same basename, because both would target the same ZIP path
- in `--dry-run`, the script prints the intended copy operations without copying files

`--dry-run` never modifies a `.kicad_pro` file, creates directories or writes the manifest.

## Release manifest

After a successful (non-dry-run) run, `generate_release_artifacts.py` writes a manifest JSON listing what that run generated: per project the `id`, `project_file`, `output_dir` and `release` value (paths are relative to the repository root). It is written to `<output-dir>/release-manifest.json` unless `--manifest <path>` is given. The release workflow packages ZIPs from this manifest only.

Before exporting, the script compares the KiCad version each selected board was saved with (`generator_version` in the `.kicad_pcb`) with `kicad-cli --version` and stops if the CLI is older than the board.

## Release behavior in target project

Tag conventions:

- Legacy single-project release tag: `r#.#.#` (example: `r1.3.1`)
- Targeted multi-project release tag: `r/<project-id>/#.#.#` (example: `r/board-a/1.3.1`)
- Manual runs can also use `workflow_dispatch` input `project_ids` (comma-separated).
- Manual runs with `workflow_dispatch` input `dry_run` enabled build the ZIPs and upload them as a workflow artifact, but do not publish a GitHub Release.

Behavior:

- Plain `r#.#.#` tags are valid only for legacy single-project config (`project.path`).
- Multi-project config must use targeted tag format or workflow_dispatch `project_ids`.
- Each selected project produces a ZIP named `<project-id>-gerber-r#.#.#.zip`.
- The workflow generates into a clean `.release-out/` directory in the workspace and packages only what that run generated. A committed `gerber/` directory is not read and never ends up in a release ZIP.
- For local runs the default output directory is still `gerber/`; in multi-project mode each project exports into `gerber/<project-id>/`.

## KiCad CLI in target CI

The release workflow does not install KiCad on the runner. It runs `kicad-cli` from the official KiCad container image:

- The image is set by the workflow-level `KICAD_IMAGE` variable (default `kicad/kicad:10.0`; `major.minor` tags follow the latest patch release, `major.minor.patch` tags are fixed).
- To use a different image in one target without editing the managed workflow, set `kicad.image` in that target's `release-artifacts.json` (see "Configure in target project"). It survives reinstall.
- `scripts/setup_kicad_cli_container.sh <image> <bin-dir>` pulls the image and writes a `kicad-cli` shim into `<bin-dir>`. The shim runs the image as the calling user with the workspace mounted at the same absolute path, so the generator script needs no knowledge of Docker. The workflow puts the shim on `PATH` and in `KICAD_CLI`.
- The image must be at least as new as the KiCad version your boards were saved with; the generator stops with a clear message if it is not.

### Run the shim locally

With Docker available, the same shim works on a development machine. From the target repository root:

```bash
export KICAD_CLI="$(bash scripts/setup_kicad_cli_container.sh kicad/kicad:10.0 .release-out/kicad-bin)"

python3 scripts/generate_release_artifacts.py \
	--config release-artifacts.json \
	--project-id board-a \
	--release 0.0.0 \
	--no-update-release-variable \
	--output-dir .release-out/gerber \
	--manifest .release-out/release-manifest.json

bash scripts/package_release_artifacts.sh .release-out/release-manifest.json r0.0.0 .release-out
```

Only the directory the shim was created from (the current directory, or `KICAD_CLI_MOUNT_DIR`) is visible to `kicad-cli`, so project files and the output directory must be inside it. `.release-out/` is scratch output; do not commit it.

### Test the workflow without publishing

Run the workflow manually (`workflow_dispatch`) with `release_tag` set and `dry_run` enabled. The ZIPs are built and uploaded as a workflow artifact, and no GitHub Release is created.

## Notes

- Tag-triggered target workflows run from the workflow file in the tagged commit. Re-pushing or moving a tag does not pick up a later workflow fix, so test fixes with `workflow_dispatch` (with `dry_run` enabled) from the branch that contains them, then create a new tag.
- A committed `gerber/` directory in a target is not read by the workflow. Keep it only if you want a manually exported copy in the repository.

## Module versioning and releases

- Module releases use tags in `module-v#.#.#` format.
- Target KiCad project releases use `r#.#.#` (legacy single-project) or `r/<project-id>/#.#.#` (targeted multi-project).
- Target projects update manually by checking out/pulling the desired module version, then re-running `install.sh`.
- Target projects can query the latest available module release locally with `scripts/check_release_automation_update.py`.
- Automatic target-repo upgrade bots are intentionally out of scope for now.

## Module repository workflows

- `.github/workflows/module-smoke-test.yml`: lints the workflows with `actionlint`, validates installer and CLI behavior in non-interactive test scenarios, and (job `e2e-real-kicad`) installs the module into a fixture repository and generates and packages real Gerbers with `kicad-cli` from the KiCad container image. A manual run accepts a `kicad_image` input to test another image.
- `.github/workflows/module-release.yml`: publishes module release archives/checksums from `module-v#.#.#` tags.
