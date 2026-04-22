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
│   └── cancel
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
└── completion
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
- `billing cancel` schedules cancellation at period end and must display effective cancellation date.

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
- Stripe failures MUST include safe hints such as `stripe_code`/`request_id` (no secrets).
- Supabase failures MUST include safe hints such as `http_status`/`sqlstate`/`rls_policy` (no tokens).
- Python/runtime and hardware/connection issues (disk full, keyring unavailable, filesystem permissions, timeouts) MUST map to `SYS` or `NET` with remediation guidance.

---

## 4. Memory Data Contract

### 4.1 Transport
- Canonical payload: **binary**
- Exchange format: **base64**

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
