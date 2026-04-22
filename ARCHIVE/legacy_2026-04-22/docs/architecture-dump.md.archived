# Matriosha — Architecture Dump (12-14 April 2026)

_Raw brainstorming notes from Rizzo's sessions. To be organized into formal prompts._

---

## Core Concept

"Memory-as-a-Service" layer for AI agents — secure, sovereign, instant long-term autobiography.

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Brain / OS | Python | Local runtime — encryption + logic |
| Identity | Clerk | Passkey/MFA auth + session management |
| Data Engine | Supabase | PostgreSQL (Merkle Roots) + S3 Storage (binary blocks) |
| Memory Format | Custom Binary | 128-bit headers + AES-GCM encrypted bodies |
| Recall (Fast) | FastEmbed | Local zero-knowledge vector search (Stage 1) |
| Recall (Secure) | Merkle Tree | Proof-of-Inclusion integrity (Stage 2) |
| Web / Dashboard | Next.js | $9/mo storefront, vault health, key recovery |
| Monetization | Stripe | Subscription billing for Safety Net |

## The 8 Prompts (P1-P8)

### P1: Core (OS)
- AES-256-GCM for data blocks
- Argon2id key derivation (unique 16-byte salt per vault)
- Python keyring for session key management — never store raw keys on disk
- Merkle Tree index — every .bin hashed, index.json stores Root
- Any mismatch → SecurityIntegrityError
- Atomic Writes (temp file → rename) to prevent corruption
- portalocker for file-locking concurrency

### P2: Security
- Argon2 KDF + OS-level keyring integration
- Password → Argon2 → 256-bit AES key (user never sees raw key)
- Shamir's Secret Sharing for key recovery
- Session key stays in protected memory (asked once per session)
- Passkey option via Clerk (biometric unlock → Secure Enclave → Argon2 key)

### P3: Managed Backend (Key Escrow)
- Supabase with RLS (Row Level Security)
- Clerk JWT → Supabase auth handshake
- vault_keys table: encrypted Master Key stored using platform Master Key
- $9/mo "Safety Net" for key recovery via authenticated login
- Edge Functions (Deno) for Stripe webhooks

### P4: Brain (OS) — Two-Stage Recall
- Stage 1: FastEmbed local semantic search → returns Leaf_IDs
- Stage 2: Fetch binary block → unpack header → check importance → verify Merkle Proof → decrypt
- Vector index stores ONLY embeddings + Leaf_IDs (no plaintext)
- Mapping table: [Vector_ID] ↔ [Leaf_ID]
- Success metric: answer "what was uncertain yesterday?" by filtering Logic_Flag=10 without full history

### P5: Adapter (Hybrid Storage)
- Unified interface: get(), put(), sync()
- Modes: "local", "managed", "hybrid"
- Always save locally first (ULL)
- If managed/hybrid → async push to Supabase
- Fetch: local first → if not found → pull from Supabase → cache locally
- Conflict resolution: local always wins (via Merkle Root comparison)
- Upgrade path: free (local) → $9/mo flip to "hybrid"

### P6: Web UI (Dashboard)
- Next.js + Clerk + Zustand/React Query
- "Sovereign Dashboard" — not a chat app, a Control Plane
- Integrity Heatmap (Merkle Tree visualization, green = synced)
- Recall Audit Log (when Agent touches memory)
- Emergency Recovery Interface (key reconstruction via Clerk + Escrow)
- "Bitcoin Vault" aesthetic — high-security feel

### P7: Monetization
- Stripe webhooks → provision isolated Supabase storage buckets
- Edge Function: payment → update user_tier in Postgres
- Adapter polls user_tier → starts syncing if paid
- One-click: pay → cloud backup begins automatically

### P8: Integrity (The Handshake)
- Local update → change Merkle Root
- Challenge: ask Supabase "what's the current Root?"
- Compare: if match → upload new blocks + new Root
- Mismatch → alert user: "Data Integrity Mismatch"
- Postgres function: sync_merkle_root() — atomic compare-and-swap
- Multi-device conflict resolution
- Real-time validation on every block request

## Binary Protocol

