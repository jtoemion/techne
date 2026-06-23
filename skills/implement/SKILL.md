---
name: implement
description: Use when about to make changes outside task scope or produce prose instead of a diff. Symptom-based: agent reaches for "while I'm here" or starts writing explanatory text instead of @@ diff markers.
triggers:
  - implement
  - write code
  - produce diff
  - make changes
---

# Implement

One line: Violating the letter violates the spirit — scope creep is the #1 source of rejected diffs.

## Lead — Output Format Gate

```text
All changes via @@...@@ diff markers. Minimum change — YAGNI.
Gate: reject if no @@ markers or prose替代diff.
```

## Body

```text
1. Diff only. No prose paragraphs in output.
2. YAGNI: implement exactly what the task requires, nothing more.
3. No "cleanup", no "refactor", no "while I'm here" additions.
4. If you find something broken, note it — do not fix it unless it's the task.
```

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "I'll clean up this one extra file since I'm here" | Scope creep. The task is the task. File another. |
| "This refactor will make the code better" | That's a second task. File it. |
| "Might as well fix this too" | You might not. The reviewer might not want it. Ask. |
| "The code is ugly but functional" | File a separate improvement issue. Don't fix it unprompted. |

## Red Flags — STOP

- "while I'm here" → stop. Stay in scope.
- "might as well fix this too" → stop. File it, don't do it.
- "let me refactor" → stop. That's a different task.
- Writing prose instead of diff → stop. Use @@ markers.

## Next Steps

- Diff written, scope confirmed → `skills/context-guard/SKILL.md`
- Back to `skills/skill-router.yaml`
