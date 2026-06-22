import tomllib
from pathlib import Path
import sys

root = Path(__file__).resolve().parent.parent
cmd_dir = root / "commands"
if not cmd_dir.exists():
    print("No commands/ directory found — skipping validation")
    sys.exit(0)

errors = []
for f in sorted(cmd_dir.glob("*.toml")):
    data = tomllib.loads(f.read_text())
    if not data.get("description", "").strip():
        errors.append(f"{f.name}: missing or empty 'description'")
    if not data.get("prompt", "").strip():
        errors.append(f"{f.name}: missing or empty 'prompt'")
    has_arg = "{{args}}" in data.get("prompt", "")
    has_arg_desc = "{{args}}" in data.get("description", "")
    if has_arg_desc and not has_arg:
        errors.append(f"{f.name}: description mentions {{args}} but prompt has no {{args}} placeholder")

if errors:
    for e in errors:
        print(f"ERROR: {e}")
    sys.exit(1)
else:
    print(f"Validated {len(list(cmd_dir.glob('*.toml')))} command file(s) — all OK")
