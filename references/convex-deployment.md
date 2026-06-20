# Convex Production Deployment

## Initial Deploy

```bash
cd stage/app

# Set required env vars FIRST (trusted origins guard rejects without SITE_URL)
npx convex env set SITE_URL "https://<deployment-name>.convex.cloud"
npx convex env set BETTER_AUTH_SECRET "$(openssl rand -hex 32)"

# Deploy — target prod deployment by name (non-interactive)
CONVEX_DEPLOYMENT="<deployment-name>" npx convex deploy
```

## Deployment targeting

- Local `.env.local` sets `CONVEX_DEPLOYMENT=local:...` which causes the interactive prompt.
- Setting `CONVEX_DEPLOYMENT` explicitly targets that deployment and skips the prompt.
- Use `npx convex env list` to verify vars on the target deployment.

## Required env vars

| Var | Why | Set before first deploy |
|-----|-----|------------------------|
| `SITE_URL` | Trusted origins guard rejects without it in production | YES |
| `BETTER_AUTH_SECRET` | Signs auth tokens | YES |
| `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS` | Nodemailer SMTP transport | Optional (console fallback) |
| `SMTP_PORT`, `SMTP_FROM` | SMTP transport config | Optional |

## Email architectures (two paths)

- **Convex (password reset)**: `convex/email.ts` — "use node" + Nodemailer, called via `ctx.runAction()`. Zero-direct-import rule applies (see SKILL.md pitfall #13).
- **SvelteKit SSR (magic links)**: `src/lib/server/email.ts` — Nodemailer, runs in Netlify SSR Node.js runtime. No "use node" needed.
- Both read the same SMTP env vars. Both fall back to console.log when SMTP not configured.

## Resend alternative

If SMTP is unavailable, use Resend API (works in V8 runtime, no "use node" needed):

```bash
npx convex env set RESEND_API_KEY re_xxxxxxxxxxxx
```

The `convex/email.ts` file was originally written for Resend and can be swapped back by reverting to its `fetch()`-based implementation.

## Convex Component Installation

Several dependencies ship as Convex components (`@convex-dev/better-auth`, etc.) that must be installed on the deployment separately from code pushes.

### Component registration syntax (critical)

Convex component registration uses `app.use()` — NOT `defineApp({ components })`:

```ts
// convex.config.ts — correct syntax
import { defineApp } from "convex/server";
import betterAuth from "@convex-dev/better-auth/convex.config";

const app = defineApp();
app.use(betterAuth);

export default app;
```

The `defineApp({ components: { betterAuth } })` object syntax does NOT work with current Convex versions. It silently compiles and deploys without error, but the component is never installed. The deploy log will show `✔ Deployed Convex functions` but will NOT show `✔ Installed component X`. Switching to `app.use()` produces the telltale `✔ Installed component betterAuth.` line in the deploy output.

### Installation flow

```bash
# 1. Register the component in convex.config.ts using app.use()
# (see correct syntax above)

# 2. Install locally (pulls the component binary)
npx convex dev --once

# 3. Install on production — use --prod, not deploy
npx convex dev --once --prod

# 4. Deploy code (also pushes component config)
npx convex deploy --yes

# 5. Verify by running a component function
npx convex run <componentModule>:<function> '{}'
# If you get "Child component not found" → component NOT installed
```

### Why `npx convex deploy` alone doesn't install components

`npx convex deploy` pushes your code (functions, schema) to the production deployment. It does NOT install Convex components that haven't been synced yet. Components must first be pulled via `npx convex dev` (which targets whichever deployment the local env points to).

If `.env.local` has `CONVEX_DEPLOYMENT=local:...`, `npx convex dev --once` installs the component on the LOCAL backend only. To install on production:

```bash
# Forces production deployment (but does NOT update .env.local)
npx convex dev --once --prod
```

### Common error: "Child component ComponentName(Identifier(\"betterAuth\")) not found"

| Cause | Fix |
|-------|-----|
| Component never installed on this deployment | `npx convex dev --once --prod` then redeploy |
| Wrong deployment targeted | Check `cat .env.local` for CONVEX_DEPLOYMENT — it may still point to local |
| Component registered with `defineApp({ components })` instead of `app.use()` | Switch to `app.use(betterAuth)` syntax, redeploy |
| `.env.local` points to local, but you ran `npx convex run` without `--prod` | Add `--prod` or update `.env.local` |

### Creating demo users via programmatic API (when component is available)

Once the Better Auth component is installed, create users from a Convex mutation using the programmatic API (no HTTP calls, no origin checks):

```ts
import { internalMutation } from "./_generated/server";
import { createAuth } from "./auth";

export const run = internalMutation({
  args: {},
  handler: async (ctx) => {
    const auth = createAuth(ctx as any);
    await auth.api.signUpEmail({
      body: { name: "User", email: "user@example.com", password: "Demo123!" }
    });
  },
});
```

The `.api` property on the `betterAuth` instance exposes `signUpEmail`, `signInEmail`, `signOut`, `changePassword`, `updateUser`, `deleteUser`, and many more — no HTTP layer needed. This is the simplest way to create demo users or seed auth accounts programmatically.

### Critical: Linking auth users to Convex records

Better Auth user records created via `signUpEmail` or the sign-up API only carry identity fields (`name`, `email`, `id`, `emailVerified`). They do NOT carry:
- `role` ("staff" or "guardian")
- `staffRoles` (e.g. `["HeadOfAcademy", "Coach"]`)
- Any other app-specific metadata

This metadata lives in the Convex `staff` and `guardians` tables. Each record has an `authUserId` field that must be set to the Better Auth user's `id`. Without this link:
- `roleFromSession()` returns `'coach'` (the default fallback) for ALL users
- The app can't determine the correct dashboard (HOA vs coach vs guardian)
- Staff/guardian-specific queries may return empty results

**After creating demo auth users, ALWAYS create the corresponding staff/guardian records with the authUserId set.** The user IDs from `signUpEmail` responses are available immediately after creation:

```ts
const res = await auth.api.signUpEmail({
  body: { name: "Ms. Ellen", email: "ellen@beatandbloom.id", password: "Demo123!" }
});
// res.user.id ← this is the authUserId
```

Then create or link the Convex record:

```ts
await ctx.db.insert("staff", {
  fullName: "Ms. Ellen",
  email: "ellen@beatandbloom.id",
  roles: ["HeadOfAcademy", "Coach"],
  authUserId: res.user.id,
  active: true,
  createdAt: Date.now(),
  preferredLanguage: "en",
});
```

**If auth users were already created without linking**: query the Convex tables by email, and use `ctx.db.patch(record._id, { authUserId })` to set the link. Users can sign in without the link, but role resolution and data access will not work correctly.

## Common errors

| Error | Cause | Fix |
|-------|-------|-----|
| `SITE_URL environment variable must be set in production` | Missing SITE_URL in Convex env | `npx convex env set SITE_URL ...` |
| `It looks like you are using Node APIs from a file without the "use node" directive` | Cross-runtime import (non-"use node" file imports from "use node" file) | Use `ctx.runAction()` instead of direct import |
| `Cannot prompt for input in non-interactive terminals` | Convex CLI requires TTY | Set `CONVEX_DEPLOYMENT` env var or pipe through |
| `The package "events" wasn't found` | Nodemailer bundled for V8 runtime | Move to "use node" file, ensure no cross-runtime imports |
