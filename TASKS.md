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
