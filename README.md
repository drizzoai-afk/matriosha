# Matriosha

**Secure Agentic Memory Layer** — Cryptographic memory for AI agents with zero-knowledge cloud sync.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize vault (generates encryption key)
python -c "from core.security import generate_salt, derive_key; salt = generate_salt(); print(f'Salt: {salt.hex()}')"

# Run tests
pytest tests/ -v
```

## Architecture

- **P1 Security:** AES-256-GCM + Argon2id KDF + OS keyring
- **P2 Binary Protocol:** 128-bit header with ternary logic + importance flags
- **P3 Merkle Tree:** Proof-of-Inclusion for tamper detection
- **P4 Brain:** FastEmbed local vector search + two-stage recall
- **P5 Adapter:** Hybrid local/Supabase storage sync
- **P6 CLI:** Typer-based interface (`init`, `remember`, `recall`, `sync`)
- **P7 Supabase:** RLS-enforced Postgres + Storage buckets
- **P8 Dashboard:** Next.js + Clerk auth + integrity UI
- **P9 Monetization:** Stripe webhooks + $9/mo key escrow

## Security

- OWASP Top 10 hardened
- Row Level Security on all Supabase tables
- Zero-knowledge design (server never sees plaintext)
- Context quarantine prevents prompt injection

See `.agent/rules/security.md` for detailed guardrails.

## Development

Generated via Abacus CLI with Qwen 3.6 Plus (build) + Gemma 4 (audit).

Full spec: `SPEC.md`  
Agentic context: `.agent/CONTEXT.md`
