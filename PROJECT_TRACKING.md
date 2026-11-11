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
- [x] Support multiple projects per repository (`projects[]`, targeted tags `r/<project-id>/#.#.#`).
- [x] Run `kicad-cli` from the official KiCad container image in target CI (shim, no runner install).
- [x] Package release ZIPs from a per-run manifest; add `dry_run` workflow input.
- [x] Exercise a real `kicad-cli` in module CI with KiCad 9 and KiCad 10 fixture boards; lint workflows with `actionlint`.
- [ ] Roll the container-based workflow out to installed targets and confirm one tagged release per project.
- [ ] Add optional DRC/ERC gate examples.
- [ ] Add module release notes quality gates (breaking-change checklist).
- [ ] Add optional target update-check template workflow (PR-only, manual merge).

## Versioning

- Module tags: `module-v#.#.#`
- Target project release tags: `r#.#.#` (single project) or `r/<project-id>/#.#.#` (multi-project)
- Target repositories upgrade manually by re-running `install.sh` from the selected module version.

## Notes

- Target project owns final `.github/workflows/release-gerbers.yml`.
- Target project should review `release-artifacts.json` before first tag release.
- Module CI/release workflows are non-interactive by design.
