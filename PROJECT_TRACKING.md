# PROJECT_TRACKING

## Objective

Provide reusable KiCad release automation as a standalone module repository.

## Scope (current)

- [x] Keep module repository non-actionable by default.
- [x] Store workflow under template path.
- [x] Include install script for target repositories.
- [x] Include reusable artifact-generation script.
- [x] Include example release configuration JSON.

## Scope (next)

- [ ] Add uninstall helper script.
- [ ] Add workflow smoke-test instructions.
- [ ] Add optional DRC/ERC gate examples.
- [ ] Add versioned changelog for template updates.

## Notes

- Target project owns final `.github/workflows/release-gerbers.yml`.
- Target project should review `release-artifacts.json` before first tag release.
