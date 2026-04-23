# MANAGED_BOOTSTRAP

Operator bootstrap for Matriosha managed mode.

- Create a Supabase project for the managed environment.
- Open the SQL editor and execute the full schema from `core/managed/schema.sql`.
- Enable Vault extension and verify required extensions are available.
- Configure Stripe using Supabase native Stripe integration (2026 feature baseline). Use Supabase MCP documentation/workflows for exact integration primitives and webhook routing.
- Configure managed backend runtime secrets and environment variables.

## Copy-paste SQL (minimum bootstrap preflight)

```sql
create extension if not exists vector;
create extension if not exists vault;

-- sanity checks
select extname
from pg_extension
where extname in ('vector', 'vault')
order by extname;
```

## Full schema rollout

- Copy all SQL from `core/managed/schema.sql` into your SQL execution pipeline.
- Apply in one migration unit (schema + indexes + RLS policies).
- Validate owner-scoped access by testing with two different auth users.

## Managed runtime env + secrets contract

Set these environment variables for managed backend processes:

- `GCP_PROJECT_ID=982521900123`
- `GOOGLE_APPLICATION_CREDENTIALS=<path-to-service-account-json>`

Required secret names (resolved in this order: env var → GSM `projects/982521900123/secrets/{NAME}/versions/latest` → local fallback):

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_ANON_KEY`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`

## Stripe plan baseline

- Single plan code: `eur_monthly`
- Quota model: base pack enforcement with re-payment required when limits are hit
- Use quantity-backed subscription updates for incremental agent/storage packs
