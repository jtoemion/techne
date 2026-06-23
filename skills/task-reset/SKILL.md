---
name: task-reset
description: Use when ALL alternatives have been exhausted — pipeline-health passes, no stuck process, but a task is genuinely unrecoverable. Run --dry-run first. This is NOT for routine debugging.
triggers:
  - "reset task"
  - "force reset"
  - "unstick task"
  - "stuck task"
---

# Task Reset

Resetting a task destroys phase state. It is the right thing for a genuinely stuck task and the wrong thing for every other situation. Violating the letter of "only as last resort" is violating the spirit.

## Lead — Safety Protocol

```
1. Run pipeline-health.py first    — is the pipeline actually healthy?
2. Run session_reporter.py         — understand why the task is stuck
3. Run task_reset.py --dry-run     — preview the change
4. Only then: task_reset.py <id>   — executes with confirmation prompt
```

`--dry-run` is not optional. Run it. Read the output. Then decide.

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "The task is stuck, this is the fastest way" | Fastest != correct. If you didn't run pipeline-health first, you don't know why it's stuck. |
| "Dry-run is for amateurs, I know what this does" | Every reset that skipped dry-run in this repo hit the wrong status or lost phase progress. |
| "Reset doesn't delete data, it's safe" | Reset advances phase tracking. Wrong phase = restart the whole pipeline. |
| "I'll log the mistake after reset" | No you won't. Log first: `mistakes_logger.py log` before `task_reset.py`. |

## Red Flags — STOP (HARD)

- "I don't need to check why it's stuck, I know"
- "I'll skip dry-run, it's just one reset"
- "Let me reset first and investigate later"
- "All three conditions I said are NOT met"

ALL three conditions MUST be met before reset:
1. `pipeline_health.py --quick` shows no pipeline issues
2. The task has been stuck for >1 hour or the pipeline errored with no recovery
3. You have logged the root cause to mistakes.md

## Next Steps

- After reset → re-dispatch task through `skills/conductor/SKILL.md`
- Pipeline keeps getting stuck? → `skills/pipeline-health/SKILL.md`
- Not sure why it stuck? → `skills/debug/SKILL.md`
