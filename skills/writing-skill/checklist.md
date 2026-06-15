---
name: writing-skill/checklist
description: Pre-publish review for any new or refactored skill. Run through this before committing. Covers structure, newspaper test, ecosystem wiring, and test coverage.
---

# Skill Review Checklist

## Type Check (do this first — it sets the rest)

```
[ ] Type named: discipline/rule/gate OR technique/reference
[ ] Discipline → hardened per skills/writing-skill/discipline.md
[ ] Technique  → reasoned + measured per skills/writing-skill/evaluation.md
[ ] Description matches type (see Description Field below)
```

Wrong type = the proof and content checks below are checking the wrong things.

## Newspaper Test (read the first 10 lines)

```
[ ] Frontmatter present: name + description
[ ] First section = the most critical thing (not background, not history)
[ ] Reader knows what this skill does without scrolling
[ ] Reader knows the ONE rule they must follow without scrolling
```

If any box is empty → the lead is buried. Move the critical thing to the top.

## Structure

```
[ ] Entry card ≤ 100 lines
[ ] Each sub-skill ≤ 150 lines
[ ] Every file ends with ## Next Steps
[ ] Next Steps chains point forward AND back (not dead ends)
[ ] No prose paragraphs — code blocks, tables, bullet lists only
[ ] No general documentation — only gotchas, gates, and patterns
```

## Rule Files (nextjs.md, typescript.md pattern)

```
[ ] Hard gates marked: # weight: high | gate: yes
[ ] Soft rules marked: # weight: medium | gate: no
[ ] Gate function exists in harness/gates.py
[ ] Gate added to ALL_GATES list in gates.py
[ ] Quick Patterns section has working code, not pseudocode
```

## Ecosystem Wiring

```
[ ] skill-router.yaml — entry added with correct weight
    (check weight table in skills/writing-skill/template.md)
[ ] Disambiguation entry if skill overlaps with another
[ ] CONTEXT.md — mentioned in Output section if skill writes to it
[ ] docs/adr/ — mentioned if skill creates ADRs
[ ] SESSION.md — output checklist includes session handoff note
```

## Proof It Works (by type — not optional)

Structural tests prove the skill is well-formed, never that it's good.
RED-first either way: watch the baseline before you trust the skill.

**Discipline / rule / gate skills:**
```
[ ] Watched an agent fail the baseline WITHOUT the skill (rationalizations logged)
[ ] Agent complies WITH the skill under 3 stacked pressures
[ ] Rationalization table + red-flags list present and built from RED (not imagined)
[ ] gates.py checked: gate written if diff-visible; NOT stamped gate:yes if it can't fire
```

**Technique / reference skills:**
```
[ ] Ran with-skill vs without-skill on 2-3 realistic prompts
[ ] with-skill is clearly better (else the skill is dead weight — cut it)
[ ] No fix that only helps the test cases (overfit check)
```

**Both:**
```
[ ] Triggering eval: fires on should, silent on should-not
[ ] Near-miss written against each sibling skill it could collide with
```

## Description Field (CSO, by type)

```
[ ] Discipline w/ mandatory workflow → WHEN-to-use ONLY, no step summary
[ ] Technique/reference → what + when, keyword-rich, a touch pushy
```

See `skills/writing-skill/evaluation.md` and `skills/writing-skill/discipline.md`.

## Tests (required before committing)

```
[ ] tests/test_<name>.py exists
[ ] test_file_structure() — all files exist with content
[ ] test_router() — correct routing for trigger phrases
[ ] test_next_steps() — every file has ## Next Steps
[ ] test_compact() — line count within limits
[ ] All tests passing
```

## Real-World Smell Test

Read the skill as if you just sat down cold with a task.

```
[ ] "I know exactly what to do after reading the first section"
[ ] "I know where to go next without scanning the whole file"
[ ] "There is no sentence I could delete and lose critical info"
[ ] "There is no sentence I must keep that belongs in a wiki instead"
```

## Common Mistakes (from retro log)

```
Prose intro before the lead       → reader skips it anyway. Cut it.
MUST in a TECHNIQUE skill          → no adversary there; reframe with the why
MUST in a DISCIPLINE skill         → legitimate, but a real gate beats it. Promote if gate-able.
Hard rule left as prose            → unenforced. Promote to gates.py.
Rationalization table imagined     → must be built from a watched RED baseline
Description leaks the workflow     → discipline body gets skipped. When-to-use only.
Fix that only helps the test cases → overfit. Generalize or revert.
Next Steps missing or vague        → "see documentation" is not a chain
Sub-skill longer than entry        → extract another layer or merge back
No baseline watched (RED skipped)  → unproven. Don't merge.
No tests                           → skill is unverifiable, don't merge
```

## After All Boxes Checked

```
1. git add skills/<name>.md skills/<name>/ tests/test_<name>.py harness/skill-router.yaml
2. git commit -m "feat: add <name> skill — <one-line description>"
3. git push origin master
```

## Next Steps

- Discipline skill not yet hardened? → `skills/writing-skill/discipline.md` (do this first)
- Technique skill not yet measured? → `skills/writing-skill/evaluation.md` (do this first)
- Checklist passes? → commit and push
- Gate needed for a rule? → `harness/gates.py` → `ALL_GATES` list
- Skill feels too long? → apply newspaper test, extract to sub-skill
- Back to the template? → `skills/writing-skill/template.md`
