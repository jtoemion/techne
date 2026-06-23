---
name: mistakes-logger
description: Use when a pipeline phase fails, a gate rejects, or the user flags a mistake — log it BEFORE starting the next attempt. Do not skip because "I'll remember for retro."
triggers:
  - "log mistake"
  - "record lesson"
  - "log failure"
  - "mistakes logger"
---

# Mistakes Logger

Every unlogged mistake repeats. The mistakes.md file is the only durable record of what went wrong and why — retro reads it, GRPO scores against it, and future sessions check it before starting work.

## Lead — Required After Every Failure

```
python3 scripts/mistakes_logger.py log "the lesson" "root cause" --phase <phase>
python3 scripts/mistakes_logger.py list           # review open entries
python3 scripts/mistakes_logger.py resolve <id>   # mark fixed
```

Log BEFORE the next attempt, not at retro. A mistake logged after you already fixed it is a diary entry, not a guardrail.

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "I'll log it in retro" | Retro comes at the end. You'll forget the exact cause by then. |
| "The mistake is obvious, I won't repeat it" | "Won't repeat" is the rationalization that guarantees repetition. |
| "The format is easy, I'll write it manually" | Manual entries always miss fields (phase, task, root cause). Use the script. |

## Red Flags — STOP

- "I'll remember this for later"
- "It's fine, I learned my lesson"
- "Let me just fix it quickly first"

## Next Steps

- After logging → `skills/retro/SKILL.md` (full retro reads mistakes.md)
- Mistakes piling up? → `skills/pipeline-health/SKILL.md`
- Back to router → `skills/skill-router.yaml`
