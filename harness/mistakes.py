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
MISTAKES_FILE = ROOT / ".techne" / "memory" / "mistakes.md"
INSERT_MARKER = "<!-- New entries go below this line -->"

ENTRY_TEMPLATE = """## [{date}] {phase} | {source}
**Error**     : {error}
**Cause**     : {cause}
**Lesson**    : {lesson}
**Gate**      : {gate}
**Skill**     : {skill}
**Status**    : ACTIVE
"""


def log_mistake(
    phase: str,
    error: str,
    cause: str = "pending analysis",
    lesson: str = "pending retro",
    gate: str = "none",
    skill: str = "none",
    source: str = "AUTO-LOGGED",
) -> None:
    """Add structured entry to MISTAKES.md below insert marker.

    `skill` attributes the failure to the skill that was routed for the run,
    so retro can count recurrence per skill (the keystone of self-improvement).
    """
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
        skill=skill,
    )

    if INSERT_MARKER not in content:
        raise ValueError(f"Insert marker not found in MISTAKES.md")

    new_content = content.replace(INSERT_MARKER, f"{INSERT_MARKER}\n{new_entry}")
    MISTAKES_FILE.write_text(new_content, encoding="utf-8")


def _parse_entries(content: str) -> list[dict]:
    """Parse all structured mistake entries."""
    entries = []
    # Skill is optional so entries written before skill-attribution still parse.
    pattern = re.compile(
        r"^\s*## \[(?P<date>[^\]]+)\] (?P<phase>[^\|]+)\| (?P<source>[^\n]+)\n"
        r"^\s*\*\*Error\*\*\s*: (?P<error>[^\n]+)\n"
        r"^\s*\*\*Cause\*\*\s*: (?P<cause>[^\n]+)\n"
        r"^\s*\*\*Lesson\*\*\s*: (?P<lesson>[^\n]+)\n"
        r"^\s*\*\*Gate\*\*\s*: (?P<gate>[^\n]+)\n"
        r"(?:^\s*\*\*Skill\*\*\s*: (?P<skill>[^\n]+)\n)?"
        r"^\s*\*\*Status\*\*\s*: (?P<status>[^\n]+)",
        re.MULTILINE,
    )
    for m in pattern.finditer(content):
        entries.append({
            "date": m.group("date").strip(),
            "phase": m.group("phase").strip(),
            "source": m.group("source").strip(),
            "error": m.group("error").strip(),
            "cause": m.group("cause").strip(),
            "lesson": m.group("lesson").strip(),
            "gate": m.group("gate").strip(),
            "skill": (m.group("skill") or "none").strip(),
            "status": m.group("status").strip(),
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
        searchable = f"{entry['error']} {entry['cause']} {entry['lesson']} {entry['gate']} {entry['skill']}".lower()
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
    # 4 fields pre-skill, 5 with skill — tolerate both old and new entries.
    pattern = re.compile(
        rf"(^\s*## \[{re.escape(date_str)}\] [^\n]+\n(?:[^\n]+\n){{4,6}}^\s*\*\*Status\*\*\s*: )ACTIVE",
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


def count_by_skill() -> dict[str, int]:
    """ACTIVE mistakes grouped by the skill in play — per-skill recurrence.

    The keystone for self-improvement: a skill earns a proposed edit when its
    own failures recur. retro reads this to attribute recurrence to a skill.
    """
    if not MISTAKES_FILE.exists():
        return {}
    content = MISTAKES_FILE.read_text(encoding="utf-8")
    counts: dict[str, int] = {}
    for e in _parse_entries(content):
        if e["status"] != "ACTIVE":
            continue
        if e["skill"] == "none":
            continue   # no routed skill → no skill to improve (don't propose skills/none.md)
        counts[e["skill"]] = counts.get(e["skill"], 0) + 1
    return counts
