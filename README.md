# KiCad Release Automation Module

Reusable GitHub Actions + script tooling for KiCad release artifact generation.

## Why this repository has no active GitHub workflow

This repository is intentionally **non-actionable**:

- No active workflow exists at `.github/workflows/` in this repo.
- Workflow files are stored under `templates/.github/workflows/`.
- A target KiCad project installs the workflow explicitly using `install.sh`.

## Contents

- `templates/.github/workflows/release-gerbers.yml`
- `scripts/generate_release_artifacts.py`
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
- `release-artifacts.json` (only if it does not already exist)

If you run `install.sh` again on an existing target project, it performs an update:

- refreshes the managed workflow/script files to the latest versions from this module
- preserves your existing `release-artifacts.json` configuration

## Configure in target project

Edit `release-artifacts.json` in the target project:

- `project.path`: path to the target `.kicad_pro`
- `gerber.include_layers`: layers to export

## Release behavior in target project

For tag `r1.3.1` and project `MyBoard`, workflow output names are:

- ZIP: `MyBoard-gerber-r1.3.1.zip`
- Workflow artifact: `MyBoard-gerber-r1.3.1`

## Notes

- CI workflow installs KiCad nightly for newer board formats.
- Tag-triggered workflows run from the workflow file in the tagged commit.
