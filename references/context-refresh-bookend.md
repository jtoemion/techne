# Context Amortization — Refresh After Every Change

The user's explicit rule: **every complete change must refresh `.techne/context/` files.**

## The bookend pattern

Context amortization is a bookend:

```
Build context at session start → [changes] → Refresh context after every change
```

## When to refresh

After a pipeline task reaches DONE (or any completed change), update:

| File | When to update |
|------|---------------|
| `.techne/context/project_digest.md` | Stack changed, dependencies added, routes altered |
| `.techne/context/file_roles.md` | New files added, files removed, file purposes changed |
| `.techne/context/commands.md` | New commands added, test commands changed |
| `.techne/context/risk_boundaries.md` | New HITL areas discovered, new no-go zones |
| `.techne/context/context_hash.txt` | Always — update commit SHA, test counts, timestamp |
| `.techne/context/context_packs/*.md` | If the task touched that layer's domain |

## What NOT to do

- Don't rebuild all context files from scratch every time — only update what changed.
- Don't skip context update on "read-only" tasks — if the task produced findings (bug report, audit), add them as a pack or update risk_boundaries.
- Don't let context drift accumulate. A stale context pack is worse than no context.

## YAGNI for context updates

- One changed file? Update only project_digest or the affected pack.
- No code changed (report-only)? Update context_hash + add a findings pack.
- Don't regenerate file_roles.md for every task — only when file structure changes.
