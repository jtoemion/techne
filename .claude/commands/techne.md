---
description: "Run a task through Techne's enforced pipeline (RECALL → IMPLEMENT → VERIFY → CONCLUDE → DONE)."
---

You are running a Techne pipeline task. Follow these rules exactly.

## Before you start
- Check if a pipeline is active: run `techne status`
- If no pipeline: run `techne init <task-id>` first
- Read the current phase requirements before writing anything

## Phase artifact requirements
| Phase | Artifact | Required content |
|---|---|---|
| RECALL | `.techne/loop/recall.txt` | Must contain `WORKSHOP_CONTEXT:` header |
| IMPLEMENT | `.techne/loop/diff.txt` | Must contain `@@` and `--- ` diff markers |
| VERIFY | `.techne/loop/test_output.txt` | Must contain pass indicators (passed/0 errors/✓) |
| CONCLUDE | `.techne/loop/conclude.txt` | Must contain `CONTEXT: sha:<40-char-sha>` |

## The loop
```
techne init <task-id>
# write RECALL artifact
techne next
# write IMPLEMENT artifact (git diff output)
techne next
# run tests, write output to VERIFY artifact
techne next
# write CONCLUDE artifact
techne next
# pipeline reaches DONE
```

## Rules
1. Write the phase artifact BEFORE calling `techne next`
2. If `techne next` returns BLOCKED, fix the gate violation — never skip
3. Never write to `.techne/audit/` — audit trail is tamper-evident and off-limits
4. The PreToolUse hook enforces phase discipline — blocked writes mean fix the violation

${{args}}
