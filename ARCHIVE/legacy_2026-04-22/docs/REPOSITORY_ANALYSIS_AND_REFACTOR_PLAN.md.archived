# Matriosha Repository Analysis & Refactoring Plan

**Repository:** `drizzoai-afk/matriosha`  
**Analysis date:** 2026-04-22  
**Analyst:** Abacus AI Agent

---

## 1) Executive Summary

Matriosha is a **hybrid codebase** combining:
- a Python local-first encrypted memory engine (`core/`, `cli/`, `mcp_server.py`), and
- a Next.js + Clerk + Supabase web control plane (`app/`, `components/`, `lib/`, `app/api/*`).

The project vision is strong and coherent (secure portable memory with Merkle integrity + semantic recall), but the repository currently mixes:
- implemented features,
- stubs,
- temporary artifacts,
- legacy/duplicate documentation,
- and partially overlapping backend implementations.

The biggest immediate opportunity is a **repo hygiene + structure normalization pass** before isolating any single component.

---

## 2) Deep Project Structure Exploration

## 2.1 Top-Level Layout (Current)

- `.agent/`, `.agents/`, `.aidesigner/`, `.codex/` → agent tooling/meta
- `.edge-functions-temp/` → temporary/duplicate webhook code (Deno)
- `app/`, `components/`, `lib/`, `middleware.ts` → Next.js app router frontend/API
- `cli/`, `core/`, `mcp_server.py` → Python memory engine + CLI + MCP server
- `migrations/` → Supabase SQL schema + RLS
- `scripts/` → benchmarks, secret setup/push scripts
- `docs/` + multiple root `.md` files → extensive mixed documentation/audits
- generated artifacts currently tracked: `__pycache__/`, `*.pyc`, `matriosha.egg-info/`
- anomalous tracked file: `<_io.BufferedWriter name=13>`

## 2.2 Key Runtime Directories

### Python runtime
- `core/security.py` → AES-256-GCM, Argon2id, keyring integration
- `core/binary_protocol.py` → 16-byte memory header pack/unpack
- `core/merkle.py` → Merkle tree build/proof verification
- `core/brain.py` → LanceDB + FastEmbed semantic index/search
- `core/adapter.py` → local/hybrid/managed storage adapter (partially implemented)
- `cli/commands/*` → `init`, `remember`, `recall`, `verify`, `sync`, `export/import`, `compress`
- `mcp_server.py` → MCP tools: `search_memory`, `store_memory`

### Web runtime
- `app/page.tsx` → landing page
- `app/dashboard/page.tsx` → authenticated dashboard
- `app/api/*` → memories/integrity/archive/billing/checkout/stripe webhook/status
- `lib/supabase.ts` → Supabase SSR/browser clients
- `middleware.ts` → Clerk protection + Supabase cookie sync

---

## 3) Architecture & Design Patterns

## 3.1 Macro Architecture

Matriosha currently behaves like **two coupled but not fully unified systems**:

1. **Local Sovereign Memory Engine (Python):**
   - encrypted block storage
   - local semantic indexing
   - integrity primitives (Merkle)
   - CLI/MCP access

2. **Managed Dashboard Plane (Next.js/Supabase/Stripe):**
   - user auth + subscription UX
   - DB-backed metadata views
   - API wrappers for billing/archive/integrity status

### Observed design patterns
- Layered modular core (`security` → `protocol` → `storage`/`brain`)
- Command pattern via Typer commands
- Adapter strategy in `MatrioshaAdapter` (`local|hybrid|managed`)
- Local-first fallback strategy (where implemented)
- API-route gateway pattern in Next.js (`app/api/*`)

---

## 4) Component Breakdown (Roles & Responsibilities)

## 4.1 Python Core Components

- **`core/security.py`**
  - key derivation (Argon2id)
  - key storage/retrieval (keyring + fallback file)
  - encrypt/decrypt (AES-256-GCM)
  - leaf hash helper

- **`core/binary_protocol.py`**
  - serializes/deserializes 16-byte metadata header
  - logic/importance/flags/timestamp/leaf hash fields
  - header validation

- **`core/merkle.py`**
  - hash leaves/nodes
  - build tree/root
  - generate and verify inclusion proofs

- **`core/brain.py`**
  - embeddings via FastEmbed (`all-MiniLM-L6-v2`)
  - LanceDB index init/add/search/delete
  - metadata filtering by importance

- **`core/adapter.py`**
  - atomic local writes into `vault/blocks/`
  - optional Supabase hot sync
  - placeholder cold tier

## 4.2 Python Interface Components

- **CLI (`cli/main.py`, `cli/commands/*`)**
  - `init`: creates vault, salt, key, config
  - `remember`: encrypts and stores block + index update
  - `recall`: semantic search + decrypt path
  - `verify`: Merkle/header validation
  - `sync`, `export/import`: currently stubs
  - `compress`: calls missing `brain.compress_memories()`

- **MCP server (`mcp_server.py`)**
  - tool endpoints for AI coding agents
  - `store_memory` and `search_memory`
  - directly reads/writes vault blocks and updates index

