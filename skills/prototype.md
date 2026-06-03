---
name: prototype
description: Build a throwaway prototype to answer ONE design question before committing to it. Routes to a runnable terminal app for state/logic questions, or several toggleable UI variations for look-and-feel questions. Use to sanity-check a data model or state machine, mock up a UI, or explore options.
triggers:
  - prototype this
  - throwaway prototype
  - mock up a UI
  - try a few designs
  - sanity-check the state model
---

# Prototype

> Adapted from mattpocock/skills.

## The One Rule

**A prototype is throwaway code that answers ONE question.** Name the question
first — it decides everything. The only thing you keep is the *answer*, captured
somewhere durable. The code gets deleted or absorbed.

## Pick the branch (the question decides)

```
"Does this logic / state model feel right?"  → LOGIC branch
    Tiny interactive terminal app that pushes the state machine through the
    cases that are hard to reason about on paper.

"What should this look like?"                → UI branch
    Several radically different UI variations on ONE route, switchable via a
    URL search param + a floating bottom bar.
```

Wrong branch wastes the whole prototype. If ambiguous and the user is away,
match the surrounding code (backend module → LOGIC, page/component → UI) and
state the assumption at the top.

## Rules (both branches)

```
1. Throwaway from day one — name it so a reader sees it's not production
2. One command to run     — whatever the project's task runner already uses
3. No persistence         — state in memory; persistence is what you're testing
4. Skip polish            — no tests, no error handling beyond "runnable", no abstractions
5. Surface state          — print/render full relevant state after every action/switch
6. Delete or absorb       — when the question is answered, don't let it rot
```

## When done

```
Capture the ANSWER + the question it answered, somewhere durable:
  commit message | docs/adr/ | NOTES.md next to the prototype
Then delete the prototype or fold the validated decision into real code.
```

If the decision was hard, surprising, and had real trade-offs → write it as an
ADR (`docs/adr/ADR-FORMAT.md`), same bar as `skills/grill.md`.

## Next Steps

- Prototype answered the design question? → `skills/grill.md` to lock the interface
- Ready to build the real thing? → `skills/implementer.md` (and delete the prototype)
- Question was "what should we even build?" not "how" → `skills/persona-brainstorm.md`
- Found a bug while prototyping? → it's throwaway; note it, don't `skills/diagnose.md` yet
