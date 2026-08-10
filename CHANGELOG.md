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

### Changed
- Clarified module vs target release tag conventions.

## [1.0.0] - 2026-08-10

### Added
- Initial reusable install/update workflow template for target KiCad projects.
- `generate_release_artifacts.py` entrypoint for Gerber and drill generation.
- Example `release-artifacts.json` configuration template.
