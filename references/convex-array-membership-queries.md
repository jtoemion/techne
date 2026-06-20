# Convex array-membership queries in this codebase

Session-derived note for future audits of learner/evidence queries.

## What happened

A change attempted to replace:

```ts
const all = await ctx.db.query("evidenceRecords").collect();
return all.filter((r) => r.learnerIds.includes(args.learnerId));
```

with a server-side `.filter()` pattern on `learnerIds`. That broke tests because Convex query semantics did not support the attempted array-membership check in that shape, and the result set went empty.

A later guardian-view regression showed the other failure mode too: using the array index as if it were an exact-membership query caused shared evidence (`learnerIds: [a, b]`) to disappear from guardian timeline/proficiency/chart data even though the linked learner should have seen it.

## Safe current pattern

For `evidenceRecords.learnerIds` today, keep the minimal safe implementation:

```ts
const all = await ctx.db.query("evidenceRecords").collect();
return all.filter((r) => r.learnerIds.includes(args.learnerId));
```

For curated evidence views:

```ts
const all = await ctx.db.query("evidenceRecords").collect();
const mine = all.filter(
  (r) => r.learnerIds.includes(args.learnerId) && r.status === "Curated",
);
```

## Regression test pattern

Seed one evidence record with two learners:

```ts
learnerIds: [pashaId, sariId]
```

Then query the guardian timeline for `pashaId` and assert the shared record is still visible. This catches the exact-match/index assumption that a single-learner fixture will miss.

## When to refactor

`evidenceRecords.by_learner` is still used by guardian views:

```ts
.withIndex("by_learner", (q) => q.eq("learnerIds", [args.learnerId]))
```

So:
- do not remove the index just because `convex/evidence.ts` or `convex/views/evidence.ts` scans in memory
- add a shared-evidence regression test before changing the schema or guardian views

## Regression test recipe

Seed one evidence row with `learnerIds: [pashaId, sariId]`, curate it, then assert that `guardianTimeline({ learnerId: pashaId })` includes the shared row and that `guardianTimeline({ learnerId: sariId })` is still gated by guardian linking.

## When to refactor

If query performance becomes a real issue, use a junction table such as `evidenceLearners` (one row per evidence/learner pair). Do not try to force array-membership semantics into the query layer.
