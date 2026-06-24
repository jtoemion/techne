---
name: ultrawork
description: Autonomous loop trigger. Type 'ultrawork' or 'ulw' to run the full Techne pipeline (interview → init → RECALL → IMPLEMENT → VERIFY → CONCLUDE → DONE) hands-free, surfacing only HITL blocks and phase reports. Inspired by OMO's ultrawork mode.
triggers:
  - ultrawork
  - ulw
  - just do it
  - run autonomously
  - full autonomous loop
  - run the pipeline autonomously
---

# Ultrawork — Autonomous Pipeline Loop

## One Line

`ultrawork` = hands-free Techne from blank prompt to DONE, surfacing only HITL blocks and required decisions.

## What It Does

```
ultrawork <task description>
  │
  ├─ 1. techne-interview  →  Decision-Complete ticket (if no ticket exists)
  ├─ 2. techne init       →  pipeline state RECALL
  ├─ 3. RECALL phase      →  delegate_task + ./next
  ├─ 4. IMPLEMENT phase   →  delegate_task + ./next
  ├─ 5. VERIFY phase      →  run tests + ./next
  ├─ 6. CONCLUDE phase    →  honcho write-back + ./next
  └─ 7. DONE              →  phase report forwarded to user
```

The host agent drives every phase. Subagents do the work. You (the host) surface ONLY:
- HITL blocks (the loop cannot proceed without a human decision)
- Phase reports (full `./next` output after each advance)
- Final summary on DONE

**Do not narrate intermediate steps.** The user said "just do it" — give them the result.

---

## Before Launching

Check the pre-conditions:

```bash
techne status          # is there an active pipeline? if DONE or no pipeline, safe to start
techne doctor          # is the hook wired? is the audit chain intact?
```

If `techne status` shows an active STALLED pipeline: surface it to the user and wait for direction before overwriting.

---

## Trigger Words

| Word | What it starts |
|---|---|
| `ultrawork <desc>` | Full pipeline from interview → DONE |
| `ulw <desc>` | Alias for ultrawork |
| `ultrawork --no-interview` | Skip interview, use ticket already in `.techne/loop/ticket.md` |
| `scout <topic>` | SCOUT mode (RECALL phase only — research and report, no IMPLEMENT) |
| `grill <plan>` | Adversarial review of an existing plan (→ `skills/grill.md`) |

---

## Loop Mechanics

### Phase 1 — Interview (unless --no-interview)

Load `skills/techne-interview/SKILL.md`. Run until a Decision-Complete ticket is written to `.techne/loop/ticket.md`. Then call `techne init <TASK_ID>`.

### Phase 2 — RECALL → IMPLEMENT → VERIFY → CONCLUDE

For each phase:
1. Call `loop.next_phase(task_id)` — or run `techne next` — to get the current gate requirements
2. `delegate_task(prompt)` with the phase prompt to a subagent
3. Subagent writes the artifact (`recall.txt`, `diff.txt`, `test_output.txt`, `conclude.txt`)
4. Call `techne next` to run gates and advance

If `techne next` returns BLOCKED:
- Summarize the gate failure to the user
- Offer the debugger (`skills/debug/SKILL.md`) or request direction
- Do NOT edit `state.json` to skip the gate

### HITL Blocks

When `techne next` returns `BLOCK_HITL`:
- Surface the full block message to the user
- Pause and wait for input
- Resume with `techne next` after the user resolves the block

### Phase Reports

After every successful `techne next`, forward the full phase report to the user. Do not summarize. The report is actionable intelligence — the user needs the raw gates/artifact details.

---

## VERIFY — Real Tests Only

The SHA gate rejects faked test output. VERIFY must run real tests:

```bash
python3 -m pytest tests/ -v > .techne/loop/test_output.txt
techne next
```

Do not ask a subagent to "generate test output". Run the actual suite.

---

## Done Summary

On DONE, emit a summary block:

```
══ ULTRAWORK DONE ══════════════════════════════════
Task:    <task_id>
Phases:  RECALL → IMPLEMENT → VERIFY → CONCLUDE
Result:  <one-line OBJECTIVE from ticket>
Tests:   <pass count / total>
RL:      reward=<score> advantage=<delta>
Handoff: run `techne handoff` to write a session handoff doc
════════════════════════════════════════════════════
```

---

## Red Flags — STOP

- `techne doctor` shows hook not wired → wire it first (`skills/techne-handoff.md` has the settings path)
- `techne status` shows STALLED pipeline → surface to user, do not auto-overwrite
- VERIFY gate rejects output 3× → escalate with debugger, do not retry blindly
- Gate returns `FAILED` (terminal) → report to user, do not try to resume

---

## Next Steps

- Pipeline complete → `skills/techne-handoff/SKILL.md` to write a session handoff doc
- Gate blocking repeatedly → `skills/debug/SKILL.md`
- Want a plan review before running → `skills/techne-interview/SKILL.md` then `skills/grill.md`
- Need the phase report interpreted → forward it verbatim, then ask the user
