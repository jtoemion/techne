---
name: preflight
description: Use when preparing context before a task, running context amortization, or doing phase preflight. WHEN-TO-USE only, no workflow summary.
triggers:
  - "preflight"
  - "prepare context"
  - "context amortization"
  - "phase preflight"
---

# Preflight

One line: Full amortization requires all 5 files — incomplete amortization was explicitly called out. Do not substitute.

## Lead — 5 Required Files

```text
Complete amortization = all 5 present and current:
  1. project_digest.md    — what the project is and does
  2. handoff.md           — active tasks and recent decisions
  3. file_roles.md        — what each file does and why it exists
  4. commands.md          — how to run, build, test
  5. risk_boundaries.md   — what not to touch, what's dangerous

Plus: context_hash.txt — must reflect current state after any edit.
```

## Body

```text
Incomplete amortization (called out in retro):
  - "I'll create just the digest and hash" → wrong, all 5 required
  - "I'll add more later" → later means never, the files must be there now

If a file doesn't apply → NOT_NEEDED: <reason> — still must appear in the format.
```

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "I'll create just the digest and hash, that's enough" | All 5 files are required. Incomplete amortization was explicitly called out as the failure mode. |
| "I'll add more later" | Later means never. Files must be complete at phase end. |
| "This project is simple, not much to document" | Simple still needs file_roles and commands. NOT_NEEDED is valid with a reason. |
| "The context looks fine, no update needed" | Check the hash. If files changed, the hash must be recomputed. |

## Red Flags — STOP

- "digest and hash is enough" — all 5 files required
- "I'll add more later" — incomplete is a failure
- Missing any required file without NOT_NEEDED: reason
- Stale context_hash.txt

## Next Steps

- All 5 files present and current, hash verified → `skills/skill-router.yaml`
