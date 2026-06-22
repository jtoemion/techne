# Subagent Scope: Pitfalls and Guidelines

## Observable pattern (2026-06-22)

Over two real sessions, subagents dispatched with large multi-file change sets
(MiniMax-M2.7 via minimax.io) timed out at the 600-second child limit:

| Task | Files affected | Calls before timeout | Result |
|---|---|---|---|
| 5-layer bug audit (UI + Stores + Service) | 3 subagents × ~15 files each | 7-12 per subagent | All 3 completed ✅ |
| Convex backend layer audit | 20+ files | 12 calls | Completed ✅ |
| Schema layer audit | 1 file | 8 calls | **Timed out** ❌ |
| Auth guard gaps (7 queries + test fixes) | 10+ files | 37 calls | **Timed out** ❌ |
| Same task, retry with test instructions | 10 files | 37 calls | **Timed out** ❌ |

## Root cause

The subagent reads each file, plans the change, applies the patch, then
verifies. When a task covers 10+ files with read → edit → verify cycles,
the linear sequence of tool calls exceeds 600 seconds because:

- Each `read_file` + `patch` + `terminal(npm test)` cycle takes 10–30 seconds
- The subagent doesn't parallelise — it edits one file at a time
- The 600-second timeout is hard (cannot be overridden per-call)
- MiniMax-M2.7 is slower than frontier models on file-reading tasks

## Guidelines

### 1. Scope limit: ~6–8 files max per subagent

If a change touches more than 8 files, split into multiple subagents:

- **Group by dependency**: files that tests depend on should be in the same
  batch as the test fixes, but unrelated modules can be separate subagents.
- **Group by layer**: don't mix auth-guard changes (Convex backend) with
  test fixes (test files) in the same subagent if the combined file count
  exceeds 8. Split into "fix queries" and "fix tests" subagents.

### 2. When a subagent times out with partial changes

Steps to recover without losing work:

1. Check `git diff --stat` in the working tree — the subagent's patches
   are usually committed to the working tree even on timeout.
2. Read the diff to verify correctness:
   ```bash
   git diff stage/app/convex/ --stat   # which files changed
   git diff stage/app/convex/evidence.ts  # check the actual change
   ```
3. Run `svelte-check` / `tsc` — if the diff compiles and the subagent's
   summary said it was working on tests next, proceed to fix tests yourself.
4. Fix remaining failing tests (the mechanical bypassUserId additions, etc.)
5. Run tests, commit, push.

### 3. Test-update pattern for auth-guard additions

When adding `requireStaff` guards with `bypassUserId` to existing queries,
the test pattern is:

```typescript
// BEFORE:
const result = await t.query(api.module.myQuery, { someArg: value });

// AFTER:
const result = await t.query(api.module.myQuery, {
  someArg: value,
  bypassUserId: "test-bypass",
});
```

For intensionally public queries (iCal endpoints, cohort feeds), do NOT add
the guard. Document the intentional public design with a comment instead.
