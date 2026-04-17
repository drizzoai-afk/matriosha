# Matriosha Dashboard

This directory contains the Next.js 15 dashboard for Matriosha.

## Tech Stack
- **Framework:** Next.js 15 (App Router) + React 19
- **UI:** Tailwind CSS + shadcn/ui
- **Auth:** Clerk
- **State:** Zustand
- **Design Reference:** Aidesigner.ai (via MCP)

## Development
```bash
npm install
npm run dev
```

## Production Notes
- **Secrets:** Do not commit `.env.local`. Use Google Secrets Manager in production.
- **Auth:** Ensure `CLERK_SECRET_KEY` is set in the deployment environment.
- **Supabase:** RLS policies must be active before deploying the dashboard.
# Trigger redeploy
