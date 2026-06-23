---
name: karpathy-guidelines
description: The default behavioral standard on every codebase task — surface assumptions instead of guessing, write the minimum honest code, change only what the request needs, and loop to a verifiable success criterion. Always-loaded for code work in both lanes. Use whenever writing, reviewing, or refactoring code.
license: MIT
triggers:
  - karpathy guidelines
  - default code behavior
  - coding behavior standard
---

# Karpathy Guidelines — the default behavior on code tasks

Four rules that catch the mistakes a capable model makes under pressure: it
assumes, it over-builds, it edits past the ask, and it stops before verifying.
Always-loaded for code work — the CONSTANT beneath whatever skill was routed.
Adapted from Andrej Karpathy's notes on LLM coding pitfalls (MIT).

**Tradeoff:** biases toward caution over speed. For a trivial one-liner, use judgment.

## 1. Think before coding — surface, don't assume

```
- State assumptions explicitly. Uncertain → ASK, don't guess.
- Multiple readings exist → present them. Never pick silently.
- A simpler approach exists → say so. Push back when warranted.
- Something unclear → STOP. Name what's confusing. Ask.
```

## 2. Simplicity first — minimum honest code

```
- No feature beyond what was asked.
- No abstraction for single-use code.
- No "flexibility"/"configurability" nobody requested.
- No error handling for impossible scenarios.
- 200 lines that could be 50 → rewrite it.
```

Test: *"Would a senior engineer call this overcomplicated?"* If yes, simplify.

## 3. Surgical changes — touch only what the ask needs

```
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor what isn't broken. Match existing style.
- Unrelated dead code → mention it, don't delete it.
- Orphaned by YOUR change → remove it. Pre-existing dead code → leave it.
```

Test: every changed line traces directly to the request.

## 4. Goal-driven execution — loop to a verifiable criterion

```
"Add validation"  → write tests for invalid inputs, then make them pass
"Fix the bug"     → write a test that reproduces it, then make it pass
"Refactor X"      → tests pass before AND after
```

Multi-step → state the plan, each step with its check:

```
1. [step] → verify: [check]
2. [step] → verify: [check]
```

Strong criteria let you loop independently; weak ones ("make it work") force
constant clarification. This is the RL spine: act → verify → repeat to GREEN.

## Why this is always-loaded, not routed

```
The routed skill is the VARIABLE (what to do). These four are the CONSTANT
(how any code work is held). They ride every code task in both lanes — the
gated pipeline ENFORCES them via gates; the Kanban lane SELF-CHECKS them.
```

## Next Steps

- Code-change task under gates → `skills/implementer.md`
- The honest standard both lanes share → `skills/discipline.md`
- Driving a step to GREEN test-first → `skills/tdd.md`
- Checking a diff obeyed rule 3 (surgical) → `skills/check-pr.md`
