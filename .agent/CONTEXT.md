# Matriosha — Agentic Coding Context

**Project:** Secure Agentic Memory Layer — Binary Standard for AI Memory  
**Stack:** Python 3.11+ (core + CLI), Supabase (backend), Next.js 15 (dashboard), Clerk (auth)  
**Primary Model for Generation:** Qwen 3.6 Plus (via Abacus RouteLLM)  
**Hardening Model:** Claude Opus 4.6 (security audit)  
**Last Updated:** 2026-04-15

---

## 1. Project Overview

Matriosha is a **standardized binary memory format** for AI agents — like MP3 for audio or JPEG for images. It combines:
- **Local encryption:** AES-256-GCM + Argon2id KDF
- **Verifiable integrity:** Merkle Tree with Proof-of-Inclusion
- **Managed cloud sync:** Supabase + Clerk + Stripe ($9/mo)
- **Token efficiency:** Binary Protocol 128-bit header + Two-Stage Recall
- **Seamless CLI & MCP:** Typer-based interface and Model Context Protocol for vibe coders (`init`, `remember`, `recall`, `sync`)

**Key principle:** Local-first. Cloud is backup/sync only. User owns the keys. Binary header = model-agnostic lingua franca.

**Business Logic:** 
- **Standard ($9/mo):** Key escrow, multi-device sync, integrity alerts, 2GB Hot + Auto-Archive to Cold (R2).
- **Enterprise:** Custom limits, dedicated support, SLA guarantees.
- **Overage:** €6/GB for Hot storage, €3/GB for Cold storage beyond included limits.

---

## 2. Tech Stack (Non-Negotiable)

### Core (Python)
- `cryptography` → AES-256-GCM
- `argon2-cffi` → Argon2id KDF
- `keyring` → OS-level key storage
- `fastembed` → Local vector embeddings (BAAI/bge-small)
- `portalocker` → File locking for concurrent access
- `supabase-py` → Supabase client
- `struct` → Binary protocol packing
- `hashlib` → SHA-256 hashing
- `typer` → CLI framework (P6)
- `tomli-w` → Config file writing (~/.matriosha/config.toml)
- `rich` → Terminal formatting (progress bars, colors)
- `boto3` → Cloudflare R2 integration (Cold Storage)
- `google-cloud-secret-manager` → Production secrets management

### Integrations (MCP)
- `mcp` → Model Context Protocol server for Cursor/Windsurf/Claude Code
- Tools: `search_memory`, `store_memory`

### CLI (P6)
- **Framework:** Typer (automatic type hints, less boilerplate than Click)
- **Commands:** `init`, `remember`, `recall`, `sync`, `verify`, `export`, `import`
- **Output modes:** Human-readable default, `--json` for agent parsing
- **Config file:** `~/.matriosha/config.toml` (vault path, mode, credentials)
- **Agent mode:** API key auth for headless agents (no Clerk interactive flow)
- **Pipe-friendly:** stdin/stdout support for Unix workflows

### Backend (Supabase)
- Postgres → vaults, key_escrow, subscriptions, memory_vectors tables
- Storage → Encrypted binary blocks (Hot Storage)
- Edge Functions (Deno) → Stripe webhooks, key recovery, auto-archiving logic
- RLS → Row Level Security on all tables

### Frontend (Next.js)
- Next.js 15 + React 19
- Clerk → Auth, MFA, Passkeys, JWT generation
- Zustand → State management
- Tailwind CSS + shadcn/ui → Styling & Components
- **Aidesigner MCP** → Design system reference for layout and visual structure
- **Matriosha Branding:** Dark theme, Cyan/Magenta accents, Monospace data fonts

### Billing & Storage
- Stripe → $9/mo Standard tier, webhook automation, metered overage billing
- Cloudflare R2 → Cold Storage for archived memories (~$0.015/GB)

---

## 3. Architecture Patterns

### 3.1 Cryptographic Flow
```
User Password → Argon2id(salt) → 256-bit Key → AES-256-GCM encrypt/decrypt
                    ↓
            Salt stored plaintext (unique per vault)
                    ↓
            Key never written to disk (keyring only)
```

