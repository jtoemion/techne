---
name: eval
description: Scoring methodology for the EVAL phase — 100-point deterministic report across 5 dimensions. What the evaluator checks, how scores are computed, and how discrepancies between agent self-report and gate results are handled.
triggers:
  - eval phase
  - score report
  - evaluation
  - 100-point eval
---

# Eval — Pipeline Scoring Phase

## Who Reads This

The **parent agent** reads this to understand how the deterministic EVAL phase scores runs. Subagents do not interact with this phase directly.

## The Scoring Model

EVAL is a **0–100 deterministic score** computed from pipeline state — not a model judgment. It runs automatically after VERIFY and before RETRO.

```
IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → EVAL → RETRO → CONCLUDE
```

## Five Scoring Dimensions

Each dimension contributes up to 20 points.

| Dimension | Max | What It Measures |
|-----------|-----|------------------|
| Gate Compliance | 20 | Violations, retries, pipeline halts |
| Verification Integrity | 20 | SHA pass, unique hash, pass indicators |
| Process Discipline | 20 | Skills loaded, mistakes consulted, diff focus |
| Review Quality | 20 | Review result, shadow gate clean, drift markers |
| Retro Value | 20 | Retro ran, proposals produced, questions answered |

## How Scores Are Computed

### Gate Compliance (20 pts)

```
0   — pipeline halted (violations not correctable)
20  — zero gate violations
15  — 1 violation, corrected on retry ≤1
10  — violations ≤3, retries < max_retries
10  — violations corrected
5   — required max retries
```

### Verification Integrity (20 pts)

```
0   — test output missing or faked
5   — SHA gate failed
20  — SHA passed, unique hash, pass indicators present
15  — SHA passed but identical hash (possible cached output)
10  — SHA passed with caveats
```

### Process Discipline (20 pts)

```
Full 20 — skills loaded + mistakes consulted + diff focused + no scope creep
-10     — skills not loaded
-5      — mistakes.md not consulted
-5      — diff not minimal
-5      — scope creep detected
Floor 0
```

### Review Quality (20 pts)

```
20  — review PASS, shadow gate clean, no drift markers
15  — review PASS but drift_markers > 0
15  — review SOFT_FAIL (warnings only)
10  — shadow gate found issue gate missed
5   — review HARD_FAIL (rework required)
0   — review skipped
```

### Retro Value (20 pts)

```
20  — retro ran, 7 questions answered, produced proposals
20  — retro ran, 7 questions answered, clean run
10  — retro ran, <7 questions answered
10  — retro ran, stable run
5   — retro incomplete
0   — retro skipped
```

## Grade Thresholds

```
90+  EXCELLENT
75+  GOOD
60+  FAIR
40+  POOR
0+   CRITICAL
```

## What Eval Checks

EVAL reads from the orchestrator loop state:

- **`_build_eval_metrics(task_id)`** — assembles gate_violations, retries_used, sha_passed, hash_unique, output_existed, had_pass_indicators, skills_loaded, mistakes_consulted, diff_focused, scope_creep, review_result, shadow_gate_clean, drift_markers, retro_ran, retro_questions
- **`loop.submit_eval()`** — records the report and marks EVAL complete
- **`get_eval(task_id)`** — retrieves the stored EvalReport

## Discrepancies Between Agent Self-Report and Gates

If an agent self-reports clean but gates found violations, the score reflects the gate results — agents cannot self-report out of a gate violation. The evaluator uses deterministic state, not agent claims.

## Output

EVAL produces an `EvalReport` with:
- Per-dimension scores + reasons
- Total score + grade
- Behavior gap analysis
- Recommendations
- Trend vs. last 5 runs (improving / stable / degrading)

Report is written to `.techne/memory/latest_eval.txt` and appended to `.techne/memory/eval_history.json`.

## Hard Constraints

- EVAL is deterministic — no model judgment involved
- EVAL verdict is PASS if total ≥ 75, else SOFT_FAIL
- EVAL does not retry; it scores what already happened
- A SOFT_FAIL eval does not halt the pipeline — RETRO and CONCLUDE still run

## Next Steps

- After EVAL? → RETRO runs (pass or fail, every pipeline)
- Want to see current scores? → read `.techne/memory/eval_history.json`
- Changing scoring weights? → edit `harness/evaluator.py`
