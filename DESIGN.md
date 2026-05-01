# Matriosha v2 — DESIGN.md

Status: **Approved CLI design baseline for future implementation sessions**.

---

## 1. Design Intent

Design for two audiences simultaneously:
- **Hardcore coders** (predictable grammar, automation-safe output)
- **Vibe coders** (clear defaults, status-rich UX, low setup friction)

Visual and interaction tone:
- Daytona-inspired launcher density
- Minimal noise, high legibility
- Explicit mode/status presentation

---

## 2. ASCII Identity (CLI)

```text
            1010101010101
         1010┌─────────┐0101
       1010  │101010101│ 0101
      1010 ┌─┴─────────┴─┐ 0101
     1010  │ 01010101010 │ 0101
     1010  │ ┌─────────┐ │ 0101
     1010  │ │101010101│ │ 0101
     1010  │ └─────────┘ │ 0101
      1010 └─────────────┘ 0101
       1010    1010101    0101
          10101010101010101
              MATRIOSHA
```

Rules:
- Keep mono-space alignment exact in docs/help.
- Do not add faces/emoji/decorative variants.
- Support `--plain` fallback without box art.

---

## 3. Primary Interface Layouts

### 3.1 Launcher-style home (`matriosha` with no args)

```text
┌────────────────────────────────────────────────────────────────────┐
│ MATRIOSHA v2                                                      │
│ mode: local | profile: default | vault: ready | integrity: ✓      │
├────────────────────────────────────────────────────────────────────┤
│ Quick Actions                                                     │
│  1) memory remember      2) memory recall      3) vault verify    │
│  4) mode set managed     5) status             6) doctor          │
├────────────────────────────────────────────────────────────────────┤
│ Recent Operations                                                 │
│ - [ok] remember m_01 sha256=... merkle=...                        │
│ - [ok] recall q="meeting notes" top_k=5                           │
└────────────────────────────────────────────────────────────────────┘
```

### 3.2 Success output pattern

```text
✓ memory stored
  id: m_20260422_0001
  sha256: <64-hex>
  merkle_leaf: <hex>
  merkle_root: <hex>
```

### 3.3 Error output pattern

```text
✗ integrity verification failed
  cause: merkle_root mismatch against local vault state
  next: run `matriosha vault verify --deep`
```

### 3.4 Interactive launcher requirements (P6.1)

The launcher (`matriosha` with no args) is the **first navigation surface** and MUST expose the full command system.

Requirements:
- Main menu must show **all command groups** without requiring `--help`.
- Commands must be organized by category:
  - **Local:** memory, vault, status, doctor
  - **Managed:** auth, billing, vault sync
  - **Agents:** token, agent
  - **Settings:** mode, profile/config, completion
- No hidden commands in launcher-only flows.
- Include clear keyboard navigation help (`↑/↓`, `Enter`, `/`, `?`, `q`) in footer.
- A dedicated "All commands" view must list every supported `<group> <verb>` from the live CLI command map.

### 3.5 Error Handling standards

#### Error taxonomy (mandatory)
All user-facing failures MUST map to a category and a stable code.

- **Authentication errors** (`AUTH`): login failures, token expiry, Supabase auth failures.
- **Network errors** (`NET`): DNS/TLS failures, timeouts, unreachable APIs, flaky connectivity.
- **Validation errors** (`VAL`): invalid flags, malformed IDs, unsupported values.
- **Storage errors** (`STORE`): local vault read/write issues, database/transaction failures.
- **Payment errors** (`PAY`): Stripe checkout/card/webhook/subscription failures.
- **Quota errors** (`QUOTA`): storage cap exceeded, agent limit reached, rate-limit exhaustion.
- **Runtime/system errors** (`SYS`): Python runtime/import errors, keyring unavailable, disk full, filesystem permissions, clock or hardware/OS constraints.

#### Error message format (mandatory)
Human-readable errors must use simple, non-jargon language and include:
1. **What failed** (plain sentence)
2. **Category + code** (e.g., `PAY-002`, with exit code)
3. **What user can do next** (actionable fix)
4. **Debug hint** (short provider/context clue)

Template:

```text
✖ <plain failure title>
  category: <CATEGORY>  code: <CAT-###>  exit: <N>
  fix: <concrete next action>
  debug: <provider hint or request id, no secrets>
```

#### Stripe/Supabase debugging hints (required)
- Stripe errors should include one of: `stripe_code`, `payment_intent`, `request_id` (never secret keys).
- Supabase errors should include one of: `http_status`, `sqlstate`, `rls_policy`, `trace_id` (never tokens).
- Connection/system errors should include one of: `endpoint`, `timeout`, `os_error`, `errno`, `free_disk_bytes` when available.

#### Good vs bad examples

**Stripe payment failed**

Bad:
```text
Error 500 from Stripe.
```

Good:
```text
✖ Payment could not be completed
  category: PAY  code: PAY-002  exit: 40
  fix: verify your card details or retry with another payment method.
  debug: stripe_code=card_declined request_id=req_1234
```

**Stripe invalid API key**

Bad:
```text
Unauthorized.
```

