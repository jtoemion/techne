---
name: evaluation
description: Post-run agent behavior scoring. Runs automatically after every pipeline. Scores 5 dimensions, grades the run, identifies gaps, gives recommendations.
---

# Evaluation

## Scoring (each 0-20, total 0-100)

```
Gate Compliance         how many violations, retries, did it halt?
Verification Integrity  SHA passed? unique hash? real output?
Process Discipline      skills loaded? mistakes consulted? diff focused?
Review Quality          PASS/SOFT_FAIL/HARD_FAIL, shadow gate, drift markers
Retro Value             7 questions answered? proposals generated?
```

## Grade Scale

```
90-100  EXCELLENT  — peak discipline
75-89   GOOD       — minor issues, self-corrected
60-74   FAIR       — multiple issues, tighten process
40-59   POOR       — significant drift
0-39    CRITICAL   — fundamental failure
```

## Report Format (auto-generated, saved to memory/latest_eval.txt)

```
EVALUATION REPORT — Pipeline #N
Task: ...
SCORES:
  Gate Compliance         : XX/20  <reason>
  Verification Integrity  : XX/20  <reason>
  Process Discipline      : XX/20  <reason>
  Review Quality          : XX/20  <reason>
  Retro Value             : XX/20  <reason>
TOTAL: XX/100 — GRADE
AGENT BEHAVIOR ANALYSIS:
  What happened:  ...
  What should be: ...
  Gap:            ...
RECOMMENDATIONS:
  1. ...
TREND: improving | stable | degrading
```

## Common Score Drops

```
Gate Compliance -5    each violation that needed a retry
Verification    -5    identical hash to previous run (cached output)
Process         -5    each of: no skills, no mistakes check, scope creep
Review          -5    drift markers (TODO/console.log/FIXME in diff)
```

## Next Steps

- Score < 75? → read the recommendations in the report
- Gate Compliance < 15? → add missing gates to `harness/gates.py`
- Process Discipline < 15? → update agent prompts in `agents/`
- Trend degrading? → run `skills/grill.md` on the pipeline design