### 3.2 Key Escrow (Shamir's Secret Sharing)
```
Encryption Key → Split in 2 shards:
  - Shard 1: Local device (encrypted with password)
  - Shard 2: Supabase key_escrow (encrypted with PLATFORM_MASTER_KEY)

Recovery: Clerk auth → fetch Shard 2 → combine with Shard 1 → reconstruct
```

### 3.3 Two-Stage Recall
```
User Query → FastEmbed embedding → Vector search → Top-K Leaf IDs
    ↓
For each Leaf ID:
  1. Fetch encrypted block (local, Hot, or Cold)
  2. Unpack header → check importance/logic (no decrypt yet)
  3. Verify Merkle Proof-of-Inclusion
  4. If valid: decrypt body → inject in <historical_data> tags
```

### 3.4 Tiered Storage Logic (Hot vs. Cold)
```
Save Memory:
  1. Write to Local SSD
  2. If Managed Mode:
     a. Check if Hot Storage > Limit (2GB Pro / 10GB Builder)
     b. If Full: Trigger Auto-Archive (move oldest 20% to R2)
     c. Upload new block to Supabase (Hot)

Fetch Memory:
  1. Check Local Cache → Hit? Return.
  2. Check Supabase (Hot) → Hit? Return & Cache.
  3. Check R2 (Cold) → Hit? Return & Cache. (Slower, ~2-5s)
```

---

## 4. Security Constraints (OWASP Top 10)

### CRITICAL — Never Violate These

1. **RLS Enforcement:** Every table MUST have `enable row level security` + policy with `auth.uid()::text = user_id` check. No exceptions.

2. **No Plaintext Keys on Disk:** Use Python `keyring` exclusively. Never write keys to files, env vars, or logs.

3. **AES-256-GCM Only:** Do not use Fernet, CBC, or other algorithms. GCM provides authenticated encryption (integrity + confidentiality).

4. **Argon2id Parameters:** `time_cost=3`, `memory_cost=64MB`, `parallelism=4`. Do not reduce for "performance".

5. **Context Quarantine:** All decrypted memory blocks MUST be wrapped in `<historical_data>` XML tags before LLM injection.

6. **Platform Master Key:** Never hardcoded. Always from environment variable `PLATFORM_MASTER_KEY`.

7. **SUPABASE_SERVICE_ROLE_KEY:** Never exposed to client. Only in Edge Functions server-side.

8. **Atomic Writes:** Always write to temp file → fsync → rename. Prevent corruption on crash.

9. **Merkle Verification:** Every fetch from Supabase/R2 MUST verify Proof-of-Inclusion before decrypt.

10. **Stripe Webhook Signature:** Always verify with `stripe.webhooks.constructEvent()` before processing.

---

## 5. File Structure

