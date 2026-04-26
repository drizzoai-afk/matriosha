# Matriosha v2 — SPECIFICATION.md

Version: **2.0.0-cli**  
Date: **2026-04-22**  
Status: **Active specification (CLI-only)**

---

## 1. Product Definition

Matriosha is a Python CLI for encrypted agent memory with verifiable integrity.

Core outcomes:
- Sovereign local memory in **Local mode**.
- Managed sync/policy workflows in **Managed mode**.
- Deterministic binary/base64 memory interchange with Merkle integrity.

Out of scope for this repository:
- Next.js frontend
- React components
- Browser OAuth flows

---

## 2. Dual-Mode Architecture

### 2.1 Local mode (default)
- Free, open-source core
- No auth required
- Offline-first
- User-owned keys never leave local trust boundary
- **Manual key lifecycle:** user runs `matriosha vault init` and manages passphrase/rotation/export choices

### 2.2 Managed mode
- Subscription-gated
- CLI-native authentication required
- Managed policy/sync integration enabled
- **Fully automated key lifecycle after authentication**
- **No `vault init` step for managed users**
- **No passphrase/password prompts for managed key custody**
- **Agent recall extension (semantic-first):** managed mode includes automatic blob backup in Supabase Storage bucket `vault` (`<memory_id>.bin.b64.backup`) so corrupted payloads can still resolve to structured semantic recall output

### 2.3 Key management semantics (normative)
- Local mode and managed mode MUST remain explicitly distinct in UX and help text.
- `matriosha vault init` is **Local mode only**.
- In managed mode, first successful `matriosha auth login` MUST automatically:
  1. Provision managed cryptographic key material if absent.
  2. Store managed wrapped key material in Supabase Vault.
  3. Persist only references/tokens required for transparent future operations.
- Managed users MUST NOT be asked to manually generate keys, copy key files, or manage crypto passphrases.
- All managed crypto operations (`memory remember/recall`, `vault sync`, token/agent operations) must be transparent after authentication.

### 2.4 Managed subscription pricing (canonical)
- **Base subscription:** **€9/month** includes up to **3 connected agents**.
- **Scalable agent packs:** **+€9/month for each additional block of 3 agents**.
  - 3 agents = €9/month
  - 6 agents = €18/month
  - 9 agents = €27/month
- **Managed storage cap:** **3 GB encrypted managed storage per 3-agent block** (pooled at workspace level).
  - Base (3 agents): 3 GB
  - 6 agents: 6 GB
  - 9 agents: 9 GB
- **Storage cap rationale:** keeps managed costs sustainable on Supabase-backed infrastructure while supporting encrypted payloads, pgvector metadata, and abuse-resistant operations under strict rate limiting.

### 2.5 Managed user journey (required UX)
1. User runs `matriosha auth login` (first time, managed mode).
2. System auto-generates/provisions keys if they do not already exist.
3. System stores wrapped key material in Supabase Vault.
4. User never sees, exports, or manually handles keys.
5. All encryption/decryption behavior is transparent in normal commands.

### 2.6 Managed session refresh contract (P6.7)
- Managed access tokens are refreshable when a valid `refresh_token` is present in the encrypted profile-scoped token store.
- Token expiry checks MUST apply a safety skew window of 60 seconds (tokens expiring within 60s are treated as stale).
- Client behavior requirements:
  - Pre-flight: stale/expired access token + refresh token triggers automatic refresh before request.
  - Recovery: a single HTTP 401 response may trigger one forced refresh and one retry of the same request.
  - Rotation: if refresh returns a new `refresh_token`, persist it atomically; if omitted, keep the previous refresh token.
- Environment override (`MATRIOSHA_MANAGED_TOKEN`) remains highest priority and bypasses profile-store refresh logic.
- When refresh cannot be completed (missing/invalid refresh token, refresh endpoint failure), user-facing remediation MUST be actionable: `matriosha auth login`.

---

