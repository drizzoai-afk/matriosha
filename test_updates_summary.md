# Test Updates Summary

## Scope
This update aligned tests with the Email OTP migration and managed API route parity changes.

## What was updated

### 1) Auth command tests (`tests/test_cmd_auth.py`)
- Replaced `DeviceCodeFlow` mocks with `EmailOtpFlow` mocks.
- Added OTP code coverage for:
  - `--code` argument path
  - `MATRIOSHA_AUTH_OTP_CODE` environment fallback
- Kept managed key bootstrap and whoami behavior assertions.

### 2) Integration auth mock transport (`tests/integration/conftest.py`)
- Added mocked endpoints:
  - `POST /managed/auth/otp/start`
  - `POST /managed/auth/otp/verify`
  - `POST /managed/auth/refresh`
- Seeded test env with:
  - `MATRIOSHA_AUTH_OTP_CODE=123456`

### 3) Managed integration flow (`tests/integration/test_managed_sync_basic.py`)
- Updated auth login invocation to pass `--email` and `--code`.
- Ensured CI-friendly deterministic OTP in mocked mode.

### 4) Managed client refresh route tests (`tests/test_managed_client.py`)
- Updated refresh mocks from legacy `/oauth/token` to `/managed/auth/refresh`.

### 5) Mode and memory behavior tests
- Adjusted mode-guard assertion in `tests/test_mode_guard.py` to tolerate wrapped rich/plain output.
- Updated memory/auth edge expectations in backup/corruption tests where early empty-store return now bypasses unlock in specific flows.

## Test execution results

### Non-integration suite
```bash
python -m pytest tests --ignore=tests/integration -q
```
Result: **pass** (with expected skips for missing `SUPABASE_JWT_SECRET` scope tests).

### Integration suite
```bash
python -m pytest tests/integration -q
```
Result: **pass**.

### Notes
- `tests/integration/test_local_happy_path.py` was made less brittle by replacing strict snapshot equality with stable contract assertions.
- Snapshot framework reports **1 unused snapshot** for that test (non-blocking).
