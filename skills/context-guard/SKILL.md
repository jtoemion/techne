---
name: context-guard
description: Use when about to change code without checking or updating related docs/context. Symptom-based: agent finishes a diff and moves straight to commit without running the audit.
triggers:
  - audit changes
  - check scope
  - run context guard
---

# Context Guard

One line: Violating the letter violates the spirit — every change needs a punch list entry, even NOT_NEEDED.

## Lead — Conclude Punch List Format

```text
DOCS: <done | NOT_NEEDED: reason>
CONTEXT: <done | NOT_NEEDED: reason>
HONCHO: <done | NOT_NEEDED: reason>
```

All three required. NOT_NEEDED requires a reason. Silence is not compliance.

## Body

```text
1. Audit every changed file against its docs/context/HONCHO entry.
2. If related docs exist and change is substantive → update them.
3. If related docs exist and change is trivial → NOT_NEEDED: <why it's trivial>.
4. If no related docs exist → NOT_NEEDED: <why none apply>.
5. Write the punch list BEFORE concluding, not after.
```

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "This change is too small to need docs" | Every change needs at minimum NOT_NEEDED: <reason>. |
| "I'll update docs later" | Later means never. Do it now or it drifts. |
| "This doesn't affect docs" | Run the audit. If it truly doesn't, note NOT_NEEDED. |
| "The docs are already up to date" | Verify by running the audit, not by assumption. |

## Red Flags — STOP

- "this doesn't affect docs" → run the audit first.
- "I'll update docs later" → stop. Do it now.
- Moving to commit without punch list → stop. Complete the audit.

## Next Steps

- Punch list complete → `skills/critique/SKILL.md`
- Back to `skills/skill-router.yaml`
