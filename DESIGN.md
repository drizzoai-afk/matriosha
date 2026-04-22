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
  next: run `matriosha vault verify --repair-plan`
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