## 3. Command System

Top-level grammar:

```bash
matriosha <group> <verb> [args] [flags]
```

Command groups:

```text
matriosha
├── mode
│   ├── show
│   └── set <local|managed>
├── auth                 # managed mode
│   ├── login            # first managed login auto-provisions keys + vault custody if missing
│   ├── logout
│   ├── whoami
│   └── switch
├── billing              # managed mode
│   ├── status
│   ├── subscribe
│   ├── upgrade          # add one 3-agent / +3 GB pack (Stripe-backed)
│   └── cancel
├── quota                # storage quota helpers
│   └── status
├── vault
│   ├── init             # local mode only (manual key bootstrap)
│   ├── verify
│   ├── rotate
│   ├── export
│   └── sync
├── memory
│   ├── remember
│   ├── recall
│   ├── search
│   ├── list
│   ├── delete
│   ├── compress
│   └── decompress
├── token
│   ├── generate
│   ├── list
│   ├── revoke
│   └── inspect
├── agent
│   ├── connect
│   ├── list
│   └── remove
├── status
├── doctor
├── completion
└── init                 # intelligent dependency bootstrap (P6.9)
```

Global flags:
- `--json`
- `--plain`
- `--verbose` / `-v`
- `--debug`
- `--profile <name>`
- `--mode <local|managed>`

### 3.1 Billing command semantics (managed mode)
- `billing status` must report subscription status plus `agent_quota` and storage cap/usage.
- `billing subscribe` must support scalable quantity in 3-agent blocks (1 block = €9/month, 3 agents, 3 GB).
- `billing upgrade` must add one additional 3-agent pack (+€9/month, +3 GB) through Stripe-backed quantity updates.
- `billing cancel` schedules cancellation at period end and must display effective cancellation date.

### 3.1.1 Quota management commands
The CLI MUST provide explicit quota management commands and shortcuts:
- `matriosha quota` / `matriosha quota status`: shows `storage_used_bytes`, `storage_cap_bytes`, percentage used, and breakdown by memory class (raw, compressed, index/metadata).
- `matriosha compress`: shortcut to `matriosha memory compress --deduplicate` with default dedup threshold `0.9`.
- `matriosha delete --older-than <days>`: shortcut to bulk delete by age.
- `matriosha delete --query <text>`: shortcut to semantic bulk delete.
- `matriosha billing upgrade`: starts managed upgrade flow to add one 3-agent pack.
- Human quota output MUST use adaptive units:
  - bytes for values below 1 KiB,
  - KiB below 1 MiB,
  - MiB below 1 GiB,
  - GiB at or above 1 GiB.
- Quota output MUST NOT round small non-zero managed storage usage to `0.00GB`.
- Example: `storage: 1.82MiB/3.00GiB (0.06%)`, not `storage: 0.00GB/3.00GB (0.00%)`.

### 3.2 Key-management command semantics
- `vault init` MUST return an actionable mode error in managed mode (`vault init is local-mode only`).
- `auth login` help/output MUST explicitly state: "auto-generates managed key custody on first use".
- Managed mode MUST NOT expose passphrase/password prompts for key custody workflows.

### 3.3 Local vs managed user experience comparison

| Area | Local mode | Managed mode |
|---|---|---|
| First setup | `matriosha vault init` | `matriosha auth login` |
| Key generation | Manual (user-triggered) | Automatic on first login |
| Key storage | Local encrypted key files + local controls | Wrapped keys in Supabase Vault |
| Passphrase handling | User-managed passphrase lifecycle | No key passphrase management exposed |
| Crypto visibility | Explicit and user-operated | Fully transparent |
| Peace of mind | Full sovereignty, manual responsibility | Full automation, zero crypto complexity |

### 3.4 Launcher command-listing contract (P6.1)
- The zero-arg launcher (`matriosha`) MUST expose the complete command system in the first interface.
- Command groups MUST be organized by category:
  - Local (memory, vault, status, doctor)
  - Managed (auth, billing, vault sync)
  - Agents (token, agent)
  - Settings (mode, completion, profile/config)
