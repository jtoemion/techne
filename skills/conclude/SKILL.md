---
name: conclude
description: Use when about to skip durable write-back to Honcho or close task without punch list sign-off. Symptom-based: agent says "honcho_conclude is enough" — gate checks state file, not API call.
triggers:
  - conclude task
  - write back
  - honcho conclude
  - close task
---

# Conclude

One line: Violating the letter violates the spirit — gate checks STATE FILE, not the API call. Write the ID manually if needed.

## Lead — Required Three Lines

```text
HONCHO: <done | ID: <40-char hex>>
DOCS: <done | NOT_NEEDED: reason>
CONTEXT: <sha: <40-char hex>>
```

All three required. SHA on CONTEXT must be 40-char hex. Gate checks the state file.

## Body

```text
1. Write HONCHO entry: task ID + outcome + key decisions.
2. Write DOCS entry: what was updated and why.
3. Write CONTEXT: snapshot of final state, SHA-1 hash.
4. Close punch list items from context-guard.
5. If honcho_conclude API fails → write the ID manually to state file.
```

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "I already used honcho_conclude" | Gate checks state file, not the API call. Verify the ID is written. |
| "The state file will update itself" | It won't. Write the ID manually if API call didn't persist. |
| "honcho_conclude is enough" | The gate reads the state file. If it didn't write, gate fails. |
| "I'll update docs later" | Later means never. Do it now or context drifts. |

## Red Flags — STOP

- "honcho_conclude is enough" → stop. Verify state file has the ID.
- "the state file will update itself" → stop. Write it manually.
- Skipping write-back to save time → write-back is the durable record. Do it.

## Next Steps

- All three lines complete, state file written → task closed
- Back to `skills/skill-router.yaml`
