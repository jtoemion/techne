# Bug Audit — Parallel Layer Dispatch Workflow

## When to use this

Systematic codebase audit with per-layer coverage. Use when the user asks for
a "full bug audit" or "harden the codebase per layers" — NOT for single-bug
fixes or focused code reviews.

## Workflow

### Phase 1: Classify layers

Slice the codebase into 5 layers (proven pattern):

| Layer | Scope | Typical paths |
|-------|-------|---------------|
| **UI** | Components, templates, routes | src/routes/, src/lib/components/ |
| **State/Stores** | State management, reactivity | src/lib/stores/ |
| **Service/Data** | APIs, sync, storage, offline | src/lib/data/, src/lib/db/ |
| **Backend** | Server logic, queries, auth | convex/ (excluding schema) |
| **Schema/Database** | Schema, indexes, migrations | schema.ts, migrations/ |

### Phase 2: Dispatch parallel EXPLORE subagents

One `delegate_task` per layer. All 5 run in parallel (or in batches of 3
for constrained environments).

Each subagent gets:
- **Layer scope** (exact paths)
- **Bug categories** relevant to that layer
- **Output format** — structured: FILE:LINE — description — severity (HIGH/MEDIUM/LOW)
- **Output file** — /tmp/bugs-<layer-name>.md

Bug categories per layer:

**UI**: null-safety, unhandled promise rejections, missing error boundaries,
a11y violations, $state vs let confusion, missing onDestroy cleanup,
duplicate renders, empty/loading/error state gaps, hardcoded strings

**State/Stores**: $state/$derived misuse, plain let where $state needed,
stale closures, race conditions, missing unsubscribe/cleanup, circular deps

**Service/Data**: missing catch handlers, silent error swallowing,
IndexedDB transaction failures, sync loop leaks, network retry gaps,
dead code, type safety leaks (any/casts)

**Backend**: N+1 queries, missing auth guards, unhandled null paths,
Promise.all vs allSettled, dead code, silent catch blocks,
array-field query traps (for Convex), iCal/public endpoint exposure

**Schema**: missing indexes for common query paths, orphaned indexes,
nullable fields requiring null checks, array-field issues,
missing cascade deletes

### Phase 3: Collate findings

Read all 5 `/tmp/bugs-*.md` files. Write a consolidated document:

```markdown
# Full Bug Audit — YYYY-MM-DD

| Layer | Critical | High | Medium | Low |
|-------|----------|------|--------|-----|
| UI | — | N | N | N |
| State | — | N | N | N |
| Service | — | N | N | N |
| Backend | N | N | N | N |
| Schema | — | N | N | N |
| **Total** | **N** | **N** | **N** | **N** |
```

List each bug with severity prefix, file:line, description, and fix approach.

### Phase 4: Fix one at a time through pipeline

Each bug fix gets its own pipeline task. Priority order:
1. Critical (security/data-loss)
2. High (runtime crashes, auth gaps)
3. Medium (race conditions, leaks)
4. Low (type safety, dead code, cosmetic)

For each fix:
1. `honcho_context(peer='user')`
2. `db.create_task(title="Bug-X: description", tags=["bug-hunt", "p1"], phase_mode="full")`
3. Drive RECALL → IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → EVAL → RETRO → CONCLUDE → REFRESH_CONTEXT → DONE
4. `honcho_conclude()` after every submit
5. `git push origin <branch>` after DONE

### Phase 5: Track progress

Maintain a status table in the consolidated document:

| # | Bug | Severity | Status | SHA |
|---|-----|----------|--------|-----|
| C-1 | sessions.byId unguarded | CRITICAL | ✅ DONE | abc1234 |
| H-1 | learner.nickname null crash | HIGH | ⏸️ PENDING | — |
