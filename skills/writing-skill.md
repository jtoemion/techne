---
name: writing-skill
description: Use this skill when creating, auditing, or refactoring any skill file in the Techne system. Covers structure, description quality, gotchas, calibration, and the Newspaper test. Also use when a skill isn't triggering reliably, feels too long, buries the critical rule, or is missing gotchas.
triggers:
  - write a skill
  - create a skill
  - new skill
  - skill template
  - audit skill
  - skill not triggering
  - refactor skill
---

# Writing a Skill

## The Newspaper Rule (inverted pyramid)

```
HEADLINE  → frontmatter: name, description, triggers
LEAD      → the ONE most critical rule or quick-start (first section)
BODY      → examples, patterns, soft rules, gotchas (middle sections)
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
Defaults        pick ONE approach — mention the fallback only if the first fails
Method          teach HOW to approach the class of problem, not the answer to one instance
Calibration     fragile / irreversible ops  → prescriptive (exact command, no variation)
                flexible / multi-path ops   → explain the WHY; agent decides HOW
```

## Description Quality (most critical field)

The description is the only thing the agent reads when deciding to activate the skill.
If it's wrong, the skill never loads — or loads when it shouldn't.

```
DO    imperative framing:    "Use when X, Y, Z" — not "This skill does X"
DO    indirect triggers:     "even if the user doesn't say 'skill' or 'template'"
DO    near-miss exclusions:  "not for rule files — those use nextjs.md / typescript.md"
DO    err pushy:             list every context where this skill applies
DON'T describe implementation — describe user intent and trigger conditions
```

Bad:  `How to write a new skill that obeys the Techne system.`
Good: `Use when creating, auditing, or refactoring any skill. Also use when a skill
       isn't triggering, feels too long, or is missing the critical rule.`

## What Goes Where

```
ENTRY CARD (skills/<name>.md)
  The what + the most critical rule + concrete quick-start
  Routes to sub-skills for depth

SUB-SKILLS (skills/<name>/<topic>.md)
  One focused topic per file
  Name the trigger condition explicitly in the Next Steps pointer that loads it:
  "Struggling to X? → skills/<name>/<topic>.md"

GOTCHAS (required slot in every body)
  Concrete corrections to mistakes the agent makes without being told
  Not general advice — specific facts that defy reasonable assumptions
  Example: "CONTEXT.md is a glossary only — no file paths, no code snippets"
  Add one every time a retro or correction reveals a recurring mistake

RULE FILES (nextjs.md, typescript.md)
  Hard gates at the top   (weight: high | gate: yes)
  Soft rules below        (weight: medium | gate: no)
  Quick patterns with working code
```

## Ecosystem Integration (required before publishing)

```
[ ] skill-router.yaml entry (id, condition, skill_path, weight)
[ ] CONTEXT.md — does this skill write to it? (grill, persona-brainstorm do)
[ ] docs/adr/ — does this skill create ADRs? (grill, persona-brainstorm do)
[ ] SESSION.md — is this skill session-aware? (mention in output checklist)
[ ] harness/gates.py — does this skill have enforceable rules? (add gate)
[ ] tests/test_<name>.py — required before merging
[ ] Run the task WITH and WITHOUT the skill loaded — confirm it improves output
    or reduces wasted steps. No improvement = the skill is adding tokens, not value.
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
- Testing whether the skill actually helps? → `skills/evaluation.md`
