# LEDGER — Decisions, Lessons & Disciplines

The method-level record: how the work was done and what was learned, so the
agent's approach refines — not just the skill files. Surfaced before each task.

- **DECISION**   — a choice about HOW to work + why (alternatives rejected)
- **LESSON**     — something learned about the process, with evidence
- **DISCIPLINE** — a method that worked and should be repeated

Distinct from `docs/adr/` (code architecture) and `memory/mistakes.md` (failures).
Written by the retro agent; `harness/ledger.py` reads/surfaces it.

<!-- New entries go below this line -->
## [2026-06-09T08:40:00Z] DECISION | session/skill-authoring
**What**   : Reconcile skill-creator, superpowers, and Techne house format into a three-layer stack (container/content/proof) branching on skill TYPE — not averaged.
**Why**    : The three contradict (MUSTs vs yellow-flags; hide-workflow vs summarize). Averaging cancels; a per-type decision rule keeps each where it's strongest.
**Skill**  : writing-skill
**Status** : ACTIVE

## [2026-06-09T08:41:00Z] DISCIPLINE | session/self-improvement
**What**   : Gate skill self-improvement on recurrence (2+) + human approval + structural validity. Evals are the regression NET, never the steering wheel.
**Why**    : Auto-editing skills from eval scores overfits and drifts (measured: n=2 on one rule was not enough to act). Same RED-first discipline applies to skill edits as to code.
**Skill**  : writing-skill
**Status** : ACTIVE

## [2026-06-09T08:42:00Z] LESSON | session/router
**What**   : Vendored capability skills must use SPECIFIC router keywords; generic ones (app/web/test) substring-match unrelated tasks and silently steal routes.
**Why**    : "app" matched "whatsapp"/"app router" and regressed the router eval — caught only by tests/evals/run_evals.py. Always run that suite after touching the router.
**Skill**  : none
**Status** : ACTIVE
