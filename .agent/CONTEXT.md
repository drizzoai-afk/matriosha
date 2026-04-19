# Matriosha - Project Context & State

**Last Updated:** 2026-04-18
**Status:** Deployed on Vercel (matriosha.in) - Auth Flow Debugging

## 📖 Mandatory Reading
Before proceeding with any development or debugging, **ALWAYS** read:
1.  `/home/ubuntu/agency/matriosha/SPEC.md` - The single source of truth for architecture and requirements.
2.  `/home/ubuntu/agency/matriosha/.agent/CONTEXT.md` - This file.

## 🏗️ Architecture Overview
*   **Frontend:** Next.js 15 (App Router), React 19, Tailwind CSS, Shadcn/UI.
*   **Auth:** Clerk (handling sessions and user management).
*   **Database:** Supabase (PostgreSQL) with Row Level Security (RLS).
*   **Storage:** Hybrid model — Supabase (Hot) + Cloudflare R2 (Cold).
*   **Billing:** Stripe (Subscriptions + Overage via Invoice Items).
*   **Deployment:** Vercel (Production) + GitHub (drizzoai-afk/matriosha).

## 🚀 Current State (2026-04-18)
### ✅ Completed
*   **UI/UX:** Redesigned Landing Page (`/`) and Protected Dashboard (`/dashboard`) with "Aidesigner" aesthetic.
*   **DB Schema:** `subscriptions`, `storage_usage`, and `user_billing_status` view implemented in Supabase.
*   **Stripe Integration:** Webhook endpoint created to sync subscription status.
*   **Dependencies:** Migrated from deprecated `@supabase/auth-helpers-nextjs` to `@supabase/ssr`.

### ⚠️ In Progress / Blocked
*   **Auth Redirects:** "Log in" and "Get Started" buttons on the landing page are not correctly redirecting to the dashboard post-auth. 
    *   *Fix:* Check Clerk Dashboard > Settings > URLs > Redirect URLs. Ensure `https://matriosha.in/dashboard` is allowed.
*   **CLI Snippet:** The landing page CLI preview is too "crypto-style". Needs to be updated to reflect actual Matriosha CLI commands.
*   **Overage Billing:** Logic exists in DB view but needs a Cron job/Edge Function to create Stripe Invoice Items.

## 🔑 Environment Variables (Vercel)
Ensure these are set in Vercel > Settings > Environment Variables:
*   `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`
*   `CLERK_SECRET_KEY`
*   `NEXT_PUBLIC_SUPABASE_URL`
*   `NEXT_PUBLIC_SUPABASE_ANON_KEY`
*   `STRIPE_SECRET_KEY`
*   `STRIPE_WEBHOOK_SECRET`
*   `STRIPE_PRO_PRICE_ID`

## 🛠️ Tech Stack Preferences
*   **LLM Routing:** Use Gemini 2.5 Pro for UI/Frontend tasks. Use GLM 5.1 for security audits.
*   **Styling:** Dark mode, technical typography, cyan/magenta accents. No "AI slop".
*   **Language:** Code comments in English, UI copy in English. Communication with Rizzo in Italian.

## 📝 Next Steps (Priority Order)
1.  **Fix Clerk Redirects:** Ensure users land on `/dashboard` after login/signup.
2.  **Refine Landing Copy:** Remove "mainnet" references, make CLI snippet realistic.
3.  **Test Payment Flow:** Verify Stripe checkout -> Webhook -> Supabase update loop.
4.  **Implement Overage Cron:** Automate the billing of extra storage usage.

---
*Note: Do not overwrite this file without updating the "Last Updated" date and summarizing changes.*