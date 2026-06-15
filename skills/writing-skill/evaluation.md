---
name: writing-skill/evaluation
description: Prove a skill actually works before merging it. A skill is a hypothesis — run it with-skill vs without-skill, compare, iterate. Plus triggering evals: does the description fire when it should and stay silent when it shouldn't. Load after drafting a skill, before committing.
---

# Validating a Skill

This is the **technique/reference branch** — the model is a collaborator, not an
adversary. (Discipline/rule skills validate differently → `skills/writing-skill/discipline.md`.)

A structural test proves a skill is well-formed. It never proves it's good.
This is the loop that does. Two questions, measured separately:

```
DOES IT HELP?   → with-skill vs without-skill on real prompts
DOES IT FIRE?   → should-trigger vs should-not-trigger queries
```

Skip this and you're asserting the skill works. The whole founding is: don't assert, measure.
RED-first still applies — run the without-skill baseline first, so you see the gap before you fill it.

## Does It Help — the baseline comparison

The control is the point: a skill that doesn't beat no-skill is dead weight.

```
1. Write 2-3 realistic prompts — what a real user would actually type, not
   "test the skill". Concrete: file paths, names, messy casual phrasing.
2. Run each TWICE in the same turn (spawn both, don't stagger):
     with-skill     → subagent loads skills/<name>.md, does the task
     without-skill  → subagent, no skill, same prompt
3. Compare side by side. Read the TRANSCRIPTS, not just the outputs — if the
   skill made the model waste steps, cut the part that caused it.
4. The skill earns its place only if with-skill is clearly better.
```

Can't tell the two apart? The skill isn't pulling weight. Cut it or rethink the approach — don't pile on MUSTs to force a difference on these specific cases.

## Does It Fire — triggering evals

The description is the trigger. Techne also weights it in `skill-router.yaml`,
so a skill can fire two ways: description match or router weight. Test both.

```
~20 queries, ~half should-fire, ~half should-not.
The negatives carry the value: NEAR-MISSES, not gimmes.
  Good negative   → shares keywords but actually needs a different skill
  Useless negative → "write a fibonacci function" for a UI skill (proves nothing)
```

```json
[
  { "query": "review this locked checkout design before I prompt v0 to build it", "should_trigger": "ui-craft" },
  { "query": "is this dashboard layout actually right? feels off", "should_trigger": "ui-grill" },
  { "query": "rename these CSS variables", "should_trigger": false }
]
```

### The near-miss is the test

You found one already: ui-grill and ui-craft both matched "ui review", and the
router couldn't separate them. A near-miss eval catches that collision
mechanically. **For every new skill, write one near-miss against each SIBLING
skill it could be confused with.** If two skills fire on the same query, their
descriptions overlap — fix the descriptions, don't just bump a weight.

## Generalize, Don't Overfit

You iterate on 3 examples because it's fast and you know them cold. But the
skill runs on a million unseen prompts. When a fix only helps your 3 cases — a
fiddly special-case, one more NEVER — stop. Reach for a different metaphor or
framing instead. It's cheap to try and it's how you escape overfitting.

## When It's Done

```
[ ] with-skill beats without-skill on every test prompt
[ ] triggering evals pass — fires on should, silent on should-not
[ ] near-miss written against each sibling skill it could collide with
[ ] no fix that only works on the test cases (overfit check)
```

## Next Steps

- Passes empirically? → `skills/writing-skill/checklist.md` (structure + wiring)
- Actually a rule the model resists? → `skills/writing-skill/discipline.md` (wrong branch)
- Description firing wrong? → tighten it; name the sibling it's confused with
- Container/structure questions? → back to `skills/writing-skill.md`
