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

### 2.2 Managed mode
- Subscription-gated
- CLI-native authentication required
- Managed policy/sync integration enabled
- Delegated key workflows under managed controls

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
│   ├── login
│   ├── logout
│   ├── whoami
│   └── switch
├── billing              # managed mode
│   ├── status
│   ├── subscribe
│   └── cancel
├── vault
│   ├── init
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
├── mcp_server.py
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
- Output format deterministic in `--json`
- No web architecture dependencies in active code tree
- Security and integrity checks enforced on memory operations
