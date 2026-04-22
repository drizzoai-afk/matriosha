# Matriosha v2 — RULES.md

Status: **Authoritative implementation rules for all future agent sessions**.
Scope: **CLI-only Python architecture** (local core + managed mode boundaries), no web/dashboard code in this repository.

---

## 1) Non-Negotiable Product Boundaries

1. This repository is **CLI-first and Python-only**.
2. **No Next.js, React, browser OAuth, or web component work** is allowed in this repo.
3. Architecture is explicitly dual-mode:
   - **Local mode**: open-source, offline-first, no auth required.
   - **Managed mode**: subscription-gated, CLI-native auth, managed sync/policy.
4. All changes must preserve strict separation:
   - `core/` = cryptography, binary protocol, merkle, vector brain, adapter.
   - `cli/` = command surface and output contract.
   - Managed integrations must not break local mode operation.

---

## 2) Security Practices (Mandatory)

### 2.1 OWASP-aligned controls

- **A01 Broken Access Control**
  - Enforce user-scoped data controls (`user_id` ownership checks).
  - Never broaden access policies for convenience.
- **A02 Cryptographic Failures**
  - Use AES-256-GCM only for memory payload encryption.
  - Use Argon2id with strong parameters (>= time=3, memory=64MB, parallelism=4).
  - Generate nonces with CSPRNG (`os.urandom(12)`).
- **A03 Injection**
  - Use parameterized queries and validated filters only.
  - Never build query logic from raw untrusted strings.
- **A05 Security Misconfiguration**
  - Keep sensitive keys out of source control.
  - Validate runtime dependency/config completeness during startup.
- **A07 Identification & Authentication Failures**
  - Add rate limits/backoff around key derivation and auth retries.
- **A08 Software & Data Integrity Failures**
  - Require SHA-256 per block + Merkle root integrity verification.
  - Prefer constant-time comparison in integrity checks.

### 2.2 Supabase security constraints

- RLS policies must map identity to owner correctly (`auth.uid()::text = user_id`).
- `USING` + `WITH CHECK` clauses are mandatory for mutable owner tables.
- `key_escrow` writes are restricted to service role paths only.
- Webhook/event handlers must verify signatures before processing payload.

### 2.3 Cryptographic key handling

- Never store plaintext master/session keys on disk.
- Prefer OS keyring for local secret persistence.
- Zero sensitive buffers/variables where practical after use.
- No debug logs may leak passwords, plaintext memory, or decrypted payloads.

---

## 3) CLI UX Rules (Synthesized Best Practices)

The CLI must be usable by both power users and automations.

### 3.1 Command ergonomics

- Grammar: `matriosha <group> <verb> [args] [flags]`.
- Nouns stable, verbs explicit, aliases documented.
- Support predictable global flags:
  - `--json`, `--plain`, `--verbose/-v`, `--debug`, `--profile`, `--mode`, `--help`, `--version`.

### 3.2 Human UX conventions

- Default output is concise and actionable.
- Use progressive disclosure:
  - short success line by default,
  - richer detail via `--verbose`/`--debug`.
- Errors must include:
  1. what failed,
  2. likely cause,
  3. exact next command to recover.
- Use TTY-aware rich rendering for humans (`rich` panels/tables).

### 3.3 Machine UX conventions

- `--json` output is deterministic and schema-stable.
- Never mix prose with JSON payload in machine mode.
- Exit codes are consistent:
  - `0` success,
  - non-zero for validation/runtime/integrity failures.

### 3.4 Interface aesthetics

- Keep Daytona-inspired density: minimal noise, high legibility, status-first.
- Preserve ASCII identity in CLI banner/help screens (binary matrioshka style).
- No decorative output in `--plain` mode.

---

## 4) Design Constraints (from approved CLI design)

1. Mode boundary is explicit and visible in status output.
2. Managed mode requires CLI-native authentication (no browser OAuth flow in this repo).
3. `memory decompress` is available when high similarity demands finer recall.
4. Agent token provisioning is manual and user-driven (no auto enrollment).
5. Sync behavior:
   - managed mode: automated,
   - local mode: explicit user invocation.

---

## 5) Output Format Contract (Mandatory)

All memory operations must honor this transport contract.

### 5.1 Payload encoding

- Internal representation: **binary**.
- Transport representation: **base64**.

### 5.2 Integrity fields

Each block must include:
- `sha256` hash of canonical block payload,
- `merkle_leaf` identifier,
- `merkle_root` reference at operation time.

### 5.3 Required metadata envelope

Every CLI memory output (human or JSON mode) must map to metadata fields:

- `memory_id`
- `mode` (`local|managed`)
- `encoding` (`base64`)
- `hash_algo` (`sha256`)
- `merkle_leaf`
- `merkle_root`
- `vector_dim`
- `created_at` (ISO-8601)
- `tags` (array)
- `source` (`cli|agent`)

If any required metadata is unavailable, command must fail with actionable error.

---

## 6) Architecture Constraints (Local vs Managed)

### 6.1 Local mode

- Must run without auth, billing, or managed control plane dependencies.
- User retains key custody and decryption authority.
- Offline-first behavior is required.

### 6.2 Managed mode

- Auth gate is enforced before managed-only commands.
- Subscription/policy checks are explicit.
- Managed key delegation must remain policy-controlled.
- Canonical subscription model (must remain consistent with `SPECIFICATION.md`):
  - €9/month base includes 3 agents and 3 GB managed storage.
  - +€9/month per additional 3-agent block (+3 GB storage per block).
- Enforce security-aware usage controls for managed billing/storage APIs:
  - rate-limit high-risk operations (auth retries, subscription mutations, sync bursts),
  - reject over-quota writes with actionable upgrade guidance,
  - never bypass quota checks based on client-provided counters.

### 6.3 Separation rule

- Local logic cannot silently depend on managed services.
- Managed logic cannot weaken local cryptographic guarantees.

---

## 7) Coding Standards for Agent Sessions

1. **Atomic changes only**: one coherent feature/fix per commit.
2. **No hidden side effects**: avoid unrelated refactors in same change.
3. **Deterministic behavior**: avoid nondeterministic output formats.
4. **Type clarity**: add/maintain type hints for public functions.
5. **Error handling**: raise structured exceptions, user-facing command messages remain actionable.
6. **Security-first logging**: redact secrets and plaintext.
7. **Backward-safe command evolution**:
   - deprecate before removal,
   - keep aliases when possible.
8. **Test discipline**:
   - validate normal path,
   - validate empty/input boundary,
   - validate integrity failure path.

---

## 8) Repository Hygiene Rules

- Keep only active CLI/local-core artifacts in active tree.
- Legacy/web/managed-dashboard assets must be archived out of active implementation paths.
- Approved markdown set for agent context:
  - `RULES.md`
  - `TASKS.md`
  - `SPECIFICATION.md`
  - `DESIGN.md`

---

## 9) Acceptance Checklist for Any New PR

- [ ] No web/dashboard references introduced
- [ ] Local mode path works without managed auth
- [ ] Managed mode commands enforce auth boundary
- [ ] Pricing/quota docs stay consistent with canonical model (€9 per 3 agents; +€9 per extra 3)
- [ ] Output contains base64 + SHA-256 + Merkle + metadata
- [ ] No secrets or plaintext leaks in logs or errors
- [ ] CLI UX remains deterministic for humans and machines
- [ ] Docs updated only within approved markdown set
