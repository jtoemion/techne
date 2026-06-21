# PIN Auth Bridge — bypassUserId Pattern

## Problem

Users authenticated via PIN (localStorage-based auth) have no Better Auth session.
Convex views call `ctx.auth.getUserIdentity()` → null → `requireStaff()` throws
`UNAUTHENTICATED`. This blocks all Convex queries for PIN-auth users.

## Solution: `bypassUserId` fallback

The pattern works in three layers:

### Layer 1 — identity.ts (server-side auth functions)

Add an optional `bypassUserId` parameter to `requireStaff()`, `requireGuardian()`,
and `requireGuardianOrStaff()`. When no Better Auth identity exists but
`bypassUserId` is provided, look up the staff/guardian document directly by ID.

```typescript
export async function requireStaff(
  ctx: Parameters<typeof getCaller>[0],
  role?: StaffRole,
  bypassUserId?: string,  // ← NEW
): Promise<Extract<Caller, { kind: "staff" }>> {
  // Try Better Auth first (email+password users)
  const identity = await ctx.auth.getUserIdentity();
  if (identity) { /* existing logic */ }

  // PIN auth fallback: DB lookup by document ID
  if (bypassUserId) {
    const staffRow = await (ctx as any).db.get(bypassUserId as Id<"staff">);
    if (staffRow && (staffRow as any).roles) {
      return { kind: "staff", authUserId: "pin-auth", staffId: bypassUserId,
               roles: (staffRow as any).roles as StaffRole[] };
    }
  }
  throw new ConvexError("UNAUTHENTICATED");
}
```

Same pattern for `requireGuardian()` (guardian fallback) and
`requireGuardianOrStaff()` (tries staff then guardian).

### Layer 2 — Convex views (query/mutation args)

Every view that calls `requireStaff()`/`requireGuardian()` needs a
`bypassUserId: v.optional(v.string())` arg, passed through to the auth function.

```typescript
// Before
export const someQuery = query({
  args: {},
  handler: async (ctx) => {
    await requireStaff(ctx);
    // ...
  },
});

// After
export const someQuery = query({
  args: { bypassUserId: v.optional(v.string()) },
  handler: async (ctx, args) => {
    await requireStaff(ctx, undefined, args.bypassUserId);
    // ...
  },
});
```

### Layer 3 — Frontend (page components)

In each page component that calls Convex views, read the PIN auth user ID from
localStorage and pass it as `bypassUserId`:

```typescript
function getBypassUserId(): string | undefined {
  if (typeof localStorage === 'undefined') return undefined;
  try {
    const raw = localStorage.getItem('pin_auth');
    if (!raw) return undefined;
    return JSON.parse(raw)?.user?.id;
  } catch { return undefined; }
}

// In useQuery calls:
const overviewQuery = useQuery(api.views.overview.overview, {
  bypassUserId: getBypassUserId(),
});
```

## Files that implement this pattern

- `convex/lib/identity.ts` — `requireStaff`, `requireGuardian`, `requireGuardianOrStaff`
- `convex/views/coach.ts` — `todaySession`, `learnersForSession`, `portfolioSubject`
- `convex/views/overview.ts` — `overview`, `recentActivity`
- `convex/views/hoa.ts` — 5 analytics queries
- `convex/views/guardian.ts` — 4 guardian queries
- `convex/views/evidence.ts` — `evidenceForLearner`, `bloomChecksForLearner`
- `convex/diagnosticReports.ts` — `guardianView`
- `src/routes/(app)/coach/+page.svelte` — via `convex-source.ts` data source
- `src/routes/(app)/hoa/+page.svelte` — via `getBypassUserId()` in useQuery
- `src/routes/(app)/guardian/+page.svelte` — via `getBypassUserId()` in useQuery