## 4.3 Web Components

- **Frontend pages/components**
  - landing marketing + quick start + pricing
  - dashboard cards (subscription/storage/integrity/actions)

- **API routes (`app/api/*`)**
  - `memories`: list/insert rows
  - `archive`: hot→cold status update placeholder
  - `integrity`: currently mock root compare/update against `profiles`
  - `billing`: static plan payload
  - `create-checkout-session`: Stripe checkout creation
  - `webhooks/stripe`: webhook signature verify + subscription upsert
  - `status`: currently mock operational payload

- **Data access (`lib/supabase.ts`)**
  - server/browser clients with env requirement

---

## 5) End-to-End Execution Paths

## 5.1 CLI Memory Write Path (`remember`)

`CLI input` → load config/vault → retrieve key → build JSON memory payload → encrypt (AES-GCM) → derive leaf ID hash → pack 16-byte header → write `.bin` block → update LanceDB index → write `.merkle_root` metadata.

## 5.2 CLI Memory Read Path (`recall`)

`CLI query` → semantic search in LanceDB → for each leaf ID read `.bin` → unpack header → split ciphertext/nonce/tag → decrypt → parse JSON → output format.

Note: Merkle verification in recall is currently simplified and effectively trusts root existence.

## 5.3 MCP Path

- `store_memory`: similar to CLI remember flow.
- `search_memory`: similar to CLI recall flow.

## 5.4 Dashboard + API Path

Auth via Clerk → page fetches Supabase tables (`subscriptions`, `vaults`, `key_escrow`, `memory_vectors`) → dashboard action buttons call API routes (`/api/*`) → routes read/write Supabase (and Stripe for billing events).

---

## 6) Data Flow Analysis

## 6.1 Local Data Flow (Python)

- Vault path from `~/.matriosha/config.toml`
- Salt at `vault/salt.bin`
- Encrypted memory blocks as `vault/<leaf_id>.bin` (CLI/MCP)
- Vector index at `vault/matriosha_brain.lancedb`
- Merkle root in `vault/.merkle_root`

## 6.2 Managed Data Flow (Web)

- Clerk `userId` gates API access
- Supabase tables consumed by dashboard
- Stripe webhook updates subscriptions
- Archive/integrity/status endpoints still partially mock/placeholder

## 6.3 Cross-System Flow Gaps

The Python local vault and Next.js-managed Supabase layer are conceptually aligned but **not fully wired end-to-end**:
- API integrity logic is mock-based and uses `profiles` table not in migrations.
- `memories` API expects tables/RPC not present in migrations.
- Local Merkle roots and dashboard integrity are not consistently connected.

---

## 7) Duplications, Messy Organization, and Structural Inconsistencies

## 7.1 Duplicate / Redundant / Fragmented Content

1. **Multiple audit reports with overlapping scope and conflicting claims:**
   - `AUDIT_REPORT.md`
   - `AUDIT_FINAL_v1.2.md`
   - `docs/AUDIT_COMPLETE.md`
   - `docs/TEST_REPORT.md`

2. **Duplicate Stripe webhook implementations in multiple places:**
   - `app/api/webhooks/stripe/route.ts`
   - `.edge-functions-temp/stripe-webhook.ts`
   - `.edge-functions-temp/stripe-webhook/index.ts`

3. **Spec/documentation references paths that do not exist or are legacy**
   - `dashboard/` directory referenced in docs/scripts, but app is root-level `app/` Next.js structure.

## 7.2 Repository Hygiene Issues

1. Generated artifacts committed:
   - `__pycache__/` directories
   - `*.pyc`
   - `matriosha.egg-info/`

2. Accidental file tracked:
   - `<_io.BufferedWriter name=13>`

3. `.gitignore` missing Python artifact ignores (`__pycache__/`, `*.pyc`, `*.egg-info/`).

## 7.3 Structural / Behavioral Inconsistencies

1. **Schema mismatch:**
   - API routes use `memories`, `profiles`, RPC `increment_storage_usage`
   - migrations define `vaults`, `key_escrow`, `subscriptions`, `memory_vectors`
   - missing migration for `memories/profiles` and RPC.

2. **Storage path mismatch inside Python stack:**
   - `remember.py` + `mcp_server.py` write blocks to vault root
   - `adapter.py` writes to `vault/blocks/`

3. **Leaf ID hash inconsistency:**
   - `remember.py` hashes `ciphertext+nonce+tag`
   - `mcp_server.py` hashes only `ciphertext`

4. **Command/implementation mismatch:**
   - `compress` command calls `brain.compress_memories()` which is not implemented.
   - `sync`, `export`, `import` are explicit stubs.

5. **Environment/secrets mismatch:**
   - `core/secrets.py` expects keys like `SUPABASE_URL`
   - `scripts/setup_secrets.py` seeds keys with `matriosha-...` names.

6. **Security/config placeholders in production paths:**
   - Stripe route defaults to placeholder secret key when env missing.
   - billing route returns static test portal URL.

