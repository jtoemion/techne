---
name: approval
description: Use when approving heavy-mode changes, reviewing sensitive modifications, or running phase approval. WHEN-TO-USE only, no workflow summary.
triggers:
  - "approve changes"
  - "heavy mode"
  - "sensitive change"
  - "phase approval"
---

# Approval

One line: Approval exists because human judgment is required — read the diff before approving. Auto-approve is a lie.

## Lead — Three Exit Paths

```text
APPROVE  → VERIFY + proceed to next phase
REJECT   → FAILED + halt, report reason
MODIFY   → IMPLEMENT + re-submit for approval

Read the diff before any decision. "Looks safe" is not an approval.
```

## Body

```text
Approval gates (heavy mode only):
  - Diff read and understood
  - Risk to critical paths assessed
  - Rollback plan identified
  - Exit path documented

Approve only what you can explain. Reject what you cannot.
```

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "The change is safe, approval is just a formality" | Approval exists because human judgment is required. Formality is a lie. |
| "Auto-approve this, it's low risk" | Low risk still requires a human to read the diff and confirm. |
| "Looks safe from the description" | The description is not the diff. Read the actual changes. |
| "I trust the implementer" | Trust is not verification. The gate exists for a reason. |

## Red Flags — STOP

- "auto-approve" or "approve by default"
- "just a formality" — it's not
- Approving without reading the diff
- "looks safe" without assessing the actual changes
- Skipping approval in heavy mode

## Next Steps

- Decision made (approve/reject/modify) → report to conductor → `skills/skill-router.yaml`
