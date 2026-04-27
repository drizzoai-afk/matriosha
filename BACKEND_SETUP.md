# Matriosha Backend Setup (Beginner-Friendly, April 2026 UI)

This guide is for people with **zero technical background**.

## Before You Start: `.env` for local dev vs GSM for production

Matriosha supports both local `.env` files and Google Secret Manager (GSM):

- **Local development (on your own machine):** use a local `.env` file.
- **Production/staging:** store secrets in **Google Secret Manager** (recommended).

### Quick local setup

```bash
cp .env.example .env
```

Then edit `.env` and replace example values.

- `.env.example` is the safe template committed to git.
- `.env` is your editable local file and should stay uncommitted.

### How to switch between local and production

- **Local mode:** keep values filled in `.env`.
- **Production mode:** keep secrets in GSM and provide `GCP_PROJECT_ID` + runtime IAM access.

> Tip: If you are unsure, start with `.env` locally, then move secrets to GSM when deploying.

You will do 4 things:
1. Create a Google Cloud project
2. Save all keys in Google Secret Manager (safe locker)
3. Create Supabase + Stripe
4. Run a simple verification check

---

## Section 1: Google Cloud + Secret Manager Setup

### Why are we doing this?
Your keys (passwords/API keys) should not live in plain text files.
Google Secret Manager (GSM) is a secure locker for those keys.

### Step 1.1 — Create a Google Cloud project

1. Open: https://console.cloud.google.com/
2. Top bar → click the project selector (usually says something like **"My First Project"**)
3. Click **"NEW PROJECT"**
4. Project name: `matriosha-prod` (or any name you like)
5. Click **"CREATE"**

**What you should see (screenshot description):**
- Top bar now shows your new project name.

---

### Step 1.2 — Install Google Cloud CLI (one-time)

If `gcloud` is already installed, skip this.

Official instructions:
https://cloud.google.com/sdk/docs/install

Then login:

```bash
gcloud auth login
gcloud auth application-default login
```

---

### Step 1.3 — Select your project and enable Secret Manager API

Copy-paste these commands:

```bash
# 1) Replace this with your project id (not project name)
export GCP_PROJECT_ID="YOUR_GCP_PROJECT_ID"

# 2) Set active project
gcloud config set project "$GCP_PROJECT_ID"

# 3) Enable Secret Manager API
gcloud services enable secretmanager.googleapis.com
```

**What you should see (screenshot description):**
- Secret Manager page shows no error and allows creating secrets.

---

### Step 1.4 — Create a credentials file for app access

```bash
# Create service account
gcloud iam service-accounts create matriosha-gsm-reader \
  --display-name="Matriosha GSM Reader"

# Grant read access to secrets
gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
  --member="serviceAccount:matriosha-gsm-reader@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# Create local folder for key
mkdir -p "$HOME/.config/gcp"

# Create key file
gcloud iam service-accounts keys create "$HOME/.config/gcp/matriosha-gsm-reader.json" \
  --iam-account="matriosha-gsm-reader@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

# Export variables Matriosha needs
export GCP_PROJECT_ID="$GCP_PROJECT_ID"
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.config/gcp/matriosha-gsm-reader.json"
```

---

### Step 1.5 — Create all required secrets in GSM

### Why are we doing this?
Matriosha now reads credentials from GSM first. This is safer than env files.

Create these secret names exactly:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_JWT_SECRET`
- `SUPABASE_PASSWORD`
- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_WEBHOOK_SECRET` (**this is commonly missing — add it**)
- `MATRIOSHA_VAULT_SERVER_PUBKEY` (optional now, recommended for advanced key-rotation flow)

Create empty placeholders first (safe):

```bash
for s in \
SUPABASE_URL SUPABASE_ANON_KEY SUPABASE_SERVICE_ROLE_KEY SUPABASE_JWT_SECRET SUPABASE_PASSWORD \
STRIPE_SECRET_KEY STRIPE_PUBLISHABLE_KEY STRIPE_WEBHOOK_SECRET MATRIOSHA_VAULT_SERVER_PUBKEY; do
  printf "placeholder" | gcloud secrets create "$s" --data-file=- 2>/dev/null || true
done
```

