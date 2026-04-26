# Managed Backend Deployment Guide (Email OTP + Billing)

## 1) Required environment variables
Set these in the runtime (Cloud Run / container env):

### Supabase
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_ANON_KEY`

### Stripe
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_PRICE_ID_BASE`
- `STRIPE_SUCCESS_URL`
- `STRIPE_CANCEL_URL`

### Admin / app
- `ADMIN_TOKEN` (used by admin-guarded endpoints)

### Security hardening knobs (optional, now supported)
- `CORS_ALLOWED_ORIGINS` (comma-separated)
- `OTP_RATE_LIMIT_WINDOW_SECONDS` (default: `300`)
- `OTP_RATE_LIMIT_START_MAX` (default: `6`)
- `OTP_RATE_LIMIT_VERIFY_MAX` (default: `10`)

## 2) Deploy API
Example local run:

```bash
uvicorn matriosha.api:app --host 0.0.0.0 --port 8000
```

Then verify:
- `POST /managed/auth/otp/start`
- `POST /managed/auth/otp/verify`
- `POST /managed/auth/refresh`
- `POST /managed/auth/logout`
- `GET /managed/whoami`
- `POST /managed/billing/checkout`
- `GET /managed/billing/status`
- `POST /managed/billing/portal`
- `POST /managed/subscription/cancel`

## 3) CLI compatibility checks
From the CLI side, verify:

```bash
matriosha auth login --email <email> --code <otp> --json
matriosha auth whoami --json
matriosha auth status --json
matriosha auth refresh --json
matriosha billing status --json
matriosha billing cancel --json
```

## 4) Stripe webhook wiring
- Point Stripe webhook endpoint to `/webhooks/stripe`
- Configure `STRIPE_WEBHOOK_SECRET`
- Ensure webhook events include subscription/invoice lifecycle events used by entitlement sync

## 5) Post-deploy smoke tests
1. Start OTP for test user
2. Verify OTP and obtain tokens
3. Run `whoami`
4. Create checkout session
5. Query billing status
6. Open billing portal session
7. Cancel subscription and verify effective date in response
