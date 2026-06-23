---
name: task-gardener
description: Use when .techne/ artifacts accumulate, tasks.db is bloated, or before committing to avoid leaking generated files. Not for routine use — only when cleanup is needed.
triggers:
  - "cleanup artifacts"
  - "purge old tasks"
  - "compact db"
  - "rotate logs"
  - "task gardener"
---

# Task Gardener

Generated artifacts are silent reputation damage: they leak into commits, bloat the DB, and waste disk. One `git add -A` with .techne/tasks/ not gitignored will ship hundreds of task-specific files to the remote.

## Lead — What to Clean

```
1. Task dirs     → .techne/tasks/, .techne/generated/  (keep last N)
2. Rotate logs   → mode_overrides.log (trim to 2000 lines)
3. Compact DB    → VACUUM tasks.db (reclaims space after deletes)
4. Check leaks   → verify CLEANABLE_DIRS are in .gitignore
```

Run `python3 scripts/task_gardener.py --dry-run` first. Add `--keep 10` to keep more history.

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "Generated dirs are small, I'll clean later" | A single `git add -A` commits them all. "Later" is already too late. |
| "I'll just gitignore the big ones" | .gitignore needs EXACT path matches. Run the script to check. |
| "VACUUM takes too long" | It runs in < 1 second on a normal tasks.db. Skip it only if DB is <1MB. |

## Red Flags — STOP

- "I'll just use git add with specific paths"
- "The artifacts are already in .gitignore"
- "Let me handle cleanup manually"

## Next Steps

- After cleanup, commit → `skills/conclude/SKILL.md`
- Leaks found? → add paths to `.gitignore`, then re-run
- Pipeline still slow? → `skills/pipeline-health/SKILL.md`
