# Pricing Model Verification — Matriosha

Date: 2026-04-22
Repository: `/home/ubuntu/github_repos/matriosha`

## Objective
Verify that the subscription pricing model is consistently documented across project Markdown files, and update any incorrect/incomplete references.

Canonical model to enforce:
- Base: **€9/month** for **3 agents**
- Scaling: **+€9/month** for every additional **3 agents** (6 agents = €18, 9 agents = €27)
- Storage cap: must be explicitly documented

## What Was Checked
Scanned all relevant markdown docs in repo, including:
- `SPECIFICATION.md`
- `DESIGN.md`
- `ATOMIC_PROMPTS.md`
- `RULES.md`
- `TASKS.md`
- `CHANGELOG.md`

## Findings (Before Updates)
1. **Model was incomplete/inconsistent**:
   - Pricing was explicitly stated only in `ATOMIC_PROMPTS.md` (single-tier `€9/mo` wording).
   - No consistent mention of scalable +€9 per additional 3 agents across the canonical docs.
2. **Storage cap was missing**:
   - No explicit managed storage cap tied to subscription blocks in the main docs.
3. **CLI subscription semantics were underspecified**:
   - No canonical statement in the core spec for how `billing subscribe/status/cancel` should expose quota/cap information.
4. **Stripe task detail gap**:
   - Prompting around Stripe checkout did not encode multi-block quantity logic (3-agent blocks) end-to-end.

## Proposed Storage Cap (Adopted)
**3 GB encrypted managed storage per 3-agent billing block**.

Examples:
- 3 agents (base): 3 GB
- 6 agents: 6 GB
- 9 agents: 9 GB

### Why this cap
- Fits low-cost managed pricing while leaving room for encrypted payloads + metadata + pgvector indexes.
- Supports predictable quota math for Stripe quantity-based billing.
- Helps enforce abuse-resistant security controls (quota checks + write throttling) without weakening local mode.

## Files Updated

### 1) `SPECIFICATION.md`
- Added canonical managed pricing section:
  - €9/month base for 3 agents
  - +€9/month per extra 3-agent block
  - storage cap scaling (3 GB per block)
- Added billing command semantics section requiring quota/cap visibility in billing commands.

### 2) `DESIGN.md`
- Added billing UX requirements for displaying:
  - plan price
  - agent quota
  - storage usage/cap
  - renewal date
- Synced UX wording to scalable pricing model.

### 3) `RULES.md`
- Added canonical pricing/quota rule under managed mode.
- Added security-aware enforcement expectations (rate limiting, over-quota handling).
- Added acceptance checklist item requiring pricing/quota doc consistency.

### 4) `ATOMIC_PROMPTS.md`
- Updated P4.5 title and pricing language from single-tier `€9/mo` to scalable model.
- Added Stripe catalog expectations for base/add-on plan IDs.
- Updated `billing subscribe` prompt behavior to support `--agent-pack-count <n>`.
- Updated checkout flow to use quantity-based pricing blocks and expected quota/cap calculations.
- Updated billing test expectations for scalable tiers and validation.
- Updated managed client prompt signature for checkout to include `quantity`.
- Expanded subscriptions schema prompt fields to include `plan_code`, `unit_price_cents`, `agent_quota`, and `storage_cap_bytes`.
- Updated Stripe webhook task description to include quota/cap field updates.

### 5) `CHANGELOG.md`
- Added entry documenting pricing model documentation alignment.

## Final Verification Status
- **Before**: ❌ Not fully correct/incomplete.
- **After**: ✅ Canonical pricing model and storage cap are now consistently documented across relevant markdown docs.

## Notes
- This verification/update is documentation-focused; no runtime billing code was modified in this task.
