---
name: writing-skill
description: How to write a skill that obeys the Techne harness AND actually works. A skill is a hypothesis, proven by watching an agent fail without it first. Rigid container always; content and proof branch on skill type — discipline skills harden against rationalization, technique skills reason and measure. Use when creating, auditing, or refactoring any skill file.
triggers:
  - write a skill
  - create a skill
  - new skill
  - skill template
  - audit skill
---

# Writing a Skill

## The Founding (read before writing a line)

```
A skill is a HYPOTHESIS, proven by TDD-for-docs: watch an agent FAIL the baseline
first, then write the minimal skill that fixes exactly that failure. You don't know
a skill works until you've seen what the model does without it.

THREE LAYERS — not three opinions to average (they contradict; averaging = mush):
  CONTAINER (always on) → rigid structure + line caps + gates; the harness enforces it
  CONTENT  (by type)    → discipline hardens, technique reasons
  PROOF    (by type)    → discipline: comply under pressure; technique: beat the baseline
```

The lean: Techne is a discipline harness, so default to hardening. Relax to the
reasoned/collaborative stance only when the skill has no adversary.

## Pick the Type First (the knob that sets everything)

```
DISCIPLINE / RULE / GATE → a SMART model will rationalize past it under pressure
  (gates, TDD, verification, the line caps themselves)
  → skills/writing-skill/discipline.md — RED-first, rationalization table, red flags

TECHNIQUE / REFERENCE → the model is a willing collaborator, no adversary
  (syntax refs, UI helpers, how-tos)
  → skills/writing-skill/evaluation.md — with/without, explain the why, anti-overfit

CAPABILITY / BUNDLE → a TOOL not advice: SKILL.md + scripts/ + reference/, run as black box
  (webapp-testing, mcp-builder) — vendor VERBATIM, EXEMPT from line caps; glue lives outside
  → skills/SOURCES.md — provenance + re-sync; never edit the engine
```

Wrong type = wrong everything. Choose before writing the first section.

## The Newspaper Rule (the container's shape)

```
HEADLINE → frontmatter: name, description, triggers
LEAD     → the ONE most critical rule or quick-start (first section)
BODY     → examples, patterns, soft rules
TAIL     → ## Next Steps chain (always last)
```

Reader stops at any line → most important thing already seen. Depth → sub-skills.

## Structure Rules (the container's gates)

```
Entry card  ≤ 100 lines       Sub-skill ≤ 150 lines
Frontmatter required: name + description; optional: triggers (router)
Sections    short, code-heavy, no prose paragraphs
Next Steps  mandatory last section in every file
```

## Description by Type (CSO)

```
DISCIPLINE w/ mandatory workflow → describe WHEN to use ONLY. Never summarize the
  steps: a workflow summary becomes a shortcut the model follows INSTEAD of reading
  the skill (a documented 2-step review silently collapsed to 1).
TECHNIQUE / REFERENCE → what + when, keyword-rich, a little pushy to fight undertriggering.
```

## Ecosystem Integration (required before publishing)

```
[ ] skill-router.yaml entry (id, condition, skill_path, weight)
[ ] proof run — discipline.md (pressure) OR evaluation.md (with/without)
[ ] CONTEXT.md / docs/adr/ — does this skill write to them?
[ ] SESSION.md — is this skill session-aware?
[ ] harness/gates.py — enforceable rule? add the gate (a gate beats a MUST)
[ ] tests/test_<name>.py — structural tests, required before merging
```

## Next Steps

- Discipline / rule / gate skill? → `skills/writing-skill/discipline.md`
- Technique / reference skill? → `skills/writing-skill/evaluation.md`
- Ready to scaffold? → `skills/writing-skill/template.md`
- Review before commit? → `skills/writing-skill/checklist.md`
- Vendoring an external capability skill? → `skills/SOURCES.md` (keep it pristine)
