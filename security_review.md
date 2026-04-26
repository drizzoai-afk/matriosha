# Security Review (Managed Auth/Billing/CLI Parity)

## Summary
A targeted hardening pass was completed across managed auth, API middleware, and CLI error handling.

## Findings and changes

### 1) OTP abuse protection
**Risk:** Unbounded OTP start/verify calls enable brute-force and spam.

**Mitigation implemented:**
- Added in-memory rate limiting in `src/matriosha/api.py`:
  - per-email and per-IP buckets
  - configurable windows/limits
  - HTTP 429 with `Retry-After`
- New env controls:
  - `OTP_RATE_LIMIT_WINDOW_SECONDS`
  - `OTP_RATE_LIMIT_START_MAX`
  - `OTP_RATE_LIMIT_VERIFY_MAX`

### 2) CORS hardening
**Risk:** Overly broad CORS policy increases attack surface for browser-based token misuse.

**Mitigation implemented:**
- Added explicit `CORSMiddleware` allowlist in `src/matriosha/api.py`.
- Default allowlist is constrained; override via `CORS_ALLOWED_ORIGINS`.
- Restricted methods and headers to required set.

### 3) Backend error propagation (CLI)
**Risk:** Generic errors hide actionable details; raw tracebacks could leak internals.

**Mitigation implemented:**
- Managed client now extracts safe backend message fields (`detail`, `message`, etc.) and surfaces user-safe messages in structured `StoreError` without dumping traceback data.
- Debug hints include endpoint/status context, not sensitive secrets.

### 4) Managed auth route parity + logout support
**Risk:** Route drift causes fallback/legacy behavior and potential unsafe operational confusion.

**Mitigation implemented:**
- Added/validated managed auth routes:
  - `/managed/auth/refresh`
  - `/managed/auth/logout`
- Added explicit route check during verification.

### 5) Admin token guard and secret endpoints
**Risk:** Administrative/health diagnostics can leak operational details if overly exposed.

**Status:**
- Admin-token dependency remains in place where used.
- Health/dependency endpoints should remain protected at ingress/network layer for production; treat `/health/*` endpoints as operational.

## Residual risks
- OTP rate limits are process-local memory (suitable for single-process/small deployments). For horizontally scaled deployments, use shared storage (Redis) for global enforcement.
- Ensure production ingress denies direct public access to sensitive operational endpoints unless explicitly required.

## Recommended follow-ups
1. Move OTP rate limiter state to Redis for multi-instance consistency.
2. Add explicit auth/role gates for any health endpoint that can reveal dependency state.
3. Add structured security tests for 429 behavior and CORS origin checks.
