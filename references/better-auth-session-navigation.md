# Better Auth Session Navigation — Full Pattern

## The Problem

After `authClient.signIn.email()` succeeds, using `goto()` to navigate to a protected page causes the layout's auth guard to redirect back to `/login`. The user sees "clicked sign in, nothing happened."

## Root Cause

The `crossDomainClient()` plugin from `@convex-dev/better-auth` stores the session token IN MEMORY, not in cookies. The `useSession()` store hasn't received the new user data when `goto()` triggers the new page's layout to check auth. Three mechanisms fight:

1. **Server-side guard**: `+layout.server.ts` reads `getAuthState()` which checks the JWT cookie. If the `Set-Cookie` from sign-in hasn't committed yet, the 302 redirect fires before the client even renders.
2. **Client-side guard**: `+layout.svelte` subscribes to `useSession()`. The atom can emit `{ data: null, isPending: false }` before the actual user data arrives — the auth guard fires prematurely.
3. **Role resolution**: The Better Auth user object has no `role` or `staffRoles` fields (only `name`, `email`, `id`). `roleFromSession()` always returns `'coach'` (the default).

## The Fix (Complete)

### Fix 1 — Server redirect race
`+layout.server.ts`: Remove `redirect(302, '/login')`. Return auth state as data instead. The client-side guard handles redirects.

### Fix 2 — Client subscribe race
`+layout.svelte` guard condition must check `!isPending && val.data !== null && val.data !== undefined`. Without the `data !== null` check, the intermediate `{ data: null, isPending: false }` emission triggers a premature redirect.

### Fix 3 — Session refresh before navigation
`login/+page.svelte::handleSignIn()`:
```ts
const session = await authClient.getSession();  // force-refresh atom
if (!session?.user) { /* error */ return; }
await invalidateAll();  // force server load functions to re-run with fresh cookie
goto(redirectForRole(actualRole));
```

### Fix 4 — Role resolution (session user has no role field)
Create a Convex query `getMyRole` that resolves role from `staff.roles` or `guardians` tables by `authUserId`:
```ts
// convex/getMyRole.ts
export const getMyRole = query({
  args: { authUserId: v.optional(v.string()) },
  handler: async (ctx, args) => {
    let authUserId = args.authUserId ?? (await ctx.auth.getUserIdentity())?.subject;
    if (!authUserId) return "coach";
    // Check staff (has roles array: HeadOfAcademy, Coach, etc.)
    const staff = await ctx.db.query("staff")
      .withIndex("by_authUser", (q) => q.eq("authUserId", authUserId)).first();
    if (staff) {
      if (staff.roles?.includes("HeadOfAcademy")) return "hoa";
      if (staff.roles?.includes("Coach")) return "coach";
      return "coach";
    }
    // Check guardians
    const guardian = await ctx.db.query("guardians")
      .withIndex("by_authUser", (q) => q.eq("authUserId", authUserId)).first();
    if (guardian) return "guardian";
    return "coach";
  },
});
```

In `login/+page.svelte`, after `getSession()`:
```ts
const { api } = await import('../../../convex/_generated/api');
const httpClient = getPublicConvexClient();
const actualRole = await httpClient.query(api.getMyRole.getMyRole, {
  authUserId: session.user.id,
});
```

In `(app)/+layout.svelte`, same pattern on session resolve as fallback redirect.

### Fix 5 — Unhandled rejections
- `goto()` in login page: `await goto(...)` so the outer try/catch catches failures.
- `goto()` in layout's subscribe callback: wrap in try/catch with `console.error` fallback since Svelte stores don't await subscriber promises.

## Verification

After all fixes:
1. `npm run check`: 0 errors
2. `npm test -- --run`: all pass
3. Convex deploy: `npx convex deploy --yes`
4. Netlify deploy: trigger from master branch
5. curl test: `POST /api/auth/sign-in/email` → HTTP 200 with token
