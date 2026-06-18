---
name: diagnose-firestore
description: Firestore-specific debugging patterns — security-rule denials, missing composite indexes, offline-cache staleness, and the read-count traps. Loaded automatically when stack_detect finds firebase/firestore in the project. Use when a bug touches Firestore reads, writes, rules, or sync.
triggers:
  - firestore
  - firebase
  - security rules
  - composite index
---

# Firestore — field-tested debugging patterns

Load these on top of the generic `skills/diagnose.md` loop. Each one looks like an
app bug but is actually a Firestore-shaped failure — check here before instrumenting.

## The error tells you the layer

```
PERMISSION_DENIED          → security rules, NOT your query. Test in the Rules
                             Playground with the EXACT auth uid + doc path.
FAILED_PRECONDITION + URL  → missing composite index. The error embeds a
                             console link that builds it. Don't hand-roll.
UNAVAILABLE / offline      → SDK is serving the local cache; the write may be
                             queued, not failed. Check .metadata.fromCache.
```

## Rules are the #1 false "my code is broken"

```
- A read returning empty is often a rule denial silently caught, not "no data".
- Rules do NOT filter — a query that violates rules ERRORS, it doesn't trim.
  If list rules require a where() clause, the query MUST include it.
- request.auth is null in rules until auth state resolves — race on first paint.
```

Repro: paste the failing path + uid into the **Rules Playground** before touching code.

## Index + query traps

```
- Compound where() + orderBy() on different fields → needs a composite index.
- != and not-in quietly exclude docs missing the field entirely.
- Range (<, >) is allowed on ONE field per query — a second range silently fails.
```

## Offline cache makes bugs non-deterministic

```
- Reads hit the local cache first → stale value that "fixes itself" on reload.
- snapshot.metadata.hasPendingWrites / .fromCache distinguishes optimistic
  local state from server-confirmed state. Log BOTH in the repro.
- A "lost write" after reload is usually a queued write that never flushed —
  check the Network tab for the Write RPC, not your handler.
```

## Read-count / cost surprises

```
- onSnapshot re-reads the WHOLE result set on any change unless paginated.
- A render loop re-subscribing each render bills a read storm — verify the
  listener is created once (effect deps), not per render.
```

## Next Steps

- Build the pass/fail loop first → `skills/diagnose.md` (Phase 1)
- Bug is in the SvelteKit layer above Firestore → `skills/svelte.md`
- Deploy/runtime-env angle (functions, env scoping) → `skills/diagnose/netlify.md`
- Root cause found, ready to fix → `skills/implementer.md`
