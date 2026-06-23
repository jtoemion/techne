---
name: recall
description: Use when about to skip Honcho search and implement from memory instead. Symptom-based: agent has context in conversation and reaches for "I already know" rather than searching.
triggers:
  - search honcho
  - recall context
  - run recall
---

# Recall

One line: Violating the letter violates the spirit — you do not have durable facts until you search.

## Lead — Required Output Lines

```text
HONCHO_CONTEXT: <from honcho search>
WORKSHOP_CONTEXT: <from honcho search>
```

Both lines MUST appear in your output before implementation begins. Gate rejects without them.

## Body

```text
1. Run: honcho search <task-keywords>
2. Pull HONCHO_CONTEXT + WORKSHOP_CONTEXT lines verbatim into your output
3. Proceed only after both lines are present
```

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "I already know the context from the conversation" | Conversation context is not durable. The model forgets mid-session. |
| "Honcho is slow, I'll just implement" | Honcho is indexed. Slow is 2 seconds. Wrong is 20 minutes. |
| "The user just told me what to do" | User intent is in Honcho. What they told you is their gloss, not the spec. |

## Red Flags — STOP

- "I already know this" → stop. Search honcho.
- "Let me skip recall and just implement" → stop. Search honcho.
- "The context is clear from the conversation" → stop. Search honcho.

## Next Steps

- Honcho search complete → `skills/implement/SKILL.md`
- Back to `skills/skill-router.yaml`
