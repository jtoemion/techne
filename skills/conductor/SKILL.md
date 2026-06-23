---
name: conductor
description: Use when orchestrating a pipeline, driving a task through phases, or running phase conductor. WHEN-TO-USE only, no workflow summary.
triggers:
  - "orchestrate"
  - "run pipeline"
  - "drive task"
  - "phase conductor"
---

# Conductor

One line: The phase_mode exists for a reason — use it. Never skip phases; the micro/fast modes exist so you don't have to.

## Lead — Phase Mode Routing

```text
phase_mode determines sequence:
  micro  → IMPLEMENT → RETRO (small, low risk)
  fast   → IMPLEMENT → VERIFY → RETRO
  full   → PREFLIGHT → IMPLEMENT → VERIFY → REVIEW → RETRO
  heavy  → PREFLIGHT → IMPLEMENT → VERIFY → REVIEW → APPROVAL → RETRO

Never skip phases. Use the mode that fits, not the one that skips.
```

## Body

```text
Conductor responsibilities:
  - Route to correct phase by mode
  - Collect gate results from harness
  - Enforce phase ordering (do not advance on FAIL)
  - Log failures to memory/mistakes.md

Exit on FAIL → retry same agent (max 3) → halt if persistent.
```

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "This is small, I'll just implement it directly without going through all phases" | micro mode exists for small changes. Use it. Don't skip the pipe. |
| "I don't need preflight for a quick fix" | If the mode requires it, you need it. Fast mode exists so you don't have to skip. |
| "I'll skip review on this one" | Review is part of full/heavy modes. If you need to skip it, change the mode. |
| "Verification is optional" | No phase is optional by name. The mode determines which are required. |

## Red Flags — STOP

- "this doesn't need the pipe" — use micro/fast mode instead
- "I'll just do it directly" — pick a mode and run it
- Advancing to next phase when current phase returned FAIL
- Using heavy mode and skipping the APPROVAL gate

## Next Steps

- All phases complete for mode → `skills/skill-router.yaml`