- No hidden command groups are allowed in launcher mode.
- Users MUST be able to see all groups and enter an "All commands" list without running `--help`.
- Launcher footer MUST show navigation controls (`↑/↓`, `Enter`, `/`, `?`, `q`).

### 3.5 Error handling contract (UX + operability)
- Errors MUST map to categories: `AUTH`, `NET`, `VAL`, `STORE`, `PAY`, `QUOTA`, `SYS`.
- Human-readable errors MUST be simple, actionable, and include exit code plus a short debug hint.
- Validation errors MUST include the invalid value, the rule that failed, and at least one valid example when the rule is user-facing.
- Tag validation errors MUST explicitly state:
  - tags must be lowercase,
  - max length is 32 characters,
  - allowed characters are `a-z`, `0-9`, hyphen, and underscore,
  - valid regex is `^[a-z0-9][a-z0-9_\-]{0,31}$`,
  - and a corrected example when obvious.
- Example tag validation message: `Tag 'edrm-round1-20260426T135446Z' is invalid. Tags must be lowercase, max 32 chars, and may contain a-z, 0-9, hyphen, or underscore. Example: edrm-round1-20260426t135446z`
- Stripe failures MUST include safe hints such as `stripe_code`/`request_id` (no secrets).
- Supabase failures MUST include safe hints such as `http_status`/`sqlstate`/`rls_policy` (no tokens).
- Python/runtime and hardware/connection issues (disk full, keyring unavailable, filesystem permissions, timeouts) MUST map to `SYS` or `NET` with remediation guidance.

### 3.6 Quota warning + enforcement contract
- Managed mode MUST warn at **80% usage** of plan storage cap (e.g., **2.4 GB / 3.0 GB** on base plan).
- Managed mode MUST enforce a **hard write limit at 100%** of cap (e.g., 3.0 GB / 3.0 GB).
- On warning or hard-limit events, CLI MUST present exactly three remediations:
  1. `compress` (reduce footprint via dedup merge),
  2. `delete` (bulk delete with filters),
  3. `upgrade` (Stripe-backed `billing upgrade`, adds +3 agents/+3 GB).
- Upgrade flow MUST be quantity-backed Stripe billing integration (same catalog/rules as `billing subscribe`).

### 3.7 Compression + deduplication contract
- `memory compress` / `matriosha compress` MUST support dedup-mode with cosine similarity threshold **> 0.9** by default.
- Compression algorithm (normative):
  1. Embed candidates (same vector space as search index).
  2. Build similarity graph for pairs where cosine similarity > threshold.
  3. Form connected clusters and merge each cluster into a parent compressed memory.
  4. Preserve original metadata: `created_at`, `updated_at`, `source`, tags, and child IDs.
  5. Recompute hashes and update Merkle leaves/root after parent write (and after optional child archival/delete).
- Compressed memories MUST remain searchable by semantic recall/search and return transparent parent/child provenance.

### 3.8 Delete filters + safety contract
- `memory delete` / `matriosha delete` MUST support:
  - Time filters: `--older-than <days>`, `--before <YYYY-MM-DD>`, `--after <YYYY-MM-DD>`, `--between <start> <end>`.
  - Semantic filters: `--query <text>`, `--similar-to <memory-id>`, `--threshold <0.0-1.0>`.
- Bulk deletes (more than one candidate) MUST require explicit confirmation unless `--yes` is provided.
- Deletion policy: permanent removal of encrypted payload + vector index + local metadata references; retain only minimal non-recallable audit tombstones when required for integrity/accounting.

### 3.8.1 Deletion output UX contract

