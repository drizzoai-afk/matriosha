# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Changed (2026-04-22)

#### ATOMIC_PROMPTS.md — Google Secret Manager integration layer added
- Added explicit dependency pin `google-cloud-secret-manager>=2.16.0` to **P1.1** dependency instructions.
- Expanded **P1.3** with a mandatory baseline implementation for `core/secrets.py` including:
  - `SecretManager` class using `google.cloud.secretmanager.SecretManagerServiceClient`
  - deterministic lookup order: `os.getenv` → Google Secret Manager → safe local fallback
  - required environment variable references: `GCP_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS`
  - error-handling expectations for missing/denied/unavailable secrets
  - local-mode fallback requirements when managed secrets are unavailable
- Added mandatory Google Secret Manager instructions (with secret-name usage and failure semantics) to all managed/security-sensitive prompts in:
  - **P4.1, P4.2, P4.3, P4.4, P4.5, P4.6**
  - **P5.1, P5.2, P5.3**
- Added task-specific secret resolution expectations for:
  - Supabase credentials (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY`)
  - Stripe credentials (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`)
- Updated Appendix A cross-cutting rules to require env/GSM-based secret sourcing via `core/secrets.py` secret names.

#### .gitignore — security hardening
- Reworked ignore rules to exclude sensitive and local-only artifacts, including:
  - service account key patterns (`*.json`, `gcp-sa-key.json`, and related key-file patterns)
  - credentials directory (`.matriosha/credentials/`)
  - local config files (`config.toml`, `.env`, `.env.*`)
  - Python caches and tooling artifacts (`__pycache__`, `*.pyc`, `*.pyo`, pytest/mypy/ruff caches)
  - virtual environments (`venv/`, `.venv/`, `env/`)
  - IDE/editor files (`.vscode/`, `.idea/`)
  - common key/cert material and log/temp files

### Changed (2026-04-22) — Pricing model documentation alignment

- Standardized managed subscription pricing across docs:
  - Base: €9/month for 3 agents
  - Scaling: +€9/month per additional 3 agents
- Added canonical managed storage cap policy:
  - 3 GB encrypted managed storage per 3-agent billing block
- Updated billing semantics in `SPECIFICATION.md` so CLI subscription commands include quota/cap expectations.
- Updated `ATOMIC_PROMPTS.md` Stripe-related tasks to support scalable quantity-based checkout and quota/cap verification.

### Security improvements
- Prompt-level guardrails now enforce secret-name based retrieval over literal key values in all managed-mode and token-related tasks.
- Managed-mode instructions now require actionable error paths for missing secrets while preserving local mode resilience.
- Secret-handling patterns now explicitly prohibit logging secret payloads and full credential paths.
