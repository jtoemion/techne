---
name: refresh-context
description: Use when context files may be stale, updating amortization, or running phase refresh. WHEN-TO-USE only, no workflow summary.
triggers:
  - "refresh context"
  - "update amortization"
  - "phase refresh"
---

# Refresh Context

One line: Context hash detects stale state — if it changes, update the files. If no config exists, skip gracefully (fast mode).

## Lead — Context Hash Check

```text
If no .techne/config.yaml → SKIP (fast mode, no context to refresh)
Else → recompute context_hash.txt AFTER any file change

Hash must reflect current state. Stale hash = broken amortized context.
```

## Body

```text
Refresh triggers (any one):
  - .techne/context files were edited
  - Significant file structure change
  - Phase transition after IMPLEMENT

After editing any context file:
  1. Recompute hash → write .techne/context/context_hash.txt
  2. Verify new hash reflects the change
  3. Do NOT skip if "only a small change"
```

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "The context files probably don't need updating for this small change" | The hash exists to detect stale state. If files changed, recompute it. |
| "Context is fine, no update needed" | If you edited files and didn't update context, the hash is now stale. |
| "I'll update it during the next phase" | Hash must be current for amortized context to work. Deferred = broken context. |
| "This is fast mode anyway" | Fast mode skips only when no config.yaml exists. If it exists, you still need the hash. |

## Red Flags — STOP

- Edited context files and didn't recompute hash
- "context is fine" without checking the hash
- "no update needed" after file changes
- Stale hash sitting in context_hash.txt while files changed

## Next Steps

- Hash recomputed and verified → `skills/skill-router.yaml`