7. **Documentation/version drift:**
   - README says Next.js 15; `package.json` uses Next 16.

8. **Missing expected tests folder from spec structure** (`tests/` not present).

---

## 8) Architecture Description Diagram (Text)

```mermaid
flowchart TD
  A[CLI / MCP Client] --> B[Python Core]
  B --> B1[security.py\nArgon2id + AES-GCM + keyring]
  B --> B2[binary_protocol.py\n16-byte header]
  B --> B3[brain.py\nFastEmbed + LanceDB]
  B --> B4[merkle.py\nroot/proofs]
  B --> B5[adapter.py\nlocal/hybrid/managed]

  B --> C[Local Vault Filesystem\n.bin blocks + .merkle_root + lancedb]
  B --> D[Supabase Storage/DB (partial)]

  E[Next.js Dashboard] --> F[API Routes app/api/*]
  F --> G[Clerk Auth]
  F --> H[Supabase Tables]
  F --> I[Stripe]

  D -. intended integration .- H
  C -. intended integrity/data sync .- F
```

---

## 9) Refactoring Plan (Before Component Isolation)

## Phase 0 — Safety Baseline (Day 0)
1. Create a dedicated refactor branch.
2. Freeze feature additions; only cleanup + alignment changes.
3. Add CI checks for Python + TS lint/tests + markdown link check.

## Phase 1 — Repository Hygiene Cleanup (Day 1)
1. Remove tracked generated artifacts (`__pycache__`, `*.pyc`, `*.egg-info`).
2. Remove accidental file `<_io.BufferedWriter name=13>`.
3. Update `.gitignore` with Python/runtime/build artifacts.
4. Move temporary experiments (`.edge-functions-temp`) to either:
   - canonical implementation directory, or
   - `archive/` (if deprecated).

## Phase 2 — Canonical Structure Normalization (Days 1-2)
Adopt a clear monorepo layout:
- `apps/web` (Next.js)
- `apps/mcp` (or keep `mcp_server.py` under `services/mcp`)
- `packages/core` (Python core modules)
- `packages/cli`
- `infra/supabase/migrations`
- `docs/`

If full move is too large now, define and enforce a “transitional canonical map” in `docs/REPO_MAP.md`.

## Phase 3 — Source of Truth Consolidation (Days 2-3)
1. Consolidate audit docs into one canonical audit + changelog appendix.
2. Keep one architecture doc and one operational runbook.
3. Align README/SPEC/package versions (Next 16, actual implemented features).
4. Mark stubs clearly as roadmap items with status table.

## Phase 4 — Data Model & Backend Contract Alignment (Days 3-4)
1. Decide canonical DB schema:
   - either migrate APIs to existing migration tables,
   - or add migrations for `memories`, `profiles`, and `increment_storage_usage` RPC.
2. Remove mock integrity/status behavior where production path exists.
3. Standardize one webhook path (Next API route **or** Supabase edge function), not both.

## Phase 5 — Python Runtime Consistency (Days 4-5)
1. Standardize block storage location (`vault/blocks` vs root).
2. Standardize leaf ID derivation algorithm across CLI + MCP.
3. Implement real Merkle verification in recall path (or explicitly document deferred behavior).
4. Either implement `compress_memories()` or disable `compress` command behind feature flag.
5. Keep `sync/export/import` hidden or marked experimental until implemented.

## Phase 6 — Secrets & Environment Contract (Day 5)
1. Unify secret key naming between runtime and setup scripts.
2. Remove default placeholder secrets in runtime code paths.
3. Fix scripts referencing `dashboard/.env.local` when dashboard folder does not exist.

## Phase 7 — Testability & Isolation Readiness (Days 5-6)
1. Create missing `tests/` baseline:
   - unit tests: security/protocol/merkle/brain
   - integration tests: remember→recall, API route contract tests
2. Add architecture decision records (ADRs) for:
   - local-first data contract
   - cloud sync contract
   - webhook deployment strategy
3. Tag components by isolation readiness:
   - **Ready:** `core/security.py`, `core/binary_protocol.py`, `core/merkle.py`
   - **Needs alignment first:** `core/brain.py`, `adapter.py`, dashboard/API bridge

---

## 10) Practical Priority Order

If you want fastest cleanup impact before component isolation, do this order:

1. Hygiene + `.gitignore` + remove accidental/generated files
2. Pick canonical webhook implementation and remove duplicates
3. Align DB schema with API routes (remove mock drift)
4. Unify Python block format/path/hash logic
5. Consolidate docs into single source of truth

This sequence gives immediate clarity and minimizes risk when isolating the next component.

---

## 11) Final Assessment

Matriosha has a strong core concept and several solid foundational modules, but the repository currently reflects rapid iteration across multiple tracks (Python core, dashboard, ops docs) without consolidation.

A **targeted 5–6 day refactor sprint** focused on structure, contracts, and source-of-truth cleanup should make the codebase significantly cleaner and ready for safe component isolation.
