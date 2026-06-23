---
name: retro
description: Use when writing a retro, reflecting on a task, or logging lessons. WHEN-TO-USE only, no workflow summary.
triggers:
  - "write retro"
  - "reflect on task"
  - "log lessons"
  - "phase retro"
---

# Retro

One line: Write as if the user will read every line — flat or minimal retro is explicitly rejected by the format.

## Lead — Reject Gates

```text
Gate rejects (< 100 chars each):
  - "Clean" / "Minimal" / "No issues" → expand or fail
  - Must reference at least 2 completed phases by name
  - Must include: metrics table, what changed, what to keep/do differently
```

## Body

```text
Required format:
  METRICS: <task type> | <duration> | <gate results>
  WHAT CHANGED: <diff summary, 2-4 bullets>
  WHAT TO KEEP: <specific practices that worked>
  WHAT TO DO DIFFERENTLY: <specific mistakes made>

Substantive = the reader can act on it. Flat = "it was fine" is not retro.
```

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "The change was clean and minimal, retro doesn't need much" | Flat/minimal retro is explicitly rejected. The format enforces substance. |
| "No issues came up" | Every task has something to keep or do differently — if you can't find it, the retro is too shallow. |
| "Straightforward change, nothing to log" | Straightforward means the retro can be brief but not absent. The metric table still applies. |
| "I'll add more detail later" | Later means never. Retro is due at phase end. |

## Red Flags — STOP

- "Clean. Fix is minimal." — needs expansion
- "No issues" — every retro has keep/do-differently entries
- "Straightforward change" without substance — minimum metrics table required
- Retro < 100 chars total

## Next Steps

- Retro complete and substantive → `skills/skill-router.yaml`
