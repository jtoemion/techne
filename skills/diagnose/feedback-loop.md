---
name: diagnose/feedback-loop
description: 10 strategies for building a fast, deterministic pass/fail signal. Load this when Phase 1 of diagnose.md is unclear — you cannot reproduce the bug.
---

# Building a Feedback Loop

The loop is the skill. Without it, everything else is guessing.

## 10 Strategies (try in order)

```
1. FAILING TEST
   Write a test at whatever seam reaches the bug.
   Prefer integration-level — unit tests miss coupling bugs.

2. HTTP SCRIPT
   curl or fetch against a running dev server.
   Capture status, headers, body. Diff against known-good.

3. CLI + SNAPSHOT
   Run with fixture input. diff stdout vs saved expected output.
   Add --verbose flags to expose internal state.

4. HEADLESS BROWSER
   Playwright/Puppeteer — drive the UI, assert on DOM/console/network.
   Use for bugs that only manifest in a browser context.

5. TRACE REPLAY
   Capture a real HTTP request (HAR, curl, fetch log).
   Replay through the code path in isolation.
   Removes flakiness caused by real network/auth.

6. THROWAWAY HARNESS
   Spin up the minimum subset: one service, mocked deps.
   One function call that exercises the bug path.
   Goal: 5 lines that reproduce reliably.

7. FUZZ LOOP
   If output is "sometimes wrong" — run 1000 random inputs.
   Look for the pattern in what fails.
   Use random.seed() to make failures reproducible.

8. BISECTION
   Bug appeared between two states (commit, dataset, version)?
   Automate "boot at state X, check, repeat" → git bisect run

9. DIFFERENTIAL
   Run same input through old vs new version. Diff outputs.
   Works for regressions where you have a known-good baseline.

10. HITL BASH
    Last resort — human must click.
    Script the loop: prompt → human action → capture output → repeat.
    Even manual loops should be structured.
```

## Making the Loop Fast

```
Slow loop (>30s)  → barely better than no loop
Fast loop (<5s)   → debugging superpower

Speed levers:
  Cache setup steps       don't re-init on every run
  Narrow scope            skip unrelated initialization
  Pin time/randomness     freeze Date.now(), seed RNG
  Isolate filesystem      temp dir, clean between runs
  Freeze network          mock external calls
```

## Non-Deterministic Bugs

```
Goal: raise reproduction rate, not achieve clean repro.

- Loop the trigger 100× in parallel
- Inject sleep() at timing-sensitive paths
- Narrow the timing window by removing unrelated work
- 50% repro rate = debuggable
- 1% repro rate = not debuggable yet, keep raising
```

## When You Cannot Build a Loop

Stop. Say so explicitly. Ask for:
- Access to the environment that reproduces it
- Captured artifact: HAR, log dump, core dump, recording with timestamps
- Permission to add temporary production instrumentation

Do NOT hypothesize without a loop.

## Next Steps

- Loop built? → back to `skills/diagnose.md` Phase 2
- Loop built, need to instrument? → Phase 4 of `skills/diagnose.md`
