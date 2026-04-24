# Matriosha v2 — TASKS.md

Status: **Execution backlog and completed isolation log**.

---

## 1) Active Atomic Work Queue

### T1. CLI command parity
- Normalize command tree to `SPECIFICATION.md`.
- Ensure `--json` parity for every public command.
- Add deterministic exit codes.

### T2. Integrity hardening
- Enforce SHA-256 + Merkle verification on all read/write paths.
- Add per-block verification hooks.

### T3. Local/managed boundary enforcement
- Fail-fast for managed-only commands in local mode.
- Add mode diagnostics to `status` command.

### T4. Security hardening pass
- Review query input validation paths.
- Add explicit redaction in logs/output.
- Add retry/rate-limiting envelope around sensitive auth/KDF surfaces.

### T5. Testing for atomic tasks
- Unit tests for `core` crypto/protocol/merkle.
- CLI behavior tests for output schema and error paths.

### T6. Semantic content extraction + agent-ready recall
- Implement a semantic content decoder/interpreter that transforms binary/base64 memories into rich structured JSON usable immediately by agents.
- Support extraction routing for pdf, images, txt/markdown/json, doc/docx/odt, xls/xlsx/csv/tsv, and unknown binary fallback.
- Preserve command grammar and legacy 4KB preview compatibility while making semantic payload first-class in recall/search outputs.
- Local mode corruption behavior: return warning-enriched recall output (do not hard-stop full processing).
- Managed mode: automatically create/update backup blob in Supabase bucket `vault` after memory creation/write.
- Backup key contract: `<memory_id>.bin.b64.backup`; use backup restoration ONLY when Merkle verification reports corruption.
- Expand integration/contract coverage for multi-file-type semantic extraction, rich output validation, corruption warnings, and managed backup recovery.

### P7.1 Integration test program (split into atomic slices)
- **P7.1a — Core integration test infrastructure + critical scenarios (current scope)**
  - Build `tests/integration/conftest.py` fixtures (`temp_home`, `initialized_vault`, backend detection, mocked/real managed client controls, CLI runner).
  - Add critical path tests: local happy path, basic managed sync, integrity corruption exit validation, semantic extraction contract coverage.
  - Add CI workflow support for real backend execution with `GCA_JSON`, `GCP_PROJECT_ID`, and `GCP_SA_KEY`.
  - Add realistic integration fixtures and syrupy snapshot contract checks.
- **P7.1b — Advanced scenarios**
  - Token lifecycle (refresh/rotation) integration validation.
  - Key rotation workflows and crash/resume paths.
  - Backup recovery verification, doctor scenarios, and mode-guard enforcement coverage.
- **P7.1c — Visual verification workflow + comprehensive adversarial suite**
  - Fast screenshot-driven visual verification workflow for key command outputs.
  - Broader adversarial matrix and stress cases across supported file types and corruption classes.

---

## 2) Completed Isolation Summary (2026-04-22)

This section is the required `matriosha_v2_isolation_summary` content, stored in-repo for clean-session continuity.

### 2.1 Docs refactor completed
- Created authoritative docs:
  - `RULES.md`
  - `TASKS.md`
  - `SPECIFICATION.md`
  - `DESIGN.md`
- Retired prior markdown docs from active tree and archived legacy material.

### 2.2 Architecture cleanup completed
- Removed active references to Next.js/web components from current specification set.
- Established CLI-only architecture as the sole active implementation scope.
- Preserved dual-mode operation model (local vs managed) in all active docs.

### 2.3 Local core isolation completed
- Isolated essential Python local components into:
  - `/home/ubuntu/matriosha_v2_core`
- Included:
  - `core/` primitives (security, binary protocol, merkle, vector brain, adapter)
  - `cli/` command and utility surface
  - `requirements.txt`, `pyproject.toml`
- Excluded web/dashboard and unrelated managed/frontend artifacts.

### 2.4 Repository cleanup completed
- Archived non-approved files from active repo paths to support clean AI-agent sessions.
- Active tree now optimized for atomic Python CLI tasks.

---

## 3) Next Session Entry Rules

1. Read `RULES.md` first.
2. Implement only one atomic task at a time.
3. Keep all spec/design changes synchronized with `SPECIFICATION.md` + `DESIGN.md`.
4. Do not reintroduce web stack assets into active implementation paths.
