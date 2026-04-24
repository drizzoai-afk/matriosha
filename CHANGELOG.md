# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Changed (2026-04-24)

#### P6.8 decoder plugin system with adaptive priority and discovery
- Added `core/interpreter_plugins.py` with a typed decoder protocol, central registry APIs, usage counters, deterministic ordering, and test reset support.
- Added runtime decoder management functions: `register_decoder`, `unregister_decoder`, `list_decoders`, and `reset_default_decoders_for_tests`.
- Added entry-point discovery for `matriosha.decoders` via `importlib.metadata` with non-fatal import/load failure handling.
- Refactored `core/interpreter.py` so decode routing now flows through plugin matching while preserving the existing `decode_semantic_content` public signature and semantic output contract.
- Converted built-in decoders (pdf, image, text, document, table, binary fallback) into plugin-style implementations registered on module load.
- Added deterministic warning behavior when multiple plugins match the same payload.
- Added plugin developer documentation in `docs/DECODER_PLUGINS.md` and specification-level extension contract updates.
- Added comprehensive plugin tests for runtime registration, entry-point discovery, failure handling, adaptive usage priority, and binary fallback compatibility.

#### P6.7 automatic token refresh with rotation and seamless managed retries
- Added managed refresh-token exchange support using the same token endpoint compatibility family as device flow (`grant_type=refresh_token`).
- Added 60-second clock-skew-aware staleness checks so near-expiry tokens refresh before managed requests.
- Added refresh-token rotation persistence with atomic encrypted TokenStore writes; refresh responses without `refresh_token` now retain existing refresh token.
- Integrated ManagedClient request lifecycle refresh behavior:
  - pre-flight refresh for stale profile-scoped tokens,
  - one forced refresh + one retry on HTTP 401,
  - actionable AUTH remediation (`matriosha auth login`) on refresh failure.
- Preserved existing managed error taxonomy/retry semantics, including unchanged 403 `insufficient_scope` behavior and unchanged 5xx retry strategy.
- Added test coverage for automatic refresh success, rotation persistence, 401 recovery retry, invalid refresh failure handling, missing refresh-token failure, and scope behavior stability.

#### P6.6 refocused on core agent-memory purpose (semantic-first)
- Rewrote `ATOMIC_PROMPTS.md` P6.6 to prioritize a semantic decoder/interpreter that transforms binary/base64 memories into rich agent-consumable JSON.
- Expanded required extraction coverage to include pdf, images, txt/markdown/json, doc/docx/odt, and xls/xlsx/csv/tsv payload families.
- Clarified recall contract: `memory recall --json` and `memory search --json` must expose first-class semantic payloads with immediate agent usability.
- Preserved command grammar compatibility and legacy preview behavior while elevating structured semantic output.

#### Corruption + backup behavior realigned for usability and resilience
- Local mode contract now emphasizes graceful corruption handling via warning-enriched output rather than process-stopping failure.
- Managed mode contract now requires automatic backup creation after memory writes and automatic backup restoration on Merkle corruption detection.
- Reaffirmed backup key naming convention: `<memory_id>.bin.b64.backup`.
- Reaffirmed architectural split: Supabase `vault` bucket stores encrypted backup blobs, while Vault key custody remains unchanged.

#### Documentation alignment for semantic content contracts
- Updated `SPECIFICATION.md` sections 2.2, 4.4, and 4.5 to define semantic-first recall and rich JSON extraction contracts.
- Updated `TASKS.md` T6 scope to center on semantic content extraction and agent-ready recall.
- Updated `BACKEND_SETUP.md` and `docs/MANAGED_BOOTSTRAP.md` to document managed backup bootstrap and corruption-triggered restore semantics.

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
