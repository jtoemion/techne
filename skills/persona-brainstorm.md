---
name: persona-brainstorm
description: Persona-based discovery dialogue to surface ONE high-impact improvement. Ezekiel (dev) grills Jeremiah (client), Megumi documents, Judah observes. Auto-loop until natural close. Output → CONTEXT.md + docs/adr/.
triggers:
  - persona brainstorm
  - grill session
  - client dev dialogue
  - discover improvement
  - Ezekiel Jeremiah
---

# Persona Brainstorm

## Goal

Surface **one** high-impact improvement from real friction.
Not feature voting. Not aspiration. Friction.

## The Four-Persona Loop

```
Ezekiel  (Developer)    → reads code/docs, asks targeted questions
Jeremiah (Client)       → answers from full project context
Megumi   (Scribe)       → documents inline to CONTEXT.md + ADRs
Judah    (Human)        → observes silently. Intervenes only when called.
```

Auto-loop is the default. Do NOT ask Judah for permission to continue.

→ Full roles + rules: `skills/persona-brainstorm/personas.md`

## How It Runs

```
1. Megumi generates temp-KB (regenerated every session, never cached)
2. Megumi announces: "Session started. Ezekiel — you're up."
3. Ezekiel reads temp-KB, asks ONE pointed question about the most acute contradiction
4. Jeremiah answers from project knowledge
5. Ezekiel digs, pivots, or escalates to ADR
6. Megumi logs each Q&A as G-Q# in CONTEXT.md
7. Loop continues until natural close OR 3 ADRs drafted
```

→ Loop mechanics + pause/resume + interrupts: `skills/persona-brainstorm/loop.md`

## ADR Writing (inside the loop)

When a real improvement crystallizes:

```
Ezekiel states context → Jeremiah confirms pain → Ezekiel drafts ADR
→ Megumi saves to docs/adr/ADR-NNNN-slug.md
```

→ ADR template + when-to-write: `skills/persona-brainstorm/adr.md`
→ Base ADR format: `docs/adr/ADR-FORMAT.md`

## The Hard Rules (non-negotiable)

```
1. ONE question at a time. No piling.
2. Jeremiah is NOT Judah. If Judah answers, redirect.
3. No vague ADRs. "Improve UX" is dead. "Add TutorSessionNoteModal" is alive.
4. ADR from friction, not aspiration.
5. Cap at 3 ADRs. Three finished = good session.
6. Push to contradictions. Reject soft answers — demand specific examples.
7. Document in real time. Megumi writes as questions close.
8. Temp-KB regenerated every session.
9. Auto-loop default. No permission-asking.
```

## When to Run / When NOT to

| Run | Skip |
|---|---|
| Beginning of dev cycle | You already have a concrete spec |
| Before large feature investment | Judah wants a list of 10 features |
| Backlog grooming produces weak priorities | Stakeholders not aligned |
| Team senses "something is off" but can't name it | |

## Output Checklist

```
[ ] Temp-KB generated and visible
[ ] CONTEXT.md: G-Q# entries per question, status marked
[ ] docs/adr/: ≤ 3 new ADRs, one per confirmed improvement
[ ] SESSION.md: handoff note written (any next agent picks up cleanly)
[ ] Pushed to correct repo
```

## Next Steps

- Need the persona details? → `skills/persona-brainstorm/personas.md`
- Loop interrupted by Judah? → `skills/persona-brainstorm/loop.md` (pause/resume section)
- About to draft an ADR? → `skills/persona-brainstorm/adr.md`
- Already have a spec? → `skills/implementer.md` instead
- Bug, not a brainstorm? → `skills/diagnose.md` instead
