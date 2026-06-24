---
name: techne-handoff
description: Write a session handoff doc so any agent (or the same agent tomorrow) can resume the Techne pipeline without losing context. Mirrors OMO's /handoff + boulder.json pattern. Run at end of session or before a long break.
triggers:
  - techne handoff
  - session handoff
  - resume tomorrow
  - hand off session
  - write handoff
  - save session state
  - before I stop
---

# Techne Handoff — Session Continuity

## One Line

Write `.techne/loop/handoff.md` so the next session picks up exactly where this one stopped.

## Why This Exists

`.techne/loop/state.json` stores phase + task_id. It does NOT store: why this task, what was decided, what's blocked, what the next agent should do first. A new session reading only `state.json` has to reconstruct that from the audit chain — which is possible but slow. `handoff.md` is the fast path.

Reference: OMO's `/handoff` + `boulder.json` pattern.

---

## When to Run

- End of session with an active pipeline
- Before context compaction would discard important reasoning
- When another agent will pick up the work
- When you are interrupted mid-pipeline and need to preserve state

---

## What to Write

Run these lookups first, then write the document:

```bash
techne status          # current phase, task, stall status
techne doctor          # hook wired? audit chain intact? proposals pending?
cat .techne/loop/state.json       # phase + task_id
cat .techne/loop/ticket.md        # objective, constraints, done_when (if exists)
cat .techne/audit/chain.jsonl     # completed phases (last 5 entries)
cat .techne/audit/blocked.log     # recent blocks (if any)
```

---

## Handoff Document Format

Write to `.techne/loop/handoff.md`:

```markdown
# Techne Handoff — <YYYY-MM-DD>

## Active Task

- **Task ID:** <task_id from state.json>
- **Phase:** <current phase>
- **Objective:** <OBJECTIVE from ticket.md, or one-sentence summary>
- **DONE_WHEN:** <from ticket, or best current understanding>

## Phases Completed

| Phase | Status | Gate summary |
|---|---|---|
| RECALL | ✓ | <one-line summary of what was recalled> |
| IMPLEMENT | ✓ | <what was changed, diff size> |
| VERIFY | … | <test results if run> |
| CONCLUDE | … | |

(mark remaining phases as —)

## What's Blocked / Open

If `techne next` returned BLOCK_HITL or there are open questions:

- **Block:** <what the gate said>
- **Required input:** <what the next agent / human needs to decide>
- **Options considered:** <what was evaluated and rejected>

If nothing is blocked: "No open blocks. Resume with `techne next`."

## Next Action

The FIRST thing the resuming agent should do:

```
<exact command or instruction>
```

Examples:
- `techne next` (if artifact is already written)
- Write `.techne/loop/recall.txt` then `techne next`
- Fix the HONCHO line in `.techne/loop/conclude.txt` then `techne next`

## Context Pack

Key files the resuming agent should read:

- `.techne/loop/ticket.md` — full task spec
- `.techne/loop/<last_artifact>.txt` — most recent phase output
- `CONTEXT.md` — domain glossary (if it exists)
- <any other files critical to this task>

## Durable State (for Honcho)

If Honcho is available, save these before stopping:

```python
honcho_conclude(conclusion="Task <task_id>: <objective>. Currently in <phase> phase. Next: <next action>.", peer="user")
```
```

---

## Resume Protocol

When starting a session that has a handoff doc:

```bash
techne status          # confirm pipeline state matches handoff
cat .techne/loop/handoff.md    # read the handoff
```

Then act on "Next Action" in the handoff before doing anything else.

If `techne status` disagrees with the handoff (e.g. phase mismatch), trust `techne status` — the handoff may be stale. Run `techne doctor` to check integrity.

---

## Red Flags

- Handoff says phase=IMPLEMENT but state.json says RECALL → trust state.json, handoff is stale
- No ticket.md → reconstruct OBJECTIVE from audit chain and Honcho before handing off
- Audit chain tampered (`techne doctor` shows ✗) → report to user, do not resume until resolved

---

## Next Steps

- Handoff written → safe to end session
- Resuming from a handoff → read handoff, run `techne status`, follow "Next Action"
- Need to Honcho-checkpoint before compaction? → `skills/honcho-precompaction-checkpoint.md`
- Pipeline is DONE? → handoff is optional; use `techne status` instead for a quick summary
