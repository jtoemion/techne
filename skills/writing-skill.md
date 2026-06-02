---
name: writing-skill
description: How to write a new skill that obeys the Techne system. Newspaper inverted pyramid structure — most critical info at top, optional depth in sub-skills, Next Steps chain at the tail. Use when creating, auditing, or refactoring any skill file.
triggers:
  - write a skill
  - create a skill
  - new skill
  - skill template
  - audit skill
---

# Writing a Skill

## The Newspaper Rule (inverted pyramid)

```
HEADLINE  → frontmatter: name, description, triggers
LEAD      → the ONE most critical rule or quick-start (first section)
BODY      → examples, patterns, soft rules (middle sections)
TAIL      → ## Next Steps chain (always last, always present)
```

Reader stops at any line → most important thing already seen.
Optional depth → goes in sub-skills, not inline.

## Structure Rules

```
Entry card      ≤ 100 lines
Sub-skill       ≤ 150 lines
Frontmatter     required: name + description
                optional: triggers (for router)
Sections        short, code-heavy, no prose paragraphs
Next Steps      mandatory last section in every file
```

## What Goes Where

```
ENTRY CARD (skills/<name>.md)
  The what + the most critical rule + concrete quick-start
  Routes to sub-skills for depth

SUB-SKILLS (skills/<name>/<topic>.md)
  One focused topic per file
  Load only when that situation arises
  Always chain back to entry or forward to next step

RULE FILES (nextjs.md, typescript.md)
  Hard gates at the top (gate: yes marker)
  Soft rules below
  Quick patterns with code
  weight: high|medium|low annotations required
```

## Ecosystem Integration (required before publishing)

```
[ ] skill-router.yaml entry (id, condition, skill_path, weight)
[ ] CONTEXT.md — does this skill write to it? (grill, persona-brainstorm do)
[ ] docs/adr/ — does this skill create ADRs? (grill, persona-brainstorm do)
[ ] SESSION.md — is this skill session-aware? (mention in output checklist)
[ ] harness/gates.py — does this skill have enforceable rules? (add gate)
[ ] tests/test_<name>.py — required before merging
```

## The Compact Test

Read the first 10 lines. Can you answer:
- What does this skill do?
- When should I use it?
- What's the most critical rule?

If no → the lead is buried. Rewrite from the top.

## Next Steps

- Ready to write? → `skills/writing-skill/template.md` (copy-paste scaffold)
- Finished writing, need to review? → `skills/writing-skill/checklist.md`
- Adding gates for new rules? → `harness/gates.py` + `harness/skill-router.yaml`
- Adding to router? → `harness/skill-router.yaml`
