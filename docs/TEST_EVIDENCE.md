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

## Commands

```bash
# regenerate/update screenshots from current CLI output
MATRIOSHA_UPDATE_VISUAL_BASELINE=1 pytest tests/integration/test_visual_verification.py

# enforce manifest + screenshot completeness gate
python scripts/verify_test_evidence.py
```
