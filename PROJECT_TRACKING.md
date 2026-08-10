# PROJECT_TRACKING

## Objective

Provide reusable KiCad release automation as a standalone module repository.

## Scope (current)

- [x] Store workflow under template path.
- [x] Include install script for target repositories.
- [x] Include reusable artifact-generation script.
- [x] Include example release configuration JSON.
- [x] Preserve target `release-artifacts.json` on reinstall/update.

## Scope (next)

- [x] Add uninstall helper script.
- [x] Add local pre-release validation instructions.
- [x] Add module smoke-test workflow.
- [x] Add module release workflow.
- [x] Add versioned changelog for module updates.
- [ ] Add optional DRC/ERC gate examples.
- [ ] Add module release notes quality gates (breaking-change checklist).
- [ ] Add optional target update-check template workflow (PR-only, manual merge).

## Versioning

- Module tags: `module-v#.#.#`
- Target project release tags: `r#.#.#`
- Target repositories upgrade manually by re-running `install.sh` from the selected module version.

## Notes

- Target project owns final `.github/workflows/release-gerbers.yml`.
- Target project should review `release-artifacts.json` before first tag release.
- Module CI/release workflows are non-interactive by design.
