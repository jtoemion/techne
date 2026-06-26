"""Validate all command files in commands/."""
import tomllib
from pathlib import Path
import sys

root = Path(__file__).resolve().parent.parent
cmd_dir = root / "commands"
if not cmd_dir.exists():
    print("No commands/ directory found \u2014 skipping validation")
    sys.exit(0)

MANDATORY_KEYWORDS = ["pipeline", "phase"]

errors = []
for f in sorted(cmd_dir.glob("*.toml")):
    data = tomllib.loads(f.read_text())
    
    desc = data.get("description", "").strip()
    prompt = data.get("prompt", "").strip()
    
    # Basic format checks
    if not desc:
        errors.append(f"{f.name}: missing or empty 'description'")
    if not prompt:
        errors.append(f"{f.name}: missing or empty 'prompt'")
    
    # Content quality checks
    for kw in MANDATORY_KEYWORDS:
        if kw not in prompt.lower():
            errors.append(f"{f.name}: prompt missing mandatory keyword '{kw}'")
    
    has_arg_in_prompt = "{{args}}" in prompt
    has_arg_in_desc = "{{args}}" in desc
    if has_arg_in_desc and not has_arg_in_prompt:
        errors.append(f"{f.name}: description mentions {{args}} but prompt has no {{args}} placeholder")
    
    # Check for at least one pipeline phase reference
    has_phase_ref = any(p.lower() in prompt.lower() for p in ["RECALL", "IMPLEMENT", "CONCLUDE", "DONE"])
    if not has_phase_ref and desc:
        errors.append(f"{f.name}: prompt should reference at least one pipeline phase")

if errors:
    for e in errors:
        print(f"ERROR: {e}")
    sys.exit(1)
else:
    count = len(list(cmd_dir.glob("*.toml")))
    print(f"Validated {count} command file(s) \u2014 all OK")
