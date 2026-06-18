---
name: diagnose
description: Disciplined debugging. Build a feedback loop first — everything else is mechanical. Use when something is broken, throwing, failing, or regressing.
---

# Diagnose

## Phase 1 — Feedback Loop (do this first, always)

Build the fastest pass/fail signal you can.

```
Quick options:
  1. Failing test at the seam that reaches the bug
  2. curl/HTTP script against dev server
  3. CLI invocation + diff stdout vs known-good snapshot
  4. Throwaway harness — minimal subset, one function call
```

Struggling to build the loop? → `skills/diagnose/feedback-loop.md` (10 strategies + non-deterministic bugs)

**Stop and report** if you cannot build a loop. Do not guess.

## Phase 2 — Reproduce

```
- Run the loop. Watch it fail.
- Confirm: matches what the USER described, not a nearby failure
- Capture exact symptom (error text, wrong value, slow timing)
```

## Phase 3 — Hypothesize

Generate 3-5 ranked hypotheses. Each must be falsifiable:

```
"If X is the cause → changing Y makes the bug disappear"
"If X is the cause → changing Z makes it worse"
```

If you can't state the prediction, the hypothesis is a guess — discard it.

## Phase 4 — Instrument

```
- One probe per hypothesis, one variable changed at a time
- Tag every debug log: [DEBUG-a4f2] — grep removes them all at cleanup
- Perf bugs: measure first (baseline timing), then bisect — never guess
```

## Phase 5 — Fix + Regression Test

```
1. Write failing test at correct seam BEFORE the fix
2. Watch it fail
3. Apply fix
4. Watch it pass
5. Re-run Phase 1 loop against original scenario
```

## Phase 6 — Cleanup

```
- [ ] Original repro no longer reproduces
- [ ] All [DEBUG-...] tags removed (grep to confirm)
- [ ] Root cause in commit message
```

## Anti-Patterns — Commit Review Trap

**The bug:** Reviewing only the *current* file state (what is) instead of the *commit delta* (what changed).

A commit message can say "fix X" but the diff may show the fix was never applied — the change was described but not executed. Reading `read_file` of HEAD after the commit misses this entirely.

**Signs you're falling into the trap:**
- You read `git log` and trust the commit subject
- You say "the fix was already applied" without running `git show HEAD`
- The commit message mentions specific code changes but your review doesn't verify each hunk

**The right loop:**
```
git show HEAD           # see what the commit actually changed
git show HEAD:file      # see previous version for comparison
```
Then verify: does the delta match what the message claims?

**This trap is especially dangerous on hotfix commits** — pressure to close the ticket leads to trusting "fix X" without verification.

## Framework patterns — `stack_detect.py` auto-loads by stack (read before Phase 4)

```
Svelte → skills/svelte.md   Next.js/TS → skills/nextjs.md
Firestore → skills/diagnose/firestore.md   Netlify → skills/diagnose/netlify.md
```

## Next Steps

- Have root cause, ready to fix? → `skills/implementer.md`
- Fix requires architectural change? → `skills/grill.md`
- Writing regression test? → `skills/tdd.md`