Later, you will replace placeholders with real values using:

```bash
# Example: update one secret value
printf "REAL_VALUE_HERE" | gcloud secrets versions add SECRET_NAME --data-file=-
```

---

## Section 2: Supabase Setup

### Why are we doing this?
Supabase is where Matriosha stores user profile data, memories, tokens, subscriptions, and vault key metadata.

### Step 2.1 — Create a Supabase project

1. Open: https://supabase.com/dashboard
2. Click **"New project"**
3. Fill project name + database password
4. Choose region closest to your users
5. Click **"Create new project"**

**What you should see (screenshot description):**
- Dashboard opens with left menu (Table Editor, SQL Editor, Edge Functions, Project Settings).

---

### Step 2.2 — Run the SQL schema (exact SQL to copy)

In Supabase:
1. Open **SQL Editor**
2. Click **New query**
3. Copy the exact SQL from this repository file:

```bash
cd <​repo-root>
cat core/managed/schema.sql
```

4. Paste everything into SQL Editor and click **Run**

> This is the exact schema Matriosha expects.

---

### Step 2.3 — Deploy edge function

```bash
cd <​repo-root>
supabase login
supabase link --project-ref YOUR_SUPABASE_PROJECT_REF
supabase functions deploy vault-custody
```

---

### Step 2.3b — Create Supabase Storage bucket for managed memory backups (semantic recall support)

This bucket enables seamless agent recall by guaranteeing backup availability for corruption recovery in managed mode.

1. In Supabase dashboard, open **Storage**.
2. Click **New bucket**.
3. Set:
   - Bucket name: `vault`
   - Visibility: **Private** (do not make public)
4. Save.

Managed backup object contract:
- Main blob: `<memory_id>.bin.b64`
- Backup blob: `<memory_id>.bin.b64.backup`
- Example backup key: `3fa85f64-5717-4562-b3fc-2c963f66afa6.bin.b64.backup`

Operational rules:
- After successful memory creation/write in managed mode, automatically create/update the backup blob.
- Use backup blob only when Merkle integrity verification reports corruption.
- Local mode does not auto-restore from managed backup; local recall should emit a warning when corruption is detected.
- Vault remains responsible for cryptographic key custody; this bucket stores encrypted file backup copies.

Recommended access model:
- CLI managed backend paths use service role credentials for upload/download.
- Do not expose direct anonymous read access to bucket objects.

Quick validation (Supabase CLI):

```bash
# List buckets and confirm `vault` exists
supabase storage ls
```

### Step 2.4 — Get Supabase credentials and store them in GSM

In Supabase Dashboard:
- **Project Settings → API**: copy
  - Project URL → `SUPABASE_URL`
  - anon/public key → `SUPABASE_ANON_KEY`
  - service_role key → `SUPABASE_SERVICE_ROLE_KEY`
- **Project Settings → Database**: copy database password → `SUPABASE_PASSWORD`
- **Project Settings → API (JWT section)**: copy JWT secret → `SUPABASE_JWT_SECRET`

Save all to GSM (copy-paste):

```bash
printf "SUPABASE_URL_VALUE" | gcloud secrets versions add SUPABASE_URL --data-file=-
printf "SUPABASE_ANON_KEY_VALUE" | gcloud secrets versions add SUPABASE_ANON_KEY --data-file=-
printf "SUPABASE_SERVICE_ROLE_KEY_VALUE" | gcloud secrets versions add SUPABASE_SERVICE_ROLE_KEY --data-file=-
printf "SUPABASE_PASSWORD_VALUE" | gcloud secrets versions add SUPABASE_PASSWORD --data-file=-
printf "SUPABASE_JWT_SECRET_VALUE" | gcloud secrets versions add SUPABASE_JWT_SECRET --data-file=-
```

---

