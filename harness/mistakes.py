"""
mistakes.py — structured mistake tracking with relevance matching.

Adopted from jtoemion/harness-engineering-skills/runtime/mistakes.py.
Upgrades the flat append-only log to structured entries with
ACTIVE/RESOLVED status and keyword-based relevance surfacing.
"""

import re
from datetime import datetime, timezone
from pathlib import Path

HARNESS_DIR = Path(__file__).parent
ROOT = HARNESS_DIR.parent
MISTAKES_FILE = ROOT / "memory" / "mistakes.md"
INSERT_MARKER = "<!-- New entries go below this line -->"

ENTRY_TEMPLATE = """## [{date}] {phase} | {source}
**Error**     : {error}
**Cause**     : {cause}
**Lesson**    : {lesson}
**Gate**      : {gate}
**Status**    : ACTIVE
"""


def log_mistake(
    phase: str,
    error: str,
    cause: str = "pending analysis",
    lesson: str = "pending retro",
    gate: str = "none",
    source: str = "AUTO-LOGGED",
) -> None:
    """Add structured entry to MISTAKES.md below insert marker."""
    if not MISTAKES_FILE.exists():
        raise FileNotFoundError(f"MISTAKES.md not found at {MISTAKES_FILE}")

    content = MISTAKES_FILE.read_text(encoding="utf-8")
    date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    new_entry = ENTRY_TEMPLATE.format(
        date=date,
        phase=phase,
        source=source,
        error=error,
        cause=cause,
        lesson=lesson,
        gate=gate,
    )

    if INSERT_MARKER not in content:
        raise ValueError(f"Insert marker not found in MISTAKES.md")

    new_content = content.replace(INSERT_MARKER, f"{INSERT_MARKER}\n{new_entry}")
    MISTAKES_FILE.write_text(new_content, encoding="utf-8")


def _parse_entries(content: str) -> list[dict]:
    """Parse all structured mistake entries."""
    entries = []
    pattern = re.compile(
        r"^\s*## \[([^\]]+)\] ([^\|]+)\| ([^\n]+)\n"
        r"^\s*\*\*Error\*\*\s*: ([^\n]+)\n"
        r"^\s*\*\*Cause\*\*\s*: ([^\n]+)\n"
        r"^\s*\*\*Lesson\*\*\s*: ([^\n]+)\n"
        r"^\s*\*\*Gate\*\*\s*: ([^\n]+)\n"
        r"^\s*\*\*Status\*\*\s*: ([^\n]+)",
        re.MULTILINE,
    )
    for m in pattern.finditer(content):
        entries.append({
            "date": m.group(1).strip(),
            "phase": m.group(2).strip(),
            "source": m.group(3).strip(),
            "error": m.group(4).strip(),
            "cause": m.group(5).strip(),
            "lesson": m.group(6).strip(),
            "gate": m.group(7).strip(),
            "status": m.group(8).strip(),
        })
    return entries


def check_relevant(task_input: str) -> list[dict]:
    """Return ACTIVE entries whose fields contain keywords from task_input."""
    if not MISTAKES_FILE.exists():
        return []

    content = MISTAKES_FILE.read_text(encoding="utf-8")
    entries = _parse_entries(content)

    keywords = [w.lower() for w in re.split(r"\W+", task_input) if len(w) > 2]
    relevant = []

    for entry in entries:
        if entry["status"] != "ACTIVE":
            continue
        searchable = f"{entry['error']} {entry['cause']} {entry['lesson']} {entry['gate']}".lower()
        for kw in keywords:
            if kw in searchable:
                relevant.append(entry)
                break

    return relevant


def mark_resolved(date_str: str) -> bool:
    """Change ACTIVE to RESOLVED for entry matching date_str."""
    if not MISTAKES_FILE.exists():
        return False

    content = MISTAKES_FILE.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"(^\s*## \[{re.escape(date_str)}\] [^\n]+\n(?:[^\n]+\n){{4}}^\s*\*\*Status\*\*\s*: )ACTIVE",
        re.MULTILINE,
    )
    if not pattern.search(content):
        return False

    new_content = pattern.sub(r"\1RESOLVED", content)
    MISTAKES_FILE.write_text(new_content, encoding="utf-8")
    return True


def count_active() -> int:
    """Count ACTIVE mistake entries."""
    if not MISTAKES_FILE.exists():
        return 0
    content = MISTAKES_FILE.read_text(encoding="utf-8")
    return len([e for e in _parse_entries(content) if e["status"] == "ACTIVE"])
