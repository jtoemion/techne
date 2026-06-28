---
name: techne
description: Run a task through Techne's enforced pipeline (RECALL → IMPLEMENT → VERIFY → CONCLUDE → DONE). Works in Hermes Agent and Claude Code.
---

You are running a Techne pipeline task.

## Before you start

1. Verify enforcement: `techne doctor`
2. Inventory available skills:
   ```bash
   ls .hermes/skills/   # Hermes-native skills
   ls skills/            # Techne skill library
   ```
3. Check active pipeline: `cat .techne/loop/state.json`
4. If no pipeline: `techne init <task-id>`

## Phase sequence

```
RECALL → IMPLEMENT → VERIFY → CONCLUDE → DONE
```

At each phase, select the best available skill from `.hermes/skills/` or `skills/`.
You are not limited to Techne's library — use `omh-deep-research`, `omh-ralplan`,
`omh-deep-interview`, or any installed Hermes skill as the task demands.

## Phase artifacts

| Phase | Artifact | Required content |
|---|---|---|
| RECALL | `.techne/loop/recall.txt` | `WORKSHOP_CONTEXT:` header |
| IMPLEMENT | `.techne/loop/diff.txt` | `@@` and `--- ` diff markers |
| VERIFY | `.techne/loop/test_output.txt` | pass indicators |
| CONCLUDE | `.techne/loop/conclude.txt` | `HONCHO: <id>` line + retro markers |

## Gate checkpoints (before each `techne next`)

```bash
# IMPLEMENT phase only:
techne gate hashline .techne/loop/diff.txt
techne gate forbidden .techne/loop/diff.txt

# All phases:
techne next    # advances phase, prints report
```

## HITL — stop and surface to user when

- `techne next` exits non-zero — show full report, do NOT edit state.json
- Hashline gate rejects the diff — re-read the named files, regenerate diff
- VERIFY finds failing tests — fix and re-run, do not skip ahead
- Any decision requires human judgment (design choice, credential, architecture)

## Skill routing guide

| Task type | Recommended skill |
|---|---|
| Deep research needed at RECALL | `omh-deep-research` |
| Complex plan needs consensus | `omh-ralplan` |
| Requirements unclear | `omh-deep-interview` |
| Plan needs stress-test | `skills/grill` |
| Issue backlog triage | `omh-triage` |
| Standard implementation | direct (no skill needed) |

## Health commands

```bash
techne status    # current phase + stall check
techne doctor    # enforcement health check
techne handoff   # write session continuity doc
```

${{args}}