```
matriosha/
├── .agent/
│   ├── CONTEXT.md          # This file
│   ├── commands/           # Abacus CLI workflows (deploy, test, seed)
│   ├── rules/              # Guardrails (security, stack constraints)
│   └── skills/             # Reusable tasks (add-memory, verify-integrity)
├── mcp_server.py           # MCP Server for Cursor/Windsurf/Claude Code integration
├── cli/                    # P6: Typer-based CLI interface
│   ├── __init__.py
│   ├── main.py             # Typer app entry point
│   ├── commands/
│   │   ├── init.py         # matriosha init
│   │   ├── remember.py     # matriosha remember
│   │   ├── recall.py       # matriosha recall
│   │   ├── sync.py         # matriosha sync
│   │   ├── verify.py       # matriosha verify
│   │   ├── export_import.py# matriosha export/import
│   └── utils/
│       ├── output.py       # JSON/human formatter
│       └── config.py       # Config file loader (~/.matriosha/config.toml)
├── core/
│   ├── __init__.py
│   ├── security.py         # P1: AES-256-GCM + Argon2id KDF + keyring
│   ├── binary_protocol.py  # P2: 128-bit header packer/unpacker
│   ├── merkle.py           # P3: Tree construction + Proof verification
│   ├── brain.py            # P4: FastEmbed + Two-Stage Recall
│   └── adapter.py          # P5: Hybrid local/Supabase/R2 adapter
├── dashboard/              # P8: Next.js app
│   ├── app/
│   │   ├── page.tsx        # Dashboard home (Integrity Heatmap)
│   │   ├── recovery/       # Key recovery flow
│   │   └── api/            # API routes (Clerk webhook handlers)
│   ├── components/
│   │   ├── IntegrityStatus.tsx
│   │   ├── RecallLog.tsx
│   │   └── RecoveryWizard.tsx
│   └── lib/
│       ├── supabase.ts     # Supabase client with Clerk JWT
│       └── clerk.ts        # Clerk auth helpers
├── migrations/             # P7: Supabase SQL
│   ├── 001_create_tables.sql
│   └── 002_rls_policies.sql
├── edge-functions/         # P9: Deno functions
│   ├── stripe-webhook.ts
│   ├── key-recovery.ts
│   └── auto-archive.ts     # Logic to move Hot -> Cold
├── tests/
│   ├── test_security.py
│   ├── test_merkle.py
│   ├── test_protocol.py
│   └── test_cli.py
├── docs/
│   ├── business-logic.md   # Pricing, Tiers, Storage Strategy
│   └── architecture-dump.md
├── SPEC.md                 # Full technical specification
├── README.md
├── requirements.txt
├── pyproject.toml          # Build config + CLI entry point
└── .env.example
```

---

## 6. Development Workflow (Abacus CLI)

### Phase-by-Phase Execution

**P1-P3 (Core Crypto):** ✅ Done
```bash
# Already generated and committed to GitHub
# core/security.py, binary_protocol.py, merkle.py
```

**P4-P5 (Brain + Adapter):**
```bash
abacus generate core/brain.py --model qwen3.6-plus
abacus generate core/adapter.py --model qwen3.6-plus --context "docs/business-logic.md"
abacus test core/ --coverage 90%
```

**P6 (CLI Interface):** ✅ Done
```bash
# Generate CLI scaffold with Typer
abacus generate cli/main.py --model qwen3.6-plus --context "SPEC.md,.agent/CONTEXT.md"

# Install in dev mode
pip install -e .

# Test CLI
matriosha --help
matriosha init --local
matriosha remember "Test memory" --importance high
matriosha recall "test" --json
```

**MCP Integration:** ✅ Done
```bash
# Start MCP Server for AI Agents
python mcp_server.py

# Configure in Cursor/Windsurf
# See docs/MCP_INTEGRATION.md
```

**P7 (Supabase):**
```bash
# Apply migrations
supabase db push --db-url $SUPABASE_CONNECTION_STRING

# Verify RLS
psql $SUPABASE_CONNECTION_STRING -f scripts/verify_rls.sql
```

**P8 (Dashboard):**
```bash
cd dashboard
npm install
# Initialize shadcn/ui
npx shadcn@latest init

# Launch Codex ACP with Aidesigner MCP for design reference
# Focus: Vault Integrity UI, Storage Visualizer, Clerk Auth integration
```

**P9 (Monetization):**
```bash
# Deploy Edge Functions
supabase functions deploy stripe-webhook
supabase functions deploy key-recovery
supabase functions deploy auto-archive

# Test webhooks locally
stripe listen --forward-to localhost:54321/functions/v1/stripe-webhook
```

---

## 7. Testing Strategy

### Unit Tests (pytest)
- `test_security.py`: Verify AES-256-GCM encrypt/decrypt roundtrip, Argon2id key derivation consistency
- `test_merkle.py`: Verify Merkle Root changes when any leaf changes, Proof-of-Inclusion validation
- `test_protocol.py`: Verify header pack/unpack preserves all fields, forward compatibility
- `test_cli.py`: Verify CLI commands produce expected output, JSON format correct
- `test_adapter.py`: Verify Hot/Cold storage logic and auto-archiving triggers

