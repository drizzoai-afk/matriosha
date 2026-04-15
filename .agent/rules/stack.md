# Stack Constraints — Matriosha

**Priority:** HIGH  
**Enforcement:** Must follow unless explicitly overridden by Rizzo

---

## Allowed Technologies

### Core (Python)
- `cryptography` → AES-256-GCM encryption
- `argon2-cffi` → Argon2id key derivation
- `keyring` → OS-level key storage
- `fastembed` → Local vector embeddings
- `portalocker` → File locking
- `supabase-py` → Supabase client
- `struct` → Binary protocol packing
- `hashlib` → SHA-256 hashing
- `typer` or `click` → CLI interface (optional, future)

### Backend (Supabase)
- Postgres → Database (vaults, key_escrow, subscriptions, memory_vectors)
- Storage → Encrypted binary blocks
- Edge Functions (Deno/TypeScript) → Stripe webhooks, key recovery
- Auth → JWT validation (Clerk integration)
- pgvector → Optional cloud-based semantic search

### Frontend (Next.js)
- Next.js 15 + React 19
- Clerk → Authentication, MFA, Passkeys
- Zustand → State management
- Tailwind CSS → Styling
- shadcn/ui → UI components (if needed)
- Stripe Customer Portal → Subscription management

### Billing
- Stripe → $9/mo Pro tier, webhook automation

---

## Forbidden Technologies

### ❌ Do NOT Use
- **Fernet** for encryption (use AES-256-GCM instead)
- **SQLite** as primary database (use Supabase Postgres)
- **Firebase** or other non-Supabase backends
- **Auth0**, **Okta**, or other auth providers (use Clerk)
- **Pinecone**, **Weaviate**, or external vector DBs (use FastEmbed local + pgvector fallback)
- **FastAPI** backend (use Supabase Edge Functions instead)
- **Custom auth logic** (delegate to Clerk + Supabase Auth)
- **Redis** for caching (not needed in MVP, add later if required)
- **Docker** containers (deploy directly to Vercel for dashboard, Supabase for backend)

---

## Version Constraints

### Python
- Minimum: Python 3.12
- Pin all dependencies in `requirements.txt`:
  ```txt
  cryptography==42.0.0
  argon2-cffi==23.1.0
  keyring==25.0.0
  fastembed==0.3.0
  portalocker==2.8.0
  supabase==2.5.0
  ```

### Node.js
- Minimum: Node 20 LTS
- Next.js 15.x
- React 19.x

### Supabase
- Use latest stable CLI version
- Edge Functions: Deno 1.40+

---

## Architecture Decisions (Locked)

### 1. Local-First Storage
- Primary storage: Local SSD (<100ms recall)
- Cloud storage: Supabase Storage (backup/sync only)
- Never reverse this priority

### 2. Zero-Knowledge Design
- Supabase sees only encrypted blobs + Merkle Root hash
- Never send plaintext data to cloud
- Never store encryption keys on server (except Shamir shard encrypted with Platform Master Key)

### 3. Clerk → Supabase JWT Handshake
- Clerk generates JWT with user ID (`sub` claim)
- Supabase validates JWT and applies RLS based on `auth.uid()`
- Never bypass this flow with custom auth tokens

### 4. Two-Stage Recall
- Stage 1: FastEmbed vector search (local, finds Leaf IDs)
- Stage 2: Fetch + verify Merkle proof + decrypt (only relevant blocks)
- Never fetch all blocks at once (defeats token efficiency)

### 5. Binary Protocol Agnosticism
- 128-bit header allows metadata access without decryption
- Works with any LLM (model-agnostic)
- Never change header structure without version bump + backward compatibility

---

## When to Deviate

These constraints can be overridden ONLY if:
1. Rizzo explicitly requests a different technology
2. A critical security vulnerability is discovered in an allowed dependency
3. Performance testing proves a constraint is blocking MVP launch

**Always ask before deviating.**