- `memory delete` MUST produce visually consistent output across repeated single deletes and bulk deletes.
- Human output MUST avoid mixed styling that appears inconsistent during loops or batch deletion.
- `--json` output MUST be stable, complete, and suitable for automation.
- Scripts and stress tests SHOULD use `--json --yes` for deletion cleanup.
- Human output SHOULD summarize bulk deletion instead of printing noisy repeated panels when deleting many memories.

### 3.9 CLI Commands (P6.9)
- `matriosha init` is the canonical environment bootstrap command for first-run setup.
- Purpose: provide intelligent dependency detection and installation for runtime prerequisites required by semantic decode and related CLI flows.
- Behavior requirements:
  - context-aware scanning of host capabilities (Python runtime + system tools),
  - user-guided installation flow for missing dependencies (system and Python),
  - explicit per-dependency approval prompts unless `--yes` / `--auto-approve` is set,
  - non-interactive safety: if missing dependencies are found in non-TTY mode without `--yes`, command fails with actionable guidance,
  - graceful error handling when auto-install is unavailable or denied.
- Safety requirements:
  - installation allowlist includes only `tesseract-ocr`, `poppler-utils`, `libmagic1`, and packages listed in `requirements.txt`,
  - timeout limit is 5 minutes per install attempt,
  - no arbitrary shell execution paths are permitted.
- Platform support requirements:
  - Ubuntu 20.04+, Debian 10+, macOS 11+ (Homebrew),
  - unsupported platforms must return fallback manual instructions.
- Output requirements:
  - a human-readable system report summarizing detected/missing dependencies,
  - setup attempt logs at `~/.matriosha/setup.log`,
  - an init report at `~/.matriosha/init_report.md` describing actions and remediations.
- Detailed dependency matrix and installation guidance MUST be maintained in `docs/DEPENDENCIES.md`.

---

## 4. Memory Data Contract

### 4.1 Transport
- Canonical payload: **binary**
- Exchange format: **base64**
- Payloads MUST be split into fixed **64 KiB blocks** before hashing/encryption/storage.
- The fixed block size is normative for Merkle integrity and deterministic interchange.

### 4.2 Integrity primitives
- Hash: **SHA-256** for each block
- Tree: **Merkle tree** over block hashes
- Verification: include and verify `merkle_leaf` + `merkle_root`

### 4.3 Mandatory metadata

```json
{
  "memory_id": "...",
  "mode": "local|managed",
  "encoding": "base64",
  "hash_algo": "sha256",
  "merkle_leaf": "...",
  "merkle_root": "...",
  "vector_dim": 384,
  "created_at": "ISO-8601",
  "tags": ["..."],
  "source": "cli|agent"
}
```

### 4.4 Backup + corruption recovery contract (semantic-first)
- CLI write path is **local-first** and authoritative.
- Managed mode MUST create/update a backup blob in Supabase Storage bucket `vault` after successful memory creation/write.
- Backup key format is mandatory: `<memory_id>.bin.b64.backup`.
- Backup blobs are for integrity incidents only; SQL schema remains unchanged.
- Backup restore/fallback is allowed ONLY when Merkle verification reports corruption.
- Local mode corruption handling MUST be graceful: recall returns warning-enriched output (for example `integrity_warning`) instead of terminating the full response path.
- Managed mode corruption handling MUST automatically read/restore from backup blob when corruption is detected.
- No asynchronous dual-write pipeline and no resilient-fetch subsystem outside corruption class are required.

### 4.5 Semantic decode output contract (JSON, agent-ready)
- `memory recall --json` and `memory search --json` MUST preserve existing JSON command grammar while elevating semantic payload as first-class output.
- Decoder output MUST be rich structured JSON immediately consumable by agents (for example: `kind`, `mime_type`, `filename`, `text`, `tables`, `metadata`, `warnings`, `preview`).
- Legacy preview behavior (max 4KB) MUST remain for backward compatibility.
- Rich built-in extraction MUST target:
  - PDF: `.pdf`, `application/pdf`
  - images: `.png`, `.jpg`, `.jpeg`, `.bmp`, `.gif`, `.webp`, `.tiff`, `.tif`, and `image/*`
  - plain text: `.txt`, `text/plain`
  - markdown: `.md`, `.markdown`, `text/markdown`
  - JSON: `.json`, `application/json`
  - delimited tables: `.csv`, `.tsv`, `text/csv`, `text/tab-separated-values`
  - Word documents: `.docx`
  - Excel workbooks: `.xlsx`
