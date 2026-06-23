---
name: session-reporter
description: Use when you need to show what happened in a session — task outcomes, Honcho state, recent git changes. Not for real-time debugging; use pipeline-health for that.
triggers:
  - "session report"
  - "what did we do"
  - "task summary"
  - "recent activity"
---

# Session Reporter

A session without a summary is lost context. Task history without state information is half the picture — the harness state file may carry conclusion IDs and retry counts that explain *why* a task stalled.

## Lead — What to Run

```
python3 scripts/session_reporter.py          # last 5 tasks
python3 scripts/session_reporter.py --last 10  # more history
python3 scripts/session_reporter.py --full    # full detail
```

Then read the output: done/failed/running counts matter. A string of FAILED tasks means the pipeline or the approach is wrong — don't start a new task until you know why.

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "I remember what happened this session" | You remember highlights. The DB shows exact task IDs, phases, and timing. |
| "I'll just check git log" | Git log shows what was committed. Not what FAILED or is still BLOCKED. |
| "Harness state doesn't matter" | It carries honcho_conclusion_id — without it the RECALL gate loops. |

## Red Flags — STOP

- "Let me just jump into the next task"
- "I know what happened, no need for a report"
- "Git log is enough"

## Next Steps

- Running tasks blocked? → `skills/pipeline-health/SKILL.md`
- Producing a retro? → `skills/retro/SKILL.md`
- Starting a new task? → `skills/conductor/SKILL.md`
