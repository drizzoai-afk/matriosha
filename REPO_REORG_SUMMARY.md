# Repository Reorganization Summary

Date: 2026-04-22
Repository: `drizzoai-afk/matriosha`

## 1) Duplicate cleanup completed

Cleanup policy applied:
- Remove `*.archived` files when archived duplicates existed.
- Remove PDF variants and keep Markdown (`.md`) canonical docs only.
- Keep active non-duplicate source files unchanged.

### Removed duplicate/archive files
- `ARCHIVE/legacy_2026-04-22/.agent/CONTEXT.md.archived`
- `ARCHIVE/legacy_2026-04-22/.agent/commands/p1-p3-core.md.archived`
- `ARCHIVE/legacy_2026-04-22/.agent/rules/security.md.archived`
- `ARCHIVE/legacy_2026-04-22/.agent/rules/stack.md.archived`
- `ARCHIVE/legacy_2026-04-22/.agents/skills/aidesigner-frontend/SKILL.md.archived`
- `ARCHIVE/legacy_2026-04-22/.agents/skills/aidesigner-frontend/references/api.md.archived`
- `ARCHIVE/legacy_2026-04-22/.agents/skills/aidesigner-frontend/references/frontend-rubric.md.archived`
- `ARCHIVE/legacy_2026-04-22/AGENTS.md.archived`
- `ARCHIVE/legacy_2026-04-22/AUDIT_FINAL_v1.2.md.archived`
- `ARCHIVE/legacy_2026-04-22/AUDIT_REPORT.md.archived`
- `ARCHIVE/legacy_2026-04-22/CLAUDE.md.archived`
- `ARCHIVE/legacy_2026-04-22/README.md.archived`
- `ARCHIVE/legacy_2026-04-22/SPEC.md.archived`
- `ARCHIVE/legacy_2026-04-22/docs/AUDIT_COMPLETE.md.archived`
- `ARCHIVE/legacy_2026-04-22/docs/MCP_INTEGRATION.md.archived`
- `ARCHIVE/legacy_2026-04-22/docs/REPOSITORY_ANALYSIS_AND_REFACTOR_PLAN.md.archived`
- `ARCHIVE/legacy_2026-04-22/docs/TEST_REPORT.md.archived`
- `ARCHIVE/legacy_2026-04-22/docs/architecture-dump.md.archived`
- `ARCHIVE/legacy_2026-04-22/docs/business-logic.md.archived`
- `ARCHIVE/legacy_2026-04-22/docs/REPOSITORY_ANALYSIS_AND_REFACTOR_PLAN.pdf`
- `ATOMIC_PROMPTS.pdf`
- `DESIGN.pdf`
- `PRICING_MODEL_VERIFICATION.pdf`
- `RULES.pdf`
- `SPECIFICATION.pdf`
- `TASKS.pdf`

### Post-cleanup validation
- Tracked `*.archived`: **0**
- Tracked `*.pdf`: **0**

## 2) Branch reorganization completed

### Before
- Local branches: `analysis/repo-audit`, `main`
- Remote branches: `main`

### Actions performed
1. Fetched/pruned remote refs.
2. Renamed local `main` -> `legacy`.
3. Pushed `legacy` to remote.
4. Renamed local `analysis/repo-audit` -> `main`.
5. Force-pushed new `main` to `origin/main`.
6. Deleted remote `analysis/repo-audit` branch.

### After
- Local branches: `main`, `legacy`
- Remote branches: `main`, `legacy`
- Remote `main` now points to commit `88f146be4afd17a6427432bb581732e841fdb035`
- Remote `legacy` points to commit `9996c38f6700702105ecc233359b5ac71de231e4`

## 3) Atomic prompt context update completed

`ATOMIC_PROMPTS.md` updated with canonical branch guidance:
- `main` = active/canonical branch for all new work.
- `legacy` = historical reference only.
- Agents should implement from `main`, and only diff against `legacy` for context.

## 4) Default branch guidance (GitHub web UI)

If manual confirmation is needed:
1. Open: `https://github.com/drizzoai-afk/matriosha`
2. Go to **Settings** -> **Branches**.
3. Under **Default branch**, choose `main`.
4. Save/update.

## 5) Guidance for future AI agent sessions

Use this workflow in every new session:
1. Clone repo and checkout `main`:
   - `git clone https://github.com/drizzoai-afk/matriosha.git`
   - `cd matriosha`
   - `git checkout main`
2. Read canonical docs first:
   - `RULES.md`
   - `SPECIFICATION.md`
   - `DESIGN.md`
   - `TASKS.md`
   - `ATOMIC_PROMPTS.md`
3. Treat `legacy` as read-only history for comparison only.
4. Do all new implementation and PR work from `main`.

## 6) State confirmation

- `main` contains the cleaned, current documentation and active implementation context.
- `legacy` preserves prior branch state as historical reference for the old/hybrid setup.
