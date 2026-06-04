---
name: techne
description: Harness engineering entry point. Routes to the right sub-skill based on what you're doing. Always read this first — never browse skills/ directly.
---

# Techne — Skill Router

## Quick Route

| You're doing... | Load this |
|---|---|
| Building a feature or fix | `skills/implementer.md` |
| Something is broken | `skills/diagnose.md` |
| Writing tests first | `skills/tdd.md` |
| Stress-testing a plan | `skills/grill.md` |
| Discovering what to build | `skills/persona-brainstorm.md` |
| Prototyping a design question | `skills/prototype.md` |
| Finding refactor/architecture wins | `skills/improve-architecture.md` |
| Checking a pull request (one pass) | `skills/check-pr.md` |
| Iterating a PR to a perfect review | `skills/greploop.md` |
| Writing a new skill | `skills/writing-skill.md` |
| Reviewing agent output | `skills/evaluation.md` |
| Next.js specific rules | `skills/nextjs.md` |
| TypeScript type errors | `skills/typescript.md` |

## Always Loaded

These are injected for every task — do not skip:

- `skills/nextjs.md` — hard gates that will reject your diff
- `skills/typescript.md` — hard gates that will reject your diff

## Pipeline Phases

```
IMPLEMENT → VERIFY → REVIEW → RETRO → EVALUATE
```

Each phase is a separate agent. Only the conductor advances phases.
Gates run in Python — agents cannot self-report a pass.

**After every phase: call `p.get_status()` — display the output.**
Shows phase results, checkpoint summary, and live eval preview (scores per dimension + total + trend). This is mandatory every time the pipeline is used.

## Next Steps

- Building something? → `skills/implementer.md`
- Debugging? → `skills/diagnose.md`
- Not sure what to do first? → `skills/grill.md`
