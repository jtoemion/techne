#!/usr/bin/env python3
"""template_scaffolder.py — Generate new skill folder + SKILL.md from template.

Usage:
    python3 scripts/template_scaffolder.py <name> --type discipline [--description "Use when ..."]
    python3 scripts/template_scaffolder.py <name> --type technique
    python3 scripts/template_scaffolder.py <name> --type capability
    python3 scripts/template_scaffolder.py <name> --with-script  # also scaffold a script
"""

from __future__ import annotations
import argparse, os, sys, textwrap
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILLS_DIR = ROOT / "skills"
TYPES = ("discipline", "technique", "capability")

DISCIPLINE_TEMPLATE = """\
---
name: {name}
description: {description}
triggers:
  - "{trigger}"
  - "{trigger2}"
---

# {Title}

<One line: the rule, and that violating the letter violates the spirit.>

## <Lead — most critical rule>

```
<paste this after filling>
```

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "<excuse>" | "<reality>" |

## Red Flags — STOP

- "<self-deception phrase>"

## Next Steps

- <next> → back to `.hermes/skills/techne-skills/skill-router.yaml`
"""

TECHNIQUE_TEMPLATE = """\
---
name: {name}
description: {description}
triggers:
  - "{trigger}"
---

# {Title}

## <Lead — quick-start or reference>

```
<paste>
```

## <Examples>

```
<paste>
```

## Common Mistakes

```
<paste>
```

## Next Steps

- <next> → back to `.hermes/skills/techne-skills/skill-router.yaml`
"""

SCRIPT_TEMPLATE = """\
#!/usr/bin/env python3
\"\"\"{name}.py — <one-line description>

Usage:
    python3 scripts/{name}.py <args>
\"\"\"

from __future__ import annotations
import argparse, sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

def main():
    parser = argparse.ArgumentParser(description="<description>")
    parser.add_argument("--dry-run", action="store_true", help="Preview without changes")
    args = parser.parse_args()
    print(f"=== {name} ===")

if __name__ == "__main__":
    main()
"""

def scaffold(name: str, skill_type: str, description: str, with_script: bool):
    folder = SKILLS_DIR / name
    if folder.exists():
        print(f"Skill folder already exists: {folder}")
        return

    folder.mkdir(parents=True)
    title = name.replace("-", " ").title()

    if skill_type == "discipline":
        triggers = [name, f"{name} tool"]
        template = DISCIPLINE_TEMPLATE
    elif skill_type == "technique":
        triggers = [name]
        template = TECHNIQUE_TEMPLATE
    else:
        triggers = [name]
        template = TECHNIQUE_TEMPLATE  # capability skills are vendored, not scaffolded

    skill_content = template.format(
        name=name,
        description=description or f"Use when <symptom>",
        Title=title,
        trigger=triggers[0],
        trigger2=triggers[1] if len(triggers) > 1 else triggers[0],
    )

    skill_path = folder / "SKILL.md"
    skill_path.write_text(skill_content.lstrip("\n"))
    print(f"  ✅ skills/{name}/SKILL.md")

    if with_script:
        scripts_dir = ROOT / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        script_path = scripts_dir / f"{name}.py"
        if not script_path.exists():
            script_content = SCRIPT_TEMPLATE.format(name=name)
            script_path.write_text(script_content.lstrip("\n"))
            os.chmod(script_path, 0o755)
            print(f"  ✅ scripts/{name}.py")
        else:
            print(f"  — scripts/{name}.py already exists")

    print(f"\nCreated {name} ({skill_type})")
    print(f"Next: add router entry to .hermes/skills/techne-skills/skill-router.yaml")

def main():
    parser = argparse.ArgumentParser(description="Scaffold a new skill from template")
    parser.add_argument("name", help="Skill name (lowercase, hyphens)")
    parser.add_argument("--type", choices=TYPES, default="discipline", help="Skill type")
    parser.add_argument("--description", default="", help="One-line description")
    parser.add_argument("--with-script", action="store_true", help="Also scaffold a script")
    args = parser.parse_args()
    scaffold(args.name, args.type, args.description, args.with_script)
    sys.exit(0)

if __name__ == "__main__":
    main()