- Rich extraction SHOULD produce:
  - `text` when extractable,
  - `tables` for CSV/TSV, DOCX tables, and XLSX sheets,
  - bounded `metadata`,
  - `preview`,
  - `warnings`.
- Legacy/proprietary formats are NOT rich-decoded by the built-in interpreter unless a dedicated plugin is installed.
- Legacy/proprietary fallback formats include, at minimum:
  - `.doc`
  - `.odt`
  - `.xls`
  - `.msg`
  - `.dwg`
  - archives such as `.zip`, `.tar`, `.gz`
- Semantic decoding is best-effort and MUST NOT weaken binary integrity guarantees.
- All recalled files, including unknown or unsupported formats, MUST return a structured semantic envelope.
- If rich extraction is unavailable, the interpreter MUST return safe fallback metadata instead of failing.
- Unsupported binary formats MUST include:
  - `kind: "binary"` or a more specific safe class such as `"archive"`, `"image"`, `"document"`, or `"cad"` when detectable,
  - `mime_type`,
  - `filename`,
  - `size_bytes` or equivalent input-size metadata,
  - bounded preview when safe,
  - `warnings` explaining that rich extraction was unavailable.
- Archive formats (`zip`, `tar`, `gz`) MUST NOT be recursively expanded by default unless explicitly requested by a future safe extraction flag.
- Interpreter success means “agent-safe structured output,” not necessarily full text extraction for every legacy/proprietary format.
- Decoder plugins MAY add rich support for additional formats through the `matriosha.decoders` entry-point group or runtime decoder registration.

### 4.6 Decoder plugin extension contract (P6.8)
- Decoder plugin registry MUST live in `core/interpreter_plugins.py` and expose:
  - `register_decoder(plugin, *, replace=False)`
  - `unregister_decoder(name)`
  - `list_decoders()`
  - `reset_default_decoders_for_tests()`
- Plugin interface is normative:
  - `name` (unique string)
  - `supports(mime_type, filename, metadata) -> bool`
  - `decode(raw, metadata, bounds) -> dict`
- Decoder selection order MUST be deterministic and routed by source tier:
  1. runtime-registered plugins
  2. entry-point plugins discovered from `matriosha.decoders`
  3. built-in decoders
  4. binary fallback decoder (always last)
- Within a source tier, decoders MUST be ordered by successful usage count (higher first) with deterministic tie-breakers.
- Entry-point load/import failures MUST be non-fatal and surfaced as semantic warnings.
- If multiple plugins match a payload, the selected plugin and skipped alternatives MUST be disclosed via warning metadata.

---

## 5. Security Requirements

- AES-256-GCM encryption only
- Argon2id KDF with hardened parameters
- CSPRNG nonce generation
- No plaintext key persistence
- Query/filter injection prevention
- Supabase RLS ownership checks where managed storage is used
- Signature verification for external webhook/event ingress

---

## 6. Active Repository Structure

```text
matriosha/
├── cli/
├── core/
├── pyproject.toml
├── requirements.txt
├── RULES.md
├── TASKS.md
├── SPECIFICATION.md
└── DESIGN.md
```

Legacy and non-core assets are archived and excluded from active implementation paths.

---

## 7. Acceptance Criteria

- Local mode fully operational without auth
- Managed mode gated and explicit
- Managed first-login key bootstrap is automatic; managed users do not touch keys/passphrases
- Output format deterministic in `--json`
- No web architecture dependencies in active code tree
- Security and integrity checks enforced on memory operations
