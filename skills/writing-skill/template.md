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

[Optional: one-sentence context if truly necessary]

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

---

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

---

## Rule File — `skills/<name>.md` with gates

```markdown
---
name: <name>
description: <X> rules. Hard gates reject diffs that violate these.
             Loaded automatically for every task.
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
// <pattern name>
<code>
```

## Next Steps

- Gate firing? → <what to check>
- Related type errors? → `skills/<related>.md`
```

---

## Router Entry — `harness/skill-router.yaml`

```yaml
- id: "<name>"
  condition: "<keyword>, <keyword>, <trigger phrase>"
  skill_path: "skills/<name>.md"
  weight: <number>   # 90=diagnose, 85=persona-brainstorm, 80=grill, 50=nextjs/ts, 30=implementer
  note: "<optional: why this weight, any collision risk>"
```

---

## Test File — `tests/test_<name>.py`

```python
# tests/test_<name>.py — copy tests/test_persona_brainstorm.py as base
# Minimum: test_file_structure, test_router, test_next_steps, test_compact
# See any existing test file in tests/ for the full pattern
```

## Next Steps

- Template filled in, ready to validate? → `skills/writing-skill/checklist.md`
- Need to add a gate for a hard rule? → `harness/gates.py` (follow existing pattern)
- Need newspaper logic explained? → `skills/writing-skill.md`