Good:
```text
✖ Billing is temporarily unavailable
  category: PAY  code: PAY-001  exit: 40
  fix: run `matriosha doctor` and set STRIPE_SECRET_KEY in env or GSM.
  debug: stripe_code=invalid_api_key endpoint=/billing/checkout
```

**Supabase connection failure**

Bad:
```text
Could not connect.
```

Good:
```text
✖ Could not reach managed storage
  category: NET  code: NET-001  exit: 40
  fix: check internet/VPN and retry `matriosha auth whoami`.
  debug: endpoint=supabase timeout=10s
```

**Supabase auth expired**

Bad:
```text
Forbidden.
```

Good:
```text
✖ Session expired
  category: AUTH  code: AUTH-002  exit: 20
  fix: run `matriosha auth login` to refresh your session.
  debug: http_status=401 provider=supabase
```

---

## 4. Command Design Constraints

- Grammar stays `matriosha <group> <verb>`.
- Prefer stable nouns; avoid command churn.
- New commands require:
  1) help text,
  2) `--json` parity,
  3) deterministic exit code mapping.

Managed-only commands (`auth`, `billing`, parts of `sync`) must fail fast in local mode with actionable guidance.

Billing UX must reflect the managed model documented in `README.md` and this design document:
- Base €9/month = 3 agents + 3 GB managed storage
- +€9/month per additional 3 agents (+3 GB per block)
- `billing status` should display: active plan price, current agent quota, used/remaining storage, and next renewal date.

### 4.1 Auth + vault UX flow constraints

#### Local mode
- User explicitly initializes key material with `matriosha vault init`.
- Passphrase/key lifecycle messaging remains explicit and user-controlled.

#### Managed mode
- First successful `matriosha auth login` auto-provisions managed key material if absent.
- Wrapped managed key material is automatically stored in Supabase Vault.
- No `vault init` step is shown for managed onboarding.
- No password/passphrase UX is shown for managed key custody.
- Post-auth commands (`memory`, `vault sync`, `token`, `agent`) run with transparent crypto behavior.

### 4.2 Managed first-time journey (must be documented in help/output)
1. `matriosha auth login` (first managed login)
2. System auto-generates managed keys
3. Keys are stored in Supabase Vault
4. User never sees or handles key material
5. Crypto operations remain transparent thereafter

### 4.3 Quota warning UX (managed mode)

#### Thresholds and behavior
- Soft warning starts at **80%** of available cap (base plan example: **2.4 GB / 3.0 GB**).
- Hard limit at **100%** (base plan: **3.0 GB / 3.0 GB**) blocks additional writes until storage is reduced or plan is upgraded.

#### Mandatory warning card contents
Quota warning/failure surfaces must display:
- Current usage + cap + percent used
- Storage breakdown by category (raw memories, compressed parents, vector/index metadata)
- Immediate next command suggestions

#### Mandatory action prompt (exactly 3 options)
When 80%+ warning or 100% hard limit is reached, prompt must offer:
1. **Compress** (`matriosha compress`): run dedup compression flow
2. **Delete** (`matriosha delete ...`): run filtered bulk delete flow
3. **Upgrade** (`matriosha billing upgrade`): add one 3-agent pack (+3 GB)

#### Upgrade flow integration
- Upgrade option must launch the existing Stripe-backed billing flow from `billing upgrade`.
- UX must show pending checkout state and then refresh quota panel after success.
- Post-upgrade dashboard must explicitly show updated storage cap and remaining space.

---

## 5. JSON Output Design

Machine mode (`--json`) must emit only structured output.

```json
{
  "status": "ok|error",
  "operation": "memory.remember",
  "data": {
    "memory_id": "...",
    "encoding": "base64",
    "hash_algo": "sha256",
    "sha256": "...",
    "merkle_leaf": "...",
    "merkle_root": "...",
    "mode": "local|managed",
    "created_at": "ISO-8601",
    "tags": []
  },
  "error": null
}
```

On failure, `error` is populated and `status` = `error`.

---

## 6. Accessibility & Scriptability

- Color is additive, never required for understanding.
- `--plain` removes heavy formatting for logs/CI.
- `--json` is stable for automation pipelines.
- All examples in help/docs must include copy-paste-safe commands.

---

## 7. Design Anti-Patterns (Do Not Introduce)

- Browser-driven auth in this repo
- Web/dashboard-specific visual guidance
- Verbose success spam for default mode
- Mixing human prose and JSON in same output stream
- Hidden mode switching or implicit managed fallback
- Managed-mode key/password prompts that expose crypto complexity to end users

## Semantic interpreter support

Matriosha recall returns bounded agent-ready semantic JSON.

Rich built-in extraction currently supports:

- `.txt`
- `.md`, `.markdown`
- `.json`
- `.csv`, `.tsv`
- `.pdf`
- `.png`, `.jpg`, `.jpeg`, `.bmp`, `.gif`, `.webp`, `.tiff`, `.tif`
- `.docx`
- `.xlsx`

Legacy or proprietary formats such as `.doc`, `.odt`, `.xls`, `.msg`, `.dwg`, and archives such as `.zip`, `.tar`, `.gz` are handled as safe binary fallback envelopes unless a dedicated decoder plugin is installed.

Fallback envelopes are still valid interpreter output. They preserve safe metadata, bounded previews, and warnings, but they do not claim full text/table extraction.
