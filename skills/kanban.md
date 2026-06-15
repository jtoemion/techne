---
name: kanban
description: The gate-free Techne lane for Kanban / multi-agent work — a second door into the SAME skillbase, sterile of conductor.py and the gates. Use when a Hermes (or any) board dispatches a subagent for non-code work: research, writing, planning, scraping. Not a copy of Techne; the same skills run without the code pipeline. For a code-change card, use the gated pipeline instead.
triggers:
  - kanban
  - kanban lane
  - dispatched subagent
  - multi-agent worker
  - gate-free
  - board worker
---

# The Kanban Lane (gate-free)

The board (Hermes) owns orchestration — cards, dispatch, fan-in, human gate,
delivery. We do NOT rebuild it. This lane is just how a dispatched subagent uses
Techne's skillbase WITHOUT the conductor or gates. Same skills, no cage. The
standard still holds (`skills/discipline.md`) — but YOU hold it, nothing enforces it.

## What populates into the worker (the same three, minus gates)

```
1. FRAMEWORK SKILLS   always-loaded rules (skill-router.yaml always_loaded)
2. GLOBAL DISCIPLINE  skills/discipline.md — the honest standard
3. ROUTED SKILL       route(card.Goal) over the SHARED skills/ — read, not copied
No conductor.py. No run_all_gates. No SHA test-hash. This is the sterile door.
```

## The loop (no pipeline, just honest work)

```
1. PICK     skill = route(card.Goal); read it as ADVICE, not a gate spec.
2. WORK     do the minimal honest task in your handed workspace.
3. CHECK    self-verify: deliverable exists where it should (persistent dir, not
            scratch), and the task is actually answered. No gate will catch this for you.
4. REPORT   return { outcome, summary, deliverable } for the board's close_task.
```

## Isolated knowledgebase (still true here)

```
A dispatched subagent shares NOTHING implicitly:
  - read the task + constraints from the CARD, not the repo's ambient memory.
  - shared cross-worker facts come from the item/board, not your private context.
  - report findings back; you can't write another worker's store. (skills/kanban/isolation.md)
```

## When a card is actually CODE work

```
Then the gate-free lane is the WRONG door — you want enforcement. Route that card
through the gated pipeline (conductor + gates), isolated via state_dir so parallel
cards don't collide. See skills/kanban/isolation.md → "running the gated lane isolated".
```

## Next Steps

- The honest standard you must self-hold → `skills/discipline.md`
- Isolated context + report-back shape → `skills/kanban/isolation.md`
- Verifying a worker's output (reviewer / bug-scout / explorer roles) → `skills/kanban/roles.md`
- Card is a code change → the gated pipeline (`skills/implementer.md`, gates apply)
- Keep Techne an RL skillbase: the gate-free lane logs no mistakes itself, so REPORT
  recurring problems in your summary → the host folds them into `memory/mistakes.md` /
  the ledger, where recurrence (2+) still drives the retro → skill-edit learning loop.
