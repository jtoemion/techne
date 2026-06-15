---
name: kanban-isolation
description: How a dispatched Techne subagent handles its isolated knowledgebase — read context from the card, report results back instead of writing shared stores — plus the state_dir mechanics for the rarer case of running the GATED pipeline isolated. Sub-skill of skills/kanban.md.
---

# Kanban Worker — Isolation & Report-Back

A dispatched subagent's knowledgebase is isolated. It shares nothing implicitly.
Two boundaries always apply; the third only when the card runs the gated pipeline.

## 1. Context — read the card, not the repo

```
The worker did NOT inherit CONTEXT.md, mistakes.md, or the ledger — its KB is empty
of repo memory. So:
  - task + constraints come from the CARD BODY (the board inlines them, the way the
    Hermes engine inlines scope rails / specs so the worker always sees them).
  - the routed skill comes from route(card.Goal) over the SHARED skills/.
  - shared cross-worker facts come from the item/board file, which the worker reads.
Never assume ambient knowledge an isolated subagent cannot have.
```

## 2. Result — report back, do not merge

```
The worker CANNOT write the parent's stores — it can't even see them. At the end:
  RETURN { outcome: pass|fail, summary: str, deliverable: <persistent path> }
  - deliverable MUST be in a persistent dir, not scratch (the stranded-file footgun).
  - the gate-free lane has nothing that auto-logs problems → fold them into summary
    so Techne's recurrence learning can still hear about them. The HOST records.
```

## 3. State — ONLY when this card runs the GATED pipeline

```
Most Kanban work is the gate-free lane (no conductor, no shared run-state → nothing
to isolate). But if a card IS code work and you run the gated pipeline in parallel:
  checkpoint.py state is single-writer (memory/harness-state.json) — parallel runs
  clobber the run counter + verify flag. Set a per-worker dir:
    export TECHNE_STATE_DIR=<workspace>/.techne/
  store.state_dir() then routes harness-state.json / run artifacts there.
  Unset → memory/ as before. Proven in tests/test_kanban.py.
```

## Next Steps

- Back to the gate-free lane → `skills/kanban.md`
- The standard you self-hold → `skills/discipline.md`
- The state_dir resolver → `harness/store.py`; checkpoint → `harness/checkpoint.py`
