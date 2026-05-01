# Changelog

All notable public changes to Matriosha are documented in this file.

## Unreleased

### Added
- Added local-first encrypted memory workflows for saving, recalling, searching, listing, deleting, compressing, and decompressing memories.
- Added grouped CLI command structure under `memory`, `vault`, `mode`, `profile`, `token`, `agent`, `auth`, `billing`, `doctor`, `status`, `audit`, `compress`, `delete`, and `quota`.
- Added local token and agent workflows for local-mode agent access.
- Added managed-mode profile support with explicit validation before switching modes.
- Added managed backup, sync, and vector-mode configuration paths.
- Added JSON output contracts for automation-friendly command usage.
- Added hash-chained audit event support for traceability.
- Added Architecture Decision Records under `docs/adr`.

### Changed
- Improved local/managed mode separation so managed-only behavior fails fast with clearer guidance.
- Improved local-mode defaults for `token list` and `agent list`.
- Improved vector diagnostics and local vector storage behavior.
- Improved startup reliability around optional vector/JAX dependencies.
- Updated public documentation for launch readiness.
- Simplified public documentation surface around `README.md`, `DESIGN.md`, `SECURITY.md`, `CHANGELOG.md`, and `docs`.

### Fixed
- Fixed managed mode switching so invalid or missing credentials do not mutate profile mode.
- Fixed token scope handling so write-capable tokens satisfy read access where appropriate.
- Fixed passphrase-sensitive tests by avoiding environment leakage in validation workflows.
- Fixed type-checking issues across API, CLI, local storage, managed sync, and tests.
- Fixed lint issues before launch validation.

### Removed
- Removed internal planning, setup, generated PDF, and prelaunch-only documentation from the public launch surface.