## Section 3: Stripe Setup

### Why are we doing this?
Stripe handles payments, plans, upgrades, and cancellations.

### Step 3.1 — Create Stripe account

1. Open: https://dashboard.stripe.com/
2. Sign up / log in
3. Use **Test mode** first (toggle in the left panel)

---

### Step 3.2 — Create products + prices

1. Go to **Product catalog**
2. Click **Create product**
3. Create base plan product (monthly)
4. Create add-on product (monthly)
5. Keep IDs for your records

Recommended IDs in your own notes:
- `matriosha_base_3_agents_eur_900_monthly`
- `matriosha_addon_3_agents_eur_900_monthly`

---

### Step 3.3 — Create webhook endpoint

1. Stripe Dashboard → **Developers → Webhooks**
2. Click **Add endpoint**
3. Endpoint URL: your backend URL + webhook path
4. Select these events:
   - `checkout.session.completed`
   - `invoice.paid`
   - `invoice.payment_failed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
5. Save endpoint
6. Copy **Signing secret** (starts with `whsec_...`) → this is `STRIPE_WEBHOOK_SECRET`

---

### Step 3.4 — Get Stripe keys and store them in GSM

From Stripe **Developers → API keys**:
- Secret key (`sk_...`) → `STRIPE_SECRET_KEY`
- Publishable key (`pk_...`) → `STRIPE_PUBLISHABLE_KEY`

From Stripe webhook endpoint details:
- Signing secret (`whsec_...`) → `STRIPE_WEBHOOK_SECRET`

Save to GSM:

```bash
printf "STRIPE_SECRET_KEY_VALUE" | gcloud secrets versions add STRIPE_SECRET_KEY --data-file=-
printf "STRIPE_PUBLISHABLE_KEY_VALUE" | gcloud secrets versions add STRIPE_PUBLISHABLE_KEY --data-file=-
printf "STRIPE_WEBHOOK_SECRET_VALUE" | gcloud secrets versions add STRIPE_WEBHOOK_SECRET --data-file=-
```

---

## Section 4: Matriosha Configuration + Validation

### Why are we doing this?
This confirms Matriosha can read secrets securely from GSM and connect to Supabase + Stripe.

### Step 4.1 — Minimal local environment

You only need these two env vars for GSM access:

```bash
export GCP_PROJECT_ID="YOUR_GCP_PROJECT_ID"
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.config/gcp/matriosha-gsm-reader.json"
```

(You do **not** need to place all app secrets in local `.env` files.)

---

### Step 4.2 — Install dependencies

```bash
cd <​repo-root>
python3 -m pip install -e .
```

---

### Step 4.3 — Run setup verification script

```bash
cd <​repo-root>
python3 scripts/verify_gsm_setup.py
```

Expected result:
- ✅ all required secrets found
- ✅ Supabase check passes
- ✅ Stripe check passes

If something fails, the script tells you exactly what to fix.

---

### Step 4.4 — Run Matriosha managed checks

```bash
cd <​repo-root>
matriosha --mode managed auth whoami --json
matriosha --mode managed billing status --json
matriosha --mode managed quota status --json
matriosha --mode managed token list --json
```

---

## Quick Troubleshooting

### Error: "Missing required secret"
- Secret name may be wrong (must match exactly)
- Secret exists but no value version added
- Wrong GCP project selected

### Error: "Permission denied" from GSM
- Service account missing role `roles/secretmanager.secretAccessor`
- Wrong `GOOGLE_APPLICATION_CREDENTIALS` file path

### Error: Supabase check fails
- Wrong `SUPABASE_URL`
- Wrong service role key
- Schema not applied yet

### Error: Stripe check fails
- Wrong `STRIPE_SECRET_KEY`
- Using live key while account is in test mode (or opposite)

---

## Security Rules (Simple)

- Never paste secret values in chat or screenshots.
- Never commit secrets to git.
- Keep secrets only in Google Secret Manager.
- Use short-lived local terminals when setting temporary env vars.
