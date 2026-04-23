# BACKEND_SETUP

Production setup guide for Matriosha managed mode (Supabase + Stripe).

## 1) Required secrets and env vars

Set these in runtime (or Google Secret Manager with same names):

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `MATRIOSHA_VAULT_SERVER_PUBKEY` (optional; required for double-wrap path in `vault rotate`)
- `GCP_PROJECT_ID` and `GOOGLE_APPLICATION_CREDENTIALS` (for GSM lookup)

Resolution order in code is: **env var -> GSM -> fallback**.

## 2) Supabase bootstrap

1. Create a Supabase project.
2. In SQL editor run:
   - `core/managed/schema.sql`
   - verify extensions `vector`, `vault`, `pgsodium`
3. Ensure table `vault_keys` exists with RLS bound to `auth.uid()`.
4. Deploy edge function:

```bash
supabase functions deploy vault-custody --project-ref <project-ref>
```

5. Configure function secrets in Supabase:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`

## 3) Stripe setup

1. Create product/prices for managed plan (`eur_monthly`, quantity-backed).
2. Configure webhook endpoint to your managed backend:
   - events: `checkout.session.completed`, `invoice.paid`, `invoice.payment_failed`, `customer.subscription.updated`, `customer.subscription.deleted`
3. Copy webhook signing secret into `STRIPE_WEBHOOK_SECRET`.

## 4) Managed auth + key bootstrap flow

- `matriosha auth login` performs OAuth device flow.
- On success, CLI stores encrypted session tokens in local token store.
- CLI then runs managed key bootstrap automatically:
  - restore wrapped key from `vault_keys` if it exists; or
  - generate new `data_key`, wrap/upload, and write local vault material.

No user passphrase prompt is required in managed mode.

## 5) Operational checks

Run these after deploy:

```bash
matriosha --mode managed auth whoami --json
matriosha --mode managed billing status --json
matriosha --mode managed quota status --json
matriosha --mode managed token list --json
matriosha --mode managed vault sync --json
```

Expected:
- `auth.whoami` returns user identity
- billing/quota endpoints return active subscription/quota data
- token lifecycle works (generate/list/revoke/inspect)
- sync reports pushed/pulled counts without integrity errors

## 6) Localhost note

When running backend services on localhost inside the Abacus agent VM, that localhost is the VM localhost, not your personal machine.
