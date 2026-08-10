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

To remove installed files from a target project while keeping your local config, run:

```bash
chmod +x uninstall.sh
./uninstall.sh /path/to/your/kicad-project-repo
```

## Local pre-release validation

Before creating a target project release tag, run local checks in the target repository:

```bash
python3 scripts/generate_release_artifacts.py \
	--config release-artifacts.json \
	--release 0.0.0 \
	--dry-run \
	--no-update-release-variable
```

Recommended validation sequence:

1. Re-run `install.sh` from the desired module version in this repository.
2. Run the dry-run command above in the target repository.
3. If dry-run output is correct, run a non-dry-run execution locally (requires `kicad-cli`) or push a release tag and let CI generate deliverables.

## Configure in target project

Edit `release-artifacts.json` in the target project:

- `project.path`: path to the target `.kicad_pro`
- `gerber.include_layers`: layers to export
- `gerber.additional_files`: optional extra files copied into the root of the Gerber output directory and ZIP

Example:

```json
{
	"project": {
		"path": "kicad/ATMega1608_Dev/ATMega1608_Dev.kicad_pro"
	},
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
		"additional_files": [
			"fab/uv-silkscreen-front.png"
		]
	}
}
```

`gerber.additional_files` behavior:

- paths may be relative to the repository root or absolute
- each entry must resolve to an existing regular file
- files are copied into the Gerber output directory root using their basename
- two configured files cannot share the same basename, because both would target the same ZIP path
- in `--dry-run`, the script prints the intended copy operations without copying files

## Release behavior in target project

For tag `r1.3.1` and project `MyBoard`, workflow output names are:

- ZIP: `MyBoard-gerber-r1.3.1.zip`
- Workflow artifact: `MyBoard-gerber-r1.3.1`

## Notes

- Target project CI installs KiCad nightly for newer board formats.
- Tag-triggered target workflows run from the workflow file in the tagged commit.

## Module versioning and releases

- Module releases use tags in `module-v#.#.#` format.
- Target KiCad project releases remain `r#.#.#`.
- Target projects update manually by checking out/pulling the desired module version, then re-running `install.sh`.
- Automatic target-repo upgrade bots are intentionally out of scope for now.

## Module repository workflows

- `.github/workflows/module-smoke-test.yml`: validates installer and CLI behavior in non-interactive test scenarios.
- `.github/workflows/module-release.yml`: publishes module release archives/checksums from `module-v#.#.#` tags.
