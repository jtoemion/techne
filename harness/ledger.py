"""
ledger.py — durable decision / lesson / discipline ledger.

The positive, reasoning-side counterpart to mistakes.py. Where mistakes.md
records FAILURES (what the gates caught), the ledger records the method layer:

  DECISION   — a choice made about HOW to work, and why (alternatives rejected)
  LESSON     — something learned about the process, with evidence
  DISCIPLINE — a method that worked and should be repeated

Distinct from docs/adr/ (which captures CODE-architecture decisions). The ledger
is about how the WORK was done, so the agent's methods refine — not just the
skill files. Surfaced before every task (check_relevant), exactly like mistakes,
so past method-lessons inform new work instead of being re-derived each session.

Mirrors the mistakes.py shape (marker-based append, ACTIVE/ARCHIVED status,
keyword relevance) on purpose — same proven discipline, opposite sign.
"""

import re
from datetime import datetime, timezone
from pathlib import Path

HARNESS_DIR = Path(__file__).parent
ROOT = HARNESS_DIR.parent
LEDGER_FILE = ROOT / ".techne" / "memory" / "ledger.md"
INSERT_MARKER = "<!-- New entries go below this line -->"
KINDS = ("DECISION", "LESSON", "DISCIPLINE")

ENTRY_TEMPLATE = """## [{date}] {kind} | {source}
**What**   : {what}
**Why**    : {why}
**Skill**  : {skill}
**Status** : ACTIVE
"""


def log_entry(kind: str, what: str, why: str = "", skill: str = "none",
              source: str = "retro") -> None:
    """Append a structured ledger entry below the insert marker."""
    kind = kind.upper()
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    if not LEDGER_FILE.exists():
        raise FileNotFoundError(f"ledger.md not found at {LEDGER_FILE}")

    content = LEDGER_FILE.read_text(encoding="utf-8")
    if INSERT_MARKER not in content:
        raise ValueError("Insert marker not found in ledger.md")

    date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_entry = ENTRY_TEMPLATE.format(
        date=date, kind=kind, source=source, what=what,
        why=why or "—", skill=skill,
    )
    new_content = content.replace(INSERT_MARKER, f"{INSERT_MARKER}\n{new_entry}")
    LEDGER_FILE.write_text(new_content, encoding="utf-8")


def log_decision(what: str, why: str = "", skill: str = "none", source: str = "retro") -> None:
    log_entry("DECISION", what, why, skill, source)


def log_lesson(what: str, why: str = "", skill: str = "none", source: str = "retro") -> None:
    log_entry("LESSON", what, why, skill, source)


def log_discipline(what: str, why: str = "", skill: str = "none", source: str = "retro") -> None:
    log_entry("DISCIPLINE", what, why, skill, source)


def _parse_entries(content: str) -> list[dict]:
    """Parse all structured ledger entries."""
    entries = []
    pattern = re.compile(
        r"^\s*## \[(?P<date>[^\]]+)\] (?P<kind>[A-Z]+) \| (?P<source>[^\n]+)\n"
        r"^\s*\*\*What\*\*\s*: (?P<what>[^\n]+)\n"
        r"^\s*\*\*Why\*\*\s*: (?P<why>[^\n]+)\n"
        r"(?:^\s*\*\*Skill\*\*\s*: (?P<skill>[^\n]+)\n)?"
        r"^\s*\*\*Status\*\*\s*: (?P<status>[^\n]+)",
        re.MULTILINE,
    )
    for m in pattern.finditer(content):
        entries.append({
            "date": m.group("date").strip(),
            "kind": m.group("kind").strip(),
            "source": m.group("source").strip(),
            "what": m.group("what").strip(),
            "why": m.group("why").strip(),
            "skill": (m.group("skill") or "none").strip(),
            "status": m.group("status").strip(),
        })
    return entries


def check_relevant(task_input: str) -> list[dict]:
    """Return ACTIVE entries whose fields share keywords with the task."""
    if not LEDGER_FILE.exists():
        return []
    entries = _parse_entries(LEDGER_FILE.read_text(encoding="utf-8"))
    keywords = [w.lower() for w in re.split(r"\W+", task_input) if len(w) > 2]
    relevant = []
    for e in entries:
        if e["status"] != "ACTIVE":
            continue
        searchable = f"{e['what']} {e['why']} {e['skill']} {e['kind']}".lower()
        if any(kw in searchable for kw in keywords):
            relevant.append(e)
    return relevant


def count_active() -> int:
    if not LEDGER_FILE.exists():
        return 0
    return len([e for e in _parse_entries(LEDGER_FILE.read_text(encoding="utf-8"))
                if e["status"] == "ACTIVE"])


def count_by_kind() -> dict[str, int]:
    """ACTIVE entries grouped by kind (DECISION / LESSON / DISCIPLINE)."""
    if not LEDGER_FILE.exists():
        return {}
    counts: dict[str, int] = {}
    for e in _parse_entries(LEDGER_FILE.read_text(encoding="utf-8")):
        if e["status"] != "ACTIVE":
            continue
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    return counts


def validate() -> list[str]:
    """Cheap drift guard for the agent-written ledger. Returns a list of problems
    (empty = clean); never raises. Catches the failure mode of an entry that LOOKS
    like a ledger entry but didn't parse (bad field order/names, lowercase kind),
    so format drift is SEEN at pipeline start instead of silently under-surfaced.
    """
    if not LEDGER_FILE.exists():
        return []
    content = LEDGER_FILE.read_text(encoding="utf-8")
    if INSERT_MARKER in content:
        content = content.split(INSERT_MARKER, 1)[1]   # only entries, not the preamble

    headers = re.findall(r"(?m)^\s*## \[[^\]]+\][^\n]*$", content)
    parsed = _parse_entries(content)
    problems = []
    if len(headers) > len(parsed):
        problems.append(
            f"{len(headers)} entry header(s) but only {len(parsed)} parsed — "
            f"{len(headers) - len(parsed)} malformed (check field order/names)"
        )
    for h in headers:
        m = re.match(r"^\s*## \[[^\]]+\]\s+(\w+)\s*\|", h)
        if m and m.group(1).upper() not in KINDS:
            problems.append(f"unknown kind: {h.strip()[:60]}")
    return problems
