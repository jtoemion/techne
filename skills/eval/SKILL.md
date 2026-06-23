---
name: eval
description: Use when scoring a task result, running eval phase, or evaluating output quality. WHEN-TO-USE only, no workflow summary.
triggers:
  - "evaluate task"
  - "score result"
  - "run eval"
  - "phase eval"
---

# Eval

One line: Score on evidence, not confidence — a perfect-feeling result can score poorly; a rough result can score well.

## Lead — 100-Point Scale

```text
Score 5 dimensions (20 pts each):
  Gate Compliance      — did it pass the gates?
  Verification         — tests, checks, proofs
  Process Discipline   — did they follow the method?
  Review Quality       — was the critique substantive?
  Retro Value          — was the retro worth reading?

Sum = 0–100. No perfect scores without evidence.
```

## Body

```text
1. Pull actual gate results from harness/memory/
2. Count passing/failing tests explicitly
3. Check retro was >100 chars and referenced phases
4. Check review made specific findings, not generic praise
5. Add comments explaining each score, cite evidence

Gate compliance and process discipline are independent of "it works."
```

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "All tests pass so it's a 100" | Tests are one of five dimensions. Gate compliance and process discipline are separate. |
| "The code looks clean" | Clean code with no retro or shallow review scores low on Retro Value and Review Quality. |
| "It compiled successfully" | Compilation is a gate, not a score. A compiling bug still fails Gate Compliance. |
| "The user didn't complain" | Retro Value requires substance, not satisfaction. |

## Red Flags — STOP

- "100/100" without citing specific evidence from all 5 dimensions
- "perfect score" or "everything passed" — pass/fail is not a score
- Skipping any dimension because it's "hard to measure"

## Next Steps

- Scores recorded → `skills/skill-router.yaml`