128-bit (16-byte) header:
- 8 bits: version
- 2 bits: ternary logic (00=False, 01=True, 10=Uncertain)
- 2 bits: importance (0-3, Low to Critical)
- 4 bits: reserved
- 32 bits: Unix timestamp
- 80 bits: truncated Merkle leaf hash

```python
import struct, time

def pack_header(logic_state, importance, version=1):
    meta_byte = (logic_state << 6) | (importance << 4)
    timestamp = int(time.time())
    fake_hash = b'\xab' * 10
    return struct.pack(">B B I 10s", version, meta_byte, timestamp, fake_hash)

def unpack_header(header_bytes):
    v, meta, ts, h = struct.unpack(">B B I 10s", header_bytes)
    return {
        "version": v,
        "logic": (meta >> 6) & 0b11,
        "importance": (meta >> 4) & 0b11,
        "timestamp": ts,
        "leaf_id": h.hex()
    }
```

## Key Concepts

- **Zero-Knowledge:** Server hosts data but can't read it. "You sell the parking lot, but the user has the only car keys."
- **AES-GCM:** Encryption + authentication tag. If a single bit changes, decryption fails.
- **Argon2:** GPU-resistant KDF. Password → long complex key.
- **Key Escrow:** $9/mo service. User encrypts their key with platform Master Key. Only user (via Clerk) can authorize release.
- **Context Quarantine:** Historical data wrapped in XML tags to prevent indirect prompt injection.
- **Token Pruning:** Summarize old/long memories to save LLM costs.
- **Ternary Logic:** Facts tagged as True/False/Uncertain — agent can filter by uncertainty.
- **Atomic Writes:** Write temp file → rename. Prevents corruption on crash.
- **Shamir's Secret Sharing:** Key split into N parts, need K to reconstruct. Local piece + Escrow piece = full key.

## Supabase Schema

```sql
create table vaults (
    id uuid primary key default uuid_generate_v4(),
    user_id text not null,
    merkle_root text not null,
    vault_version int default 1,
    last_sync timestamp with time zone default now(),
    constraint unique_user_vault unique(user_id)
);

alter table vaults enable row level security;
create policy "Users can only see their own vault"
    on vaults for all using (auth.uid()::text = user_id);
```

```sql
CREATE OR REPLACE FUNCTION sync_merkle_root(
    provided_old_root TEXT, new_root TEXT, user_id UUID
) RETURNS BOOLEAN AS $$
DECLARE current_stored_root TEXT;
BEGIN
    SELECT merkle_root INTO current_stored_root FROM user_vaults WHERE id = user_id;
    IF current_stored_root IS NULL OR current_stored_root = provided_old_root THEN
        UPDATE user_vaults SET merkle_root = new_root, last_sync = NOW() WHERE id = user_id;
        RETURN TRUE;
    ELSE
        RETURN FALSE;
    END IF;
END;
$$ LANGUAGE plpgsql;
```

## Development Strategy

- Build with Qwen 3.6 Plus (1M context window, agentic coding)
- Harden with Claude Opus 4.6 or Gemma 4 (security audit)
- Execute on Abacus Claw (persistent Linux, multi-model routing)
- Static analysis: Snyk / SonarQube alongside AI audits

## Challenges

1. Forward Compatibility — binary schema changes must not break old memories
2. UX Friction — sovereign = user responsible. Lost password + lost recovery = lost data
3. Hardware Dependency — FastEmbed + AES-GCM local perf varies by device
4. Token Efficiency — index approach can be 99.2% cheaper than full RAG
5. SHA-256 as prompt injection defense — tamper-evident seal on every memory

## Benchmarks (Targets)

- Latency: <0.20s end-to-end Time to Memory
- Merkle Proof overhead: <5ms
- Cold Start: <100ms (load Root + last 50 leaves)
- Retrieval accuracy: F1 ~0.94 (LoCoMo benchmark)

## GDPR / EU AI Act

- Privacy by Design: embeddings only (Stage 1), encrypted PII (Stage 2)
- Right to Erasure: dashboard delete function
- AES-GCM at rest + TLS in transit
- If used for recruiting/HR → High-Risk under Annex III
- Managed provider = responsible for compliance lifecycle

---

_Saved from WhatsApp brainstorming session 12-14 April 2026_
