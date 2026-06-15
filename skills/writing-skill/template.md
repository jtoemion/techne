---
name: writing-skill/template
description: Copy-paste scaffold for a new Techne skill. Fill in the blanks, delete what doesn't apply, stay under the line limits.
---

# Skill Template

## Entry Card — `skills/<name>.md`

```markdown
---
name: <name>
description: <one sentence: what it does + when to use it>
triggers:
  - <phrase that triggers this skill>
  - <another trigger phrase>
---

# <Skill Title>

## <Lead — most critical rule or quick-start>

```
<code block or compact table — the thing a reader needs immediately>
```

## <Section 2 — examples or patterns>

```
<concrete code or steps>
```

## <Section 3 — soft rules or edge cases>

```
<rules that don't have gates, but retro will flag>
```

## Next Steps

- <next situation> → `skills/<related>.md`
- <next situation> → `skills/<related>/<sub>.md`
- <done with this?> → back to `skills/<parent>.md`
```

## Sub-Skill — `skills/<name>/<topic>.md`

```markdown
---
name: <name>/<topic>
description: <focused single topic. Load when X situation arises.>
---

# <Topic>

## <Lead — the critical thing for this specific topic>

```
<code or rules>
```

## <Pattern or example>

```
<concrete>
```

## Common Mistakes

```
<what goes wrong and why>
```

## Next Steps

- <resolved?> → back to `skills/<name>.md`
- <need more depth?> → `skills/<name>/<other-topic>.md`
```

## Rule File — `skills/<name>.md` with gates

```markdown
---
name: <name>
description: <X> rules. Hard gates reject diffs that violate these. Loaded automatically.
---

# <Name> Rules

## Hard Gates (diff rejected on violation)

```
# weight: high | gate: yes
<rule>  → <short description>
<rule>  → <short description>
```

## Soft Rules (no gate)

```
# weight: medium
<rule>  → <short description>
```

## Quick Patterns

```typescript
// <pattern name> — working code, not pseudocode
<code>
```

## Discipline Skill — `skills/<name>.md` (rule the model resists)

```markdown
---
name: <name>
description: Use when <symptom of being ABOUT to violate>. WHEN-to-use only — no workflow summary.
---

# <Name>

<One line: the rule, and that violating the letter violates the spirit.>

## Rationalization Table (built from a watched RED baseline)

| Excuse | Reality |
|--------|---------|
| "<verbatim excuse from baseline>" | <the reality that defeats it> |

## Red Flags — STOP
- "<self-deception phrase>"
- → all of these mean: stop, comply, do not route around it.
```

Harden it per `skills/writing-skill/discipline.md` before shipping.

## Next Steps

- Gate firing? → <what to check>
- Related type errors? → `skills/<related>.md`
```

## Router Entry — `harness/skill-router.yaml`

```yaml
- id: "<name>"
  condition: "<keyword>, <keyword>, <trigger phrase>"
  skill_path: "skills/<name>.md"
  weight: <number>   # 90=diagnose, 85=persona-brainstorm, 80=grill, 50=nextjs/ts, 30=implementer
  note: "<optional: why this weight, any collision risk>"
```

## Test File — `tests/test_<name>.py`

```python
# Copy test_persona_brainstorm.py. Structural: file_structure, router, next_steps, compact
```

## Triggering Eval Set — `evals/<name>-trigger.json`

```json
[
  { "query": "realistic should-fire prompt, concrete + messy", "should_trigger": "<name>" },
  { "query": "near-miss: shares keywords, needs a SIBLING skill", "should_trigger": "<sibling>" },
  { "query": "near-miss that should stay silent", "should_trigger": false }
]
```

One near-miss per sibling skill. The negatives are the test, not the positives.

## Next Steps

- Discipline skill — harden it? → `skills/writing-skill/discipline.md`
- Technique skill — does it work? → `skills/writing-skill/evaluation.md`
- Ready for structural + wiring review? → `skills/writing-skill/checklist.md`
- Need the founding / type knob? → `skills/writing-skill.md`
