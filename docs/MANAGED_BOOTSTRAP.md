# MANAGED_BOOTSTRAP

Operator bootstrap for Matriosha managed mode.

- Create a Supabase project for the managed environment.
- Open the SQL editor and execute the full schema from `core/managed/schema.sql`.
- Enable Vault + pgsodium extensions and verify required extensions are available.
- Deploy edge function `vault-custody` for managed wrapped-key custody.
- Configure managed backend runtime secrets and environment variables.

## Copy-paste SQL (minimum bootstrap preflight)

```sql
create extension if not exists vector;
create extension if not exists vault;
create extension if not exists pgsodium;

-- sanity checks
select extname
from pg_extension
where extname in ('vector', 'vault', 'pgsodium')
order by extname;
```

## Full schema rollout

- Copy all SQL from `core/managed/schema.sql` into your SQL execution pipeline.
- Apply in one migration unit (schema + indexes + RLS policies).
- Validate owner-scoped access by testing with two different auth users.

### `vault_keys` managed custody table

`vault_keys` is created by schema migration with:

- `user_id uuid primary key`
- `wrapped_key bytea`
- `kdf_salt bytea`
- `algo text default 'aes-gcm'`
- `rotated_at timestamptz`

RLS policies enforce `user_id = auth.uid()` for select/insert/update/delete.

## Edge function deployment (`supabase/functions/vault-custody`)

1. Ensure function secrets are configured in Supabase:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
2. Deploy function:
   ```bash
   supabase functions deploy vault-custody --project-ref <project-ref>
   ```
3. Verify function is reachable and authenticated calls succeed:
   - `action=upsert` stores wrapped key material into `vault_keys`
   - `action=fetch` retrieves wrapped key material
   - `action=seal` and `action=unseal` call pgsodium RPC

### Required pgsodium RPC functions

The edge function expects SQL RPC functions with these signatures:

- `vault_seal_box(plaintext_b64 text) returns text`
- `vault_open_box(sealed_b64 text) returns text`

These RPCs should use server-side pgsodium key custody and must not log plaintext.

## Supabase Storage bucket bootstrap (`vault`)

Managed mode requires a private Storage bucket named `vault` for simple backup blobs.

Required settings:
- Name: `vault`
- Visibility: private
- Object key convention:
  - main blob: `<memory_id>.bin.b64`
  - backup blob: `<memory_id>.bin.b64.backup`

Operational contract (simplified):
- Keep local payload as primary read path.
- Keep one backup blob for managed corruption recovery.
- Use backup blob only when Merkle verification reports corruption.
- SQL schema remains unchanged; this bucket is blob backup only.

Validation checks:
- Upload one test main object and one backup object from service-role context.
- Download both and verify SHA-256 equality with local source payloads.

## Managed runtime env + secrets contract

Set these environment variables for managed backend processes:

- `GCP_PROJECT_ID=982521900123`
- `GOOGLE_APPLICATION_CREDENTIALS=<path-to-service-account-json>`

Required secret names (resolved in this order: env var → GSM `projects/{GCP_PROJECT_ID}/secrets/{NAME}/versions/latest` → safe local fallback):

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_ANON_KEY`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `MATRIOSHA_VAULT_SERVER_PUBKEY` (managed custody key wrapping)

## Key rotation procedures

### KEK rotation only (default)

```bash
matriosha vault rotate --new-passphrase '<new>'
```

- Re-wraps vault `data_key` with a newly derived KEK.
- Memory ciphertext files stay unchanged (memories are encrypted with `data_key`).
- In managed mode, uploads new wrapped custody blob to `vault_keys` automatically.

### Full data-key rotation (bulk re-encryption)

```bash
matriosha vault rotate --rotate-data-key --confirm-bulk --new-passphrase '<new>'
```

- Generates a new `data_key`.
- Re-encrypts all local memory payloads using temp directory + atomic swap.
- Writes a structured JSON marker (`rotate.marker.json`) for crash-safe resume.
- In managed mode, uploads new wrapped key and pushes rotated payloads to managed storage.

## Stripe plan baseline

- Single plan code: `eur_monthly`
- Quota model: base pack enforcement with re-payment required when limits are hit
- Use quantity-backed subscription updates for incremental agent/storage packs
