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
- `examples/release-artifacts.json`
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
	--project-id ZAM-AdventStar-SixPoint \
	--release 0.0.0 \
	--dry-run \
	--no-update-release-variable

# Compatibility shorthand: project-id/semver is also accepted
python3 scripts/generate_release_artifacts.py \
	--config release-artifacts.json \
	--release ZAM-AdventStar-SixPoint/0.0.0 \
	--dry-run \
	--no-update-release-variable
```

Recommended validation sequence:

1. Re-run `install.sh` from the desired module version in this repository.
2. Run the dry-run command above in the target repository.
3. If dry-run output is correct, run a non-dry-run execution locally (requires `kicad-cli`) or push a release tag and let CI generate deliverables.

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

Example:

```json
{
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
      "id": "atmega1608-dev",
      "path": "kicad/ATMega1608_Dev/ATMega1608_Dev.kicad_pro"
    },
    {
      "id": "lps-power-2",
      "path": "kicad/lps-power-4-layer/lps-power-2.kicad_pro",
      "gerber": {
        "additional_files": [
          "fab/lps-power-2-note.txt"
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

## Release behavior in target project

Tag conventions:

- Legacy single-project release tag: `r#.#.#` (example: `r1.3.1`)
- Targeted multi-project release tag: `r/<project-id>/#.#.#` (example: `r/atmega1608-dev/1.3.1`)
- Manual runs can also use `workflow_dispatch` input `project_ids` (comma-separated).

Behavior:

- Plain `r#.#.#` tags are valid only for legacy single-project config (`project.path`).
- Multi-project config must use targeted tag format or workflow_dispatch `project_ids`.
- Each selected project produces a ZIP named `<project-id>-gerber-r#.#.#.zip`.
- In multi-project mode, each project exports into its own output folder under `gerber/<project-id>/`.

## Notes

- Target project CI installs the Ubuntu KiCad package instead of the Launchpad nightly PPA because the Launchpad PPA is unreliable in hosted GitHub Actions runners.
- Tag-triggered target workflows run from the workflow file in the tagged commit.

## Module versioning and releases

- Module releases use tags in `module-v#.#.#` format.
- Target KiCad project releases use `r#.#.#` (legacy single-project) or `r/<project-id>/#.#.#` (targeted multi-project).
- Target projects update manually by checking out/pulling the desired module version, then re-running `install.sh`.
- Target projects can query the latest available module release locally with `scripts/check_release_automation_update.py`.
- Automatic target-repo upgrade bots are intentionally out of scope for now.

## Module repository workflows

- `.github/workflows/module-smoke-test.yml`: validates installer and CLI behavior in non-interactive test scenarios.
- `.github/workflows/module-release.yml`: publishes module release archives/checksums from `module-v#.#.#` tags.
