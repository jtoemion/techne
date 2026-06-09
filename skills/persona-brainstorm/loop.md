---
name: persona-brainstorm/loop
description: Auto-loop mechanics. Pause/resume on interrupts. When the loop continues, when it breaks, when Megumi calls Judah.
---

# The Auto-Loop

## Loop State

```
ACTIVE  → Ezekiel and Jeremiah dialoguing, Megumi documenting
PAUSED  → Judah interrupted. Loop state preserved. Resume from last unanswered question.
CLOSED  → natural close OR 3 ADRs reached OR Ezekiel out of contradictions
```

## Loop Continues When

```
- Megumi reads Jeremiah's KB (or draws from memory) to answer product questions
- Ezekiel surfaces a contradiction from code → asks Jeremiah one pointed question
- Jeremiah answers from KB → Ezekiel digs or pivots
- Jeremiah's answer is vague → Ezekiel pushes: "Specific example?"
- Question closes → Megumi marks Closed / ADR-N in CONTEXT.md
- New thread opens → Ezekiel pivots cleanly to it
```

## Loop Breaks When

```
- 3 ADRs drafted (cap reached)
- Ezekiel has no more acute contradictions
- Both Ezekiel + Jeremiah agree session complete
- Megumi calls Judah AND Judah's answer closes the thread
```

## Interrupt Handling (learned the hard way)

When Judah says *"quick interruption"* or any out-of-band review mid-loop:

```
1. STOP IMMEDIATELY — don't finish current question
2. Mark loop state PAUSED (not closed)
3. Save last unanswered question + temp-KB path
4. Handle Judah's interrupt
5. RESUME from last unanswered question
   ─ do NOT regenerate temp-KB
   ─ do NOT restart from G-Q1
   ─ gap tracking carries forward
```

**Anti-pattern**: regenerating temp-KB on resume. Wastes context, breaks gap continuity.

## Calling Judah (rare)

Megumi calls Judah ONLY when:

```
1. Jeremiah explicitly says "I don't know, ask the client"
2. Technical question exceeds knowledge base AND project context
3. Format correction needed (Megumi sees a rule violation)
```

Megumi does NOT call Judah for:
- Product/UX questions Jeremiah can answer
- Pace adjustment (the loop sets its own pace)
- Permission to continue

## Phase Structure (inside the loop)

```
Phase 1 — Orientation
  Megumi reads Jeremiah's KB for relevant domain context
  Ezekiel states what he knows from temp-KB + code
  Ezekiel asks ONE pointed question about the most acute contradiction

Phase 2 — Discovery (loop)
  Megumi answers from Jeremiah's KB (product friction, user pain)
  Ezekiel digs on most-real thread — pushes until concrete pain stated
  If Jeremiah's KB has no answer: Megumi infers from memory, flags "KB gap"
  If KB gap blocks resolution: Megumi calls Judah (not Ezekiel asking Judah)

Phase 3 — ADR Writing (inside the loop, not separate)
  Real improvement crystallizes → Ezekiel drafts ADR in real time
  Megumi confirms saved to docs/adr/

Phase 4 — Close
  Megumi confirms all G-Q# entries closed
  Megumi confirms ADRs written
  Megumi announces complete + pushes
```

## G-Q# Entry Format (Megumi writes to CONTEXT.md)

```markdown
## G-Q1: [short question]
- **Source**: temp-KB Section X / file:line
- **Status**: ✅ Closed | ⏸️ To Judah | ❌ Rejected | ADR-NNNN
- **Answer**: [Jeremiah's response, 1-2 sentences]
- **Closed**: YYYY-MM-DD HH:MM
```

## Common Mistakes (logged for retro)

```
Megumi bypassed Jeremiah, asked Judah         → product Q's go to Jeremiah first
Ezekiel asked 2 questions in one turn          → split. One at a time.
Loop restarted after interrupt                 → resume, don't restart
Soft answer accepted ("would be nice")         → demand specific user example
Temp-KB cached from previous session           → never cache. Regenerate.
```

## Next Steps

- Loop running smoothly, drafting ADR? → `skills/persona-brainstorm/adr.md`
- Persona acting out of role? → `skills/persona-brainstorm/personas.md`
- Session closing? → back to `skills/persona-brainstorm.md` (Output Checklist)
