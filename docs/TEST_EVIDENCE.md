# Test Evidence Manifest (P7.1c)

This manifest maps visual verification scenarios to deterministic screenshot artifacts.

## Visual Scenario Evidence Matrix

| Scenario file | Modes | State | Screenshot evidence |
|---|---|---|---|
| `tests/integration/visual_scenarios/status_overview.toml` | `local`, `managed` | `warning` | `artifacts/screenshots/status_overview__local__warning.png`, `artifacts/screenshots/status_overview__managed__warning.png` |
| `tests/integration/visual_scenarios/remember_success.toml` | `local` | `success` | `artifacts/screenshots/remember_store__local__success.png` |
| `tests/integration/visual_scenarios/remember_error.toml` | `local` | `error` | `artifacts/screenshots/remember_invalid__local__error.png` |
| `tests/integration/visual_scenarios/vault_sync_progress.toml` | `managed` | `progress` | `artifacts/screenshots/vault_sync__managed__progress.png` |
| `tests/integration/visual_scenarios/auth_whoami_managed.toml` | `managed` | `success` | `artifacts/screenshots/auth_whoami__managed__success.png` |

## Verification Checklist

- [x] Deterministic screenshot captured for every visual scenario file
- [x] Parity-critical flows include both local and managed screenshots
- [x] Pixel-perfect visual regression tests are enabled in CI

## Textual TUI Preview Set (Redesign)

Generated via `scripts/generate_tui_screenshots.py`:

- `artifacts/screenshots/tui/zero_arg_launcher_home.png`
- `artifacts/screenshots/tui/command_catalog_all_commands.png`
- `artifacts/screenshots/tui/local_mode_state.png`
- `artifacts/screenshots/tui/managed_mode_state.png`
- `artifacts/screenshots/tui/boot_welcome.png`
- `artifacts/screenshots/tui/status_diagnostics.png`
- `artifacts/screenshots/tui/activity_progress.png`
- `artifacts/screenshots/tui/success_state.png`
- `artifacts/screenshots/tui/error_state.png`
- `artifacts/screenshots/tui/quota_warning_state.png`
- `artifacts/screenshots/tui/narrow_terminal_fallback.png`

## Commands

```bash
# regenerate/update screenshots from current CLI output
MATRIOSHA_UPDATE_VISUAL_BASELINE=1 pytest tests/integration/test_visual_verification.py

# generate Textual redesign previews
PYTHONPATH=. python scripts/generate_tui_screenshots.py

# enforce manifest + screenshot completeness gate
python scripts/verify_test_evidence.py
```

## Semantic interpreter support

Matriosha recall returns bounded agent-ready semantic JSON.

Rich built-in extraction currently supports:

- `.txt`
- `.md`, `.markdown`
- `.json`
- `.csv`, `.tsv`
- `.pdf`
- `.png`, `.jpg`, `.jpeg`, `.bmp`, `.gif`, `.webp`, `.tiff`, `.tif`
- `.docx`
- `.xlsx`

Legacy or proprietary formats such as `.doc`, `.odt`, `.xls`, `.msg`, `.dwg`, and archives such as `.zip`, `.tar`, `.gz` are handled as safe binary fallback envelopes unless a dedicated decoder plugin is installed.

Fallback envelopes are still valid interpreter output. They preserve safe metadata, bounded previews, and warnings, but they do not claim full text/table extraction.
