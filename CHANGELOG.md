# Changelog

All notable changes to this module are documented in this file.

The format is inspired by Keep a Changelog, and this project follows semantic versioning for module tags (`module-v#.#.#`).

## [Unreleased]

### Added
- Added `gerber.additional_files` config support to copy extra files into the Gerber ZIP root.
- Added installed-version metadata and a local `check_release_automation_update.py` helper to query the latest module release.
- Added module smoke-test workflow for installer idempotency and local CLI dry-run validation.
- Added module release workflow for tagged module packaging and published checksums.
- Added uninstall helper script to remove managed files from target repositories.
- Added documentation for local pre-release validation and manual target upgrade policy.
- Added managed-file verification mode (`--verify`) in `check_release_automation_update.py`.
- Added multi-project configuration support via `projects[]` and `defaults.gerber`.
- Added project selection support in `generate_release_artifacts.py` via repeatable `--project-id`.
- Added targeted release-tag support in workflow template (`r/<project-id>/#.#.#`).

### Changed
- Clarified module vs target release tag conventions.
- Expanded installer metadata to schema v2 with managed-file versions and SHA256 checksums.
- Updated workflow packaging to emit one Gerber ZIP per selected project in multi-project mode.
- Kept plain `r#.#.#` tags in legacy single-project mode only when `project.path` config is used.

### Fixed
- Fixed mixed-platform path handling so Windows drive-letter paths work under WSL for configured project/additional file paths.

## [1.0.0] - 2026-08-10

### Added
- Initial reusable install/update workflow template for target KiCad projects.
- `generate_release_artifacts.py` entrypoint for Gerber and drill generation.
- Example `release-artifacts.json` configuration template.
