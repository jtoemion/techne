---
name: persona-brainstorm/adr
description: ADR template + writing rules specific to brainstorm sessions. Use when a real improvement has crystallized in the loop. Extends docs/adr/ADR-FORMAT.md.
---

# Writing the ADR

## When to Draft

```
✓ Jeremiah has surfaced a CONCRETE pain (with specific user example)
✓ Ezekiel can describe the friction in one sentence
✓ The improvement is SURGICAL — specific files/components named
✗ Improvement is "nice to have" — reject
✗ No verification criteria possible — reject
```

## Template (use this exact structure)

```markdown
# ADR-{NNNN}: {Short Title}

Date: YYYY-MM-DD
Status: Accepted
Session: persona-brainstorm-{session_id}

## Context

What's wrong or missing — ONE paragraph, specific, not aspirational.
Cite the friction Jeremiah described. Reference temp-KB if relevant.

## Decision

What we're doing. Concrete. Specific files/components named.

## What to build (v1)

Surgical scope. List specific files, features, UI components.
Example: "Add TutorSessionNoteModal at components/tutor/SessionNote.tsx,
3 fields (rating, note, growth_area), Firestore write on submit."

## What is deliberately excluded

v1 boundaries. State explicitly so scope doesn't creep post-hoc.
Example: "No backfill of existing sessions. No notification on submit.
No analytics dashboard — Phase 2."

## Why this is high-impact

Product-level rationale. How does this change the USER's WEEK, not the code's structure?
Example: "Tutors currently log notes in WhatsApp — context lost between sessions.
This makes session-to-session continuity visible to Heads of Academy."

## Verification

Specific acceptance criteria. Real tests a developer can run.
Example:
  - [ ] Tutor can submit a note in <30 seconds
  - [ ] Note shows in HoA dashboard within 5 seconds
  - [ ] Note persists across page reload (Firestore confirmed)
  - [ ] Empty fields blocked at form level (not on backend)
```

## File Naming + Numbering

```
docs/adr/ADR-NNNN-short-slug.md

NNNN = next available number (scan docs/adr/ first)
slug = 3-6 hyphenated words from title
```

## What Makes an ADR Real (not aspirational)

```
DEAD ADRs (reject these):
  "Improve UX"                          — too vague
  "Better onboarding"                   — no friction cited
  "Faster page loads"                   — no specific user impact
  "More flexible architecture"          — code-level, not product-level

LIVE ADRs (accept these):
  "Add TutorSessionNoteModal with 3 fields, Firestore write on submit"
  "Surface CohortViability warning with action: 'Escalate to HoA' button"
  "Replace WhatsApp registration with M0 Google Form, atomic write to Firestore"
```

## The Verification Test

If a developer reading the ADR cannot:
1. Find which file(s) to touch
2. List acceptance criteria as testable
3. Know what is explicitly OUT of scope

→ the ADR is not done. Push back, dig more, then draft again.

## After Drafting

```
1. Megumi saves to docs/adr/ADR-NNNN-slug.md
2. Megumi updates CONTEXT.md G-Q# entry: Status → ADR-NNNN
3. Loop continues (cap is 3 ADRs total, not 3 attempts)
4. On session close: ADR is included in SESSION.md handoff notes
```

## Next Steps

- ADR drafted, loop continues? → `skills/persona-brainstorm/loop.md`
- Hit the 3-ADR cap? → back to `skills/persona-brainstorm.md` (session close)
- Need the underlying ADR format? → `docs/adr/ADR-FORMAT.md`
- Implementing the ADR next? → `skills/implementer.md`
