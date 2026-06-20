# Better Auth Session Navigation — Debugging Path

> Full diagnostic flowchart for "sign-in returns 200 but page doesn't navigate."
> Encountered during BnB/Stage Netlify debugging, 2026-06-20.

## Symptom

User clicks "Sign In", API returns HTTP 200 with token + user data, but the browser stays on `/login`. Network logs may show `/coach/__data.json` being fetched (SvelteKit started navigating), then immediately back on `/login`.

## Root cause chain

1. **`authClient.signIn.email()`** sets a session cookie on the response, returns user data to JavaScript.
2. **`goto('/coach')`** triggers SvelteKit client-side navigation — no HTTP request, no cookie sent.
3. **`(app)/+layout.svelte` mounts**, calls `useSession()`.
4. **The session store has NOT updated** — it still shows `{ data: null, isPending: false }` from the previous fetch. Better Auth's session store does NOT respond to SvelteKit `invalidateAll()`.
5. **Auth guard fires**: `!authChecked && isPending === false → !user → goto('/login')`.
6. **User is back on /login** with no visible error.

## The fix: `getSession()` + `goto()` (not hard navigation)

The Better Auth `crossDomainClient()` plugin stores the session token in memory, NOT in cookies. A hard navigation (`window.location.href`) loses the in-memory token — the new page loads with no session, the auth guard sees no user, and the user is redirected back to `/login` with no visible error.

**Correct fix** — force-refresh the session atom in the current page context, then navigate via client-side `goto()`:

```ts
// login/+page.svelte — handleSignIn()
const session = await authClient.getSession();
if (!session?.user) {
  // session did not persist — show error instead of navigating blind
  error = 'Login succeeded but session could not be established.';
  return;
}
goto(redirectForRole(appRole));
```

`authClient.getSession()` returns a Promise that resolves with the current session (including user data). Awaiting it guarantees the session store has the user data before `goto()` loads the new page. Client-side navigation via `goto()` preserves the in-memory token.

**Why this was wrong before:** The session atom (`useSession()`) starts as `{ data: null, isPending: true }` and updates asynchronously after `signIn.email()`. Calling `goto()` immediately after sign-in races — the layout mounts before the atom propagates, sees `{ data: null, isPending: false }`, and redirects to `/login`. Neither `invalidateAll()` (which only re-runs SvelteKit load functions) nor hard navigation (which loses the in-memory token) solves this.

## What does NOT work

- **`await invalidateAll()` before `goto()`**: `invalidateAll()` only re-runs SvelteKit load functions. Better Auth's `useSession()` is an independent store; it doesn't re-fetch on `invalidateAll()`. The session store in the new page context still has the old null value.
- **`goto(url, { invalidateAll: true })`**: Not a valid option in SvelteKit 5. `goto` accepts `{ replaceState, noScroll, keepFocus, state }` only.

## Checking for this issue in the wild

Network log pattern:
```
POST /api/auth/sign-in/email → 200
GET /login/__data.json?x-sveltekit-invalidated=10 → 200   ← invalidateAll() ran
GET /coach/__data.json?x-sveltekit-invalidated=010 → 200  ← SvelteKit started loading coach
```
Then the user is back on /login (page title still shows login). The coach page data load started but the layout redirected before rendering.

## Related: Better Auth user roles

Better Auth user objects (created via `signUp.email()` or programmatic API) only contain `name`, `email`, `emailVerified`, `id`. They do NOT contain `role` or `staffRoles` fields.

The app's `roleFromSession()` function reads `user.role` and `user.staffRoles` from the Better Auth user. Since these don't exist, it falls back to `'coach'` (the default).

For proper role resolution, Convex `staff` and `guardians` records must exist with `authUserId` matching the Better Auth user ID. The Convex records contain `roles` / `staffRoles` which the app layer reads after the session is established.

### Creating linked records

```ts
// Convex mutation — after creating Better Auth users
await ctx.db.insert("staff", {
  fullName: "Ms. Ellen",
  email: "ellen@beatandbloom.id",
  roles: ["HeadOfAcademy", "Coach"],
  preferredLanguage: "en",
  active: true,
  createdAt: Date.now(),
  authUserId: "k176ryd6qdf6d1afn6vyzcv009890213", // from signUp response
});
```

Schema for `staff`:
- `fullName: v.string()`
- `roles: v.array(v.union(v.literal("HeadOfAcademy"), v.literal("Coach"), ...))`
- `email: v.string()`
- `preferredLanguage: v.string()`
- `active: v.boolean()`
- `createdAt: v.number()`
- `authUserId: v.optional(v.string())`

Indexed by `by_email` and `by_authUser`.

## Related: Convex component installation

The `@convex-dev/better-auth` Convex component must be registered correctly:

```ts
// convex/convex.config.ts — CORRECT
import betterAuth from "@convex-dev/better-auth/convex.config";
const app = defineApp();
app.use(betterAuth);              // ← this syntax
export default app;
```

```ts
// convex/convex.config.ts — WRONG (silently fails on some versions)
const app = defineApp({
  components: { betterAuth },     // ← NOT this
});
```

If the component isn't registered, mutations that access `authClient.adapter(ctx)` return `Child component ComponentName(Identifier("betterAuth")) not found`, and the sign-up API returns HTTP 500 with empty body.

After fixing `convex.config.ts`, the deploy log should show `✔ Installed component betterAuth.` (not just code push).

## Related: CSP connect-src for Convex WebSocket

Convex real-time sync uses WebSocket at `wss://<deployment>.convex.cloud`. The CSP `connect-src` directive must include both:

```
connect-src 'self' https://*.convex.site https://*.convex.cloud wss://*.convex.site wss://*.convex.cloud
```

Without `wss://*.convex.cloud`, the browser blocks the WebSocket connection with `NS_ERROR_CONTENT_BLOCKED`.
