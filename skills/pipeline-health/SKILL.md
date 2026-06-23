---
name: pipeline-health
description: Use when about to start a task and something feels wrong — tasks stuck, DB error, stale state. Not for routine use — only when you suspect the pipeline itself is unhealthy.
triggers:
  - "check pipeline health"
  - "stuck task"
  - "pipeline not working"
  - "health check"
---

# Pipeline Health

Before diagnosing a task failure, diagnose the pipeline itself. Checking one table and declaring health is not a health check — it misses stuck tasks, stale state, and uncommitted artifact leaks.

## Lead — What to Check

```
1. DB integrity    → pipeline_health.py --quick
2. Stuck tasks     → look for PENDING/BLOCKED >1h
3. Git state       → uncommitted .techne/ artifacts leak into commits
4. Harness state   → honcho_conclusion_id present?
```

Run `python3 scripts/pipeline_health.py --quick` first. Full report if issues found.

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "The pipeline was working yesterday, it's fine" | Stale state builds silently. One stuck task blocks the whole queue. |
| "I'll just check the DB count" | Count alone misses stuck tasks and state issues. Run the script. |
| "The error is in the task, not the pipeline" | A blocked task or missing honcho state will look like a task error. Rule out pipeline first. |

## Red Flags — STOP

- "I'll just check one thing"
- "The pipeline seems fine"
- "Let me skip health check and go straight to the task"

## Next Steps

- Issues found? → `skills/debug/SKILL.md` for systematic pipeline debugging
- Clean bill of health? → start the task with `skills/conductor/SKILL.md`
- Pipeline keeps failing? → back to `skills/skill-router.yaml`