### Integration Tests
- End-to-end: Create memory → sync to Supabase → fetch from new device → verify Merkle proof → decrypt
- Key Recovery: Simulate lost device → reconstruct key from Shamir shards → decrypt existing blocks
- Storage Tiering: Fill Hot storage past limit → verify auto-archive moves blocks to R2

### Security Tests
- RLS Bypass Attempt: Try to access another user's vault via manipulated JWT → should fail
- Prompt Injection: Inject malicious instruction in memory block → verify Context Quarantine prevents execution
- Tamper Detection: Modify encrypted block on Supabase → verify Merkle proof fails

---

## 8. Performance Targets

| Metric | Target | How to Measure |
|--------|--------|----------------|
| Local Recall (p50) | <100ms | `time.time()` before/after fetch+decrypt |
| Local Recall (p95) | <200ms | 95th percentile over 1000 requests |
| Hot Storage Recall | <500ms | Supabase download + verify + decrypt |
| Cold Storage Recall | <5s | R2 download + verify + decrypt |
| Merkle Proof Verify | <5ms | In-process timing |
| Token Efficiency | 99% reduction vs full RAG | Compare tokens used: Two-Stage vs naive context dump |

---

## 9. Common Pitfalls to Avoid

### ❌ Don't Do This
- Store encryption keys in `.env` files or database columns
- Use Fernet instead of AES-256-GCM (Fernet doesn't provide authenticated encryption)
- Skip Merkle verification on fetch from Supabase/R2 (defeats integrity guarantee)
- Expose `SUPABASE_SERVICE_ROLE_KEY` to client-side code
- Allow client-side writes to `key_escrow` table (only Edge Functions)
- Forget to wrap decrypted memories in `<historical_data>` tags
- Hardcode R2 credentials (use env vars)

### ✅ Do This Instead
- Use Python `keyring` for all key storage
- Enforce AES-256-GCM with explicit nonce + auth tag handling
- Verify Merkle Proof-of-Inclusion on EVERY fetch, no exceptions
- Use `service_role` key only in Edge Functions, validate user identity server-side
- Restrict `key_escrow` writes to Edge Functions with admin checks
- Always apply Context Quarantine before LLM injection
- Use `boto3` with temporary credentials for R2 access

---

## 10. Deployment Checklist

### Pre-Launch
- [ ] All tables have RLS enabled + policies verified
- [ ] `pip-audit` scan clean (no critical/high CVEs)
- [ ] `npm audit` clean for dashboard
- [ ] Stripe webhooks signature verification tested
- [ ] Key recovery flow end-to-end tested
- [ ] Merkle sync function handles conflicts correctly
- [ ] Context Quarantine prevents prompt injection
- [ ] Environment variables documented in `.env.example`
- [ ] Production build has no console.log of sensitive data
- [ ] Rate limiting enabled on Edge Functions (100 req/min per user)
- [ ] R2 bucket lifecycle policies configured for cost optimization

### Post-Launch Monitoring
- [ ] Supabase `pg_audit` logging active
- [ ] Edge Function error alerts configured (email/Slack)
- [ ] Stripe webhook failure monitoring
- [ ] Dashboard Recall Audit Log visible to users
- [ ] Merkle mismatch alerts trigger user notification
- [ ] Storage usage tracking per user (for billing/archiving)

---

## 11. References

- **SPEC.md:** Full technical specification with schema details
- **docs/business-logic.md:** Pricing tiers, storage strategy, and monetization
- **OWASP Top 10 2026:** https://owasp.org/www-project-top-ten/
- **Supabase RLS Docs:** https://supabase.com/docs/guides/auth/row-level-security
- **Clerk + Supabase Integration:** https://clerk.com/docs/integrations/databases/supabase
- **Argon2 RFC:** https://datatracker.ietf.org/doc/html/rfc9106
- **AES-GCM NIST Spec:** https://csrc.nist.gov/publications/detail/sp/800-38d/final
- **Cloudflare R2 Pricing:** https://www.cloudflare.com/products/r2/

---

**Context Version:** 1.2.0  
**Maintained by:** Nero ⚡ (Agency AI Operator)  
**Next Review:** After P6 CLI completion

