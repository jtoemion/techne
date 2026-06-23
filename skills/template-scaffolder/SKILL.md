---
name: template-scaffolder
description: Use when about to create a new skill — run this first to generate the folder, SKILL.md, and optional script from the writing-skill template. Do not create skill files manually.
triggers:
  - "scaffold skill"
  - "new skill"
  - "create skill"
  - "skill template"
---

# Template Scaffolder

Manually creating skill files produces inconsistencies — wrong frontmatter, missing triggers, no Rationalization Table. The scaffolder guarantees every new skill starts with the correct structure for its type.

## Lead — Quick Start

```
python3 scripts/template_scaffolder.py my-tool --type discipline --with-script
python3 scripts/template_scaffolder.py my-tool --type technique
python3 scripts/template_scaffolder.py my-tool --description "Use when X"
```

Creates `skills/{name}/SKILL.md` + optional `scripts/{name}.py`.

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "I'll just copy an existing skill and modify it" | You'll miss the Rationalization Table, Red Flags, or Next Steps — every time. |
| "The template is just formatting, I know the structure" | Every skill in this repo that started as a manual copy was later rewritten. |
| "I don't need a script with the skill" | Add `--with-script` even if the script starts empty. Adding it later is friction. |

## Red Flags — STOP

- "I'll just write it directly in the folder"
- "Let me copy diagnose and change the name"
- "I don't need a template"

## Next Steps

- Scaffolded? → open `skills/{name}/SKILL.md` and fill the body
- Need a script? → fill `scripts/{name}.py`
- Ready to wire? → add router entry in `skills/skill-router.yaml`
- Back to writing skills → `skills/writing-skill/SKILL.md`
