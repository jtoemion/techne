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
| UI design decisions | `skills/ui-grill.md` |
| Prompting LLM for UI | `skills/ui-craft.md` |
| UI specificity standard | `skills/ui-physics.md` |
| Design-to-dev handoff | `skills/ui-handoff.md` |
| Reviewing agent output | `skills/evaluation.md` |
| Next.js specific rules | `skills/nextjs.md` |
| TypeScript type errors | `skills/typescript.md` |

## Always Loaded

These are injected for every task — do not skip:

- `skills/nextjs.md` — hard gates that will reject your diff (Next.js projects only)
- `skills/typescript.md` — hard gates that will reject your diff

**Scope note:** Techne's gates (`gate_no_redirect_outside_middleware`, `gate_no_router_import`, etc.) and its pipeline phases (IMPLEMENT → VERIFY → REVIEW → RETRO → EVALUATE) are designed for **Next.js full-stack projects**. For React 19 + Vite projects (e.g., pastpapr), the routing and middleware conventions don't apply. Load the skill for its sub-skill routing and ESLint/TypeScript pitfall references, but skip the Next.js-specific gate logic.

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
- Post-build bug analysis? → `references/bug-analysis-soaperfume.md` (live case study — 13 bugs, H-1 through L-4, with fix patterns)
- SvelteKit deployment issues? → `references/bug-analysis-soaperfume.md` (adapter-hosting mismatch, idempotent migrations, auth guards)
- Bug triage quick-ref? → `references/bug-analysis-soaperfume.md` (symptom → cause table for common SvelteKit/SQLite patterns)
