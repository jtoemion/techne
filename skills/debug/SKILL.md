---
name: debug
description: Debugging methodology for FIX_OF tickets — the 6-phase diagnostic (diagnose → reproduce → hypothesize → instrument → fix → cleanup), TDD for debugging, and common pitfalls. Reference: agents/debugger.md.
triggers:
  - debug phase
  - debugging
  - fix_of
  - diagnostic
---

# Debug — Escalation Diagnostic Phase

## When to Use

DEBUG is called when:
1. The implementer failed the same task **2+ times**
2. The critique found a **CRITICAL** finding
3. The reviewer found a **HARD_FAIL** the implementer couldn't resolve

DEBUG does **not** re-implement. It diagnoses the root cause and produces the minimal fix that addresses exactly the failure.

## Required Skills to Load

Before doing anything, load these via `skill_view`:
- `skills/diagnose.md` — the 6-phase diagnostic method
- `skills/diagnose/feedback-loop.md` — 10 strategies for building the loop
- `skills/diagnose/<stack>.md` — stack-specific patterns (auto-detect via `skills/diagnose/stack_detect.py`)

## The 6-Phase Diagnostic

### Phase 1 — Feedback Loop

Build the fastest pass/fail signal you can:
- Failing test at the seam that reaches the bug
- curl/HTTP script against dev server
- CLI invocation + diff stdout vs known-good
- Throwaway harness — minimal subset, one function call

**Stop and report** if you cannot build a loop. Do not guess.

### Phase 2 — Reproduce

- Run the loop. Watch it fail.
- Confirm: matches what the REVIEWER/CRITIQUE described, not a nearby failure
- Capture exact symptom (error text, wrong value, timing issue)

### Phase 3 — Hypothesize

Generate 3–5 ranked hypotheses. Each must be falsifiable:

```
"If X is the cause → changing Y makes the bug disappear"
"If X is the cause → changing Z makes it worse"
```

If you can't state the prediction, the hypothesis is a guess — discard it.

### Phase 4 — Instrument

- One probe per hypothesis, one variable changed at a time
- Tag every debug log: `[DEBUG-a4f2]` — grep removes them all at cleanup
- Perf bugs: measure first (baseline timing), then bisect

### Phase 5 — Fix (Minimal)

- Write the failing test **FIRST** (confirm it fails)
- Apply the smallest possible fix
- Watch it pass
- Re-run Phase 1 loop against original scenario
- Run the full test suite

### Phase 6 — Cleanup

- [ ] All `[DEBUG-...]` tags removed (grep to confirm)
- [ ] Original repro no longer reproduces
- [ ] Root cause explained in output

## TDD for Debugging

Debugging follows TDD discipline — in reverse:

```
1. Write the test that reproduces the bug (it fails)
2. Fix the minimal thing that makes the test pass
3. Verify the full suite still passes
4. Remove debug instrumentation
```

Never debug without a failing test first. If you cannot write a test for the bug, you cannot verify the fix.

## Common Debugging Pitfalls

### Debugging without a feedback loop

If you can't reproduce the bug on demand, you are guessing. Stop and report: "Cannot build feedback loop — escalate to human."

### Fixing the symptom instead of the cause

If you change Y and the bug disappears but you don't know why, you haven't diagnosed it. The bug will resurface.

### Multiple changes at once

Changing two variables simultaneously means you don't know which one fixed it. One probe per hypothesis, one variable at a time.

### Forgetting to clean up debug instrumentation

Debug tags left in code become production noise. Always grep for `[DEBUG-` before returning.

### Calling a fix "done" without re-running the full test suite

The fix that resolves one failing test may break another. Full suite must pass.

### Assuming the bug is where the error appears

The visible error is often far from the root cause. Trace the data flow, not the error location.

## Output Format

```
DEBUGGER REPORT
Task: <task_id> | <task_title>
Escalation Reason: <implementer_failed | critique_critical | reviewer_hardfail>

ROOT CAUSE:
<1-2 sentence explanation of what's actually wrong>

DIAGNOSTIC PATH:
1. Built feedback loop: <how>
2. Reproduced: <exact symptom>
3. Hypothesis confirmed: <which one, what proved it>

FIX APPLIED:
  +N -M  path/to/file.ts  — <what the fix does>

TESTS:
  <test name> — was failing, now passes
  <full suite> — all pass

DEBUG TAGS CLEANED: YES | NO

VERDICT: FIXED | NOT_FIXABLE (explain why)
```

## Hard Constraints

- You diagnose, you don't re-implement — fix only the specific failure
- Every fix must have a failing test written **BEFORE** the fix
- If you can't build a feedback loop, stop and report — don't guess
- Remove all debug instrumentation before returning
- If the root cause is architectural (not a bug), recommend escalation to human

## Escalation to Human

If the root cause is not a bug (e.g., architectural mismatch, missing requirements, ambiguous spec), do not attempt a fix. Report:

```
ROOT CAUSE: Architectural — the implementation approach conflicts with <reason>
RECOMMENDATION: Human review required — this is not a code bug
```

## Reference

See `agents/debugger.md` for the full agent definition.

## Next Steps

- Debug complete? → Loop goes back to IMPLEMENT with the fix
- Debug fails? → BLOCK_HITL: "manual fix or abandon"
- Want to see past debug reports? → `memory/mistakes.md`
