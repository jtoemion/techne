# RETRO Phase Visibility + Context Refresh Display — 2026-06-19

## Problem 1: RETRO content never reaches the user

The RETRO phase content goes to `loop.submit(task_id, "RETRO", retro_report)` which writes to task_db events. The user never sees it unless the host agent prints it to the terminal.

During the Ms. Ellen handoff session, the host submitted one-liner RETROs just to advance the gate. The user asked "why i never see any retro?" — a frustration signal.

### The Fix

After every RETRO submission, print the RETRO content to the terminal:

```python
outcome = loop.submit(task_id, "RETRO", retro_report)
print(f"RETRO: {outcome.action}")
print(retro_report)  # <-- THIS LINE was missing
```

## Problem 2: Context refresh changes are invisible

Every pipeline run potentially touches `.techne/context/` files (project_digest, commands, risk_boundaries, handoff, context_packs, etc.). Future agents have no idea what changed unless the host agent tells them explicitly.

### The Fix

After every pipeline run (fast or full), immediately after CONCLUDE/DONE, the host agent MUST print a summary of all context files that were created or modified:

```
CONTEXT REFRESH:
  CREATED: .techne/context/context_packs/techne.md
  MODIFIED: .techne/context/project_digest.md
  MODIFIED: .techne/context/handoff.md
  UNCHANGED: .techne/context/commands.md
  HASH: fd5eae0d... (old) → 03b5f7ad... (new)
```

This gives the next agent or reviewer a clear delta of what changed in the shared context without having to diff everything manually.

## RETRO Gate Requirements

The RETRO gate rejects one-liners. It wants explicit references to completed phases:
- RECALL: what context was recalled and whether it was sufficient
- IMPLEMENT: what changed, did the diff pass on first try
- CONTEXT_GUARD: scope verification result
- CRITIQUE: findings, severity, blocking status
- REVIEW: security/correctness/gate compliance
- VERIFY: test results, SHA gate hash
- EVAL: score breakdown

## RETRO Template

```markdown
RETRO — referencing completed phases: RECALL, IMPLEMENT, CONTEXT_GUARD, CRITIQUE, REVIEW, VERIFY, EVAL

RECALL: [what context was recalled and whether it was sufficient]
IMPLEMENT: [what changed, gate pass/retry, test count]
CONTEXT_GUARD: [scope verification result]
CRITIQUE: [findings summary, any BLOCK_HITL]
REVIEW: [security/gate compliance result]
VERIFY: [test numbers, SHA hash]
EVAL: [score]

WHAT WENT WELL: [specifics]
WHAT COULD IMPROVE: [specifics]
LESSONS: [actionable items for next session — these become skill edits or memory updates]
```

## Context Refresh Display Template

After every pipeline run, before CONCLUDE or DONE is finalized:

```python
# After all work is done, before CONCLUDE/DONE
import hashlib
from pathlib import Path

base = Path(".techne/context")
old_hash = (base / "context_hash.txt").read_text().strip() if (base / "context_hash.txt").exists() else "none"

files = [
    base/"project_digest.md",
    base/"file_roles.md",
    base/"commands.md",
    base/"risk_boundaries.md",
    base/"handoff.md",
    base/"context_packs/techne.md",
]
h = hashlib.sha256()
for p in files:
    if p.exists():
        h.update(p.read_bytes())
        h.update(b"\0")
new_hash = h.hexdigest()

print("CONTEXT REFRESH:")
for p in files:
    status = "CREATED" if not hasattr(p, 'exists') or p.exists() else "MISSING"
    if p.exists():
        status = "CREATED" if p.stat().st_size < 50 else "MODIFIED"
    print(f"  {status}: {p}")

diff_note = ""
if old_hash != new_hash:
    diff_note = f"\n  HASH: {old_hash[:12]}... (old) → {new_hash[:12]}... (new)"
elif old_hash != "none":
    diff_note = "\n  HASH: unchanged"
else:
    diff_note = "\n  HASH: none → new"

print(diff_note)
```

## Enforcer Rules

1. **RETRO must print** — host MUST `print(retro_report)` after every `loop.submit(..., "RETRO", ...)` call
2. **Context refresh MUST display** — host MUST print the context refresh summary after every pipeline run, before CONCLUDE/DONE
3. **RETRO must be substantive** — gate rejects < 100 chars or output with no phase references. No "Clean. Fix is minimal." Checkbox retros get retried.
