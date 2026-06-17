"""
reward.py — positive-signal ledger: the reinforcement counterpart to mistakes.py.

mistakes.py records FAILURES the gates caught, per skill. reward.py records WINS per
skill so the retro sees the NET — not just the numerator (failures) with no denominator.

  CLEAN  — a phase passed every gate on the FIRST try (full reward). The ideal: the
           gate never had to fire. Weighted highest ON PURPOSE so the incentive favors
           not erring. Rewarding a bare "capture" would pay the agent to introduce bugs.
  SOLVED — a gate caught an error that was then fixed + re-verified within the run
           (partial reward). Recovery is good, but worth less than never erring.

GUARDRAIL (Techne's hard-won rule): this is SIGNAL, not a steering wheel. It informs
the HUMAN-GATED retro (promote a skill's repeated CLEANs to a DISCIPLINE; temper
over-correcting a skill whose failures are outweighed by wins). It NEVER auto-edits a
skill, changes routing, or feeds the eval score — that would Goodhart the metric.
Mirrors mistakes.py / ledger.py shape on purpose.
"""

import re
from datetime import datetime, timezone
from pathlib import Path

HARNESS_DIR = Path(__file__).parent
ROOT = HARNESS_DIR.parent
REWARD_FILE = ROOT / "memory" / "reward.md"
INSERT_MARKER = "<!-- New entries go below this line -->"

# Net-quality weights: not erring (CLEAN) beats recovering (SOLVED). Signal, not money.
#
# INTENTIONAL: a recovered run logs BOTH a mistake (at the failure, via mistakes.py) AND
# a SOLVED win here. That is by design — the net ordering is what we want:
#   clean run        = +3            (no gate fired)
#   recovered run    = +1 -1 = net 0 (erred, but fixed it)
#   escaped failure  =    -1         (mistakes.py only)
# The mistake deliberately stays ACTIVE after an in-run recovery so the retro still sees
# the recurrence pattern — recovery doesn't mean the skill stopped making the mistake.
POINTS = {"CLEAN": 3, "SOLVED": 1}
KINDS = tuple(POINTS)

ENTRY_TEMPLATE = """## [{date}] {kind} | {source}
**Win**    : {what}
**Skill**  : {skill}
**Gate**   : {gate}
**Points** : {points}
"""


def log_reward(kind: str, what: str, skill: str = "none",
               gate: str = "none", source: str = "AUTO-LOGGED") -> None:
    """Append a structured win below the insert marker. `skill` attributes the win
    to the routed skill, mirroring mistakes.log_mistake, so retro sees per-skill net.

    Single-writer ledger (like mistakes.py / ledger.py): written by the ONE
    host/conductor. Isolated parallel workers do NOT write it directly — they report
    back and the host records (skills/kanban/isolation.md), so concurrent writers
    don't arise here and no lockfile is needed."""
    kind = kind.upper()
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    if not REWARD_FILE.exists():
        # Defensive init: a missing ledger (clean checkout / fresh dir) must not crash
        # the pipeline — start an empty one with the marker.
        REWARD_FILE.parent.mkdir(parents=True, exist_ok=True)
        REWARD_FILE.write_text(
            f"# REWARD — Positive Signal (wins per skill)\n\n{INSERT_MARKER}\n",
            encoding="utf-8",
        )
    content = REWARD_FILE.read_text(encoding="utf-8")
    if INSERT_MARKER not in content:
        raise ValueError("Insert marker not found in reward.md")
    date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = ENTRY_TEMPLATE.format(
        date=date, kind=kind, source=source, what=what,
        skill=skill, gate=gate, points=POINTS[kind],
    )
    # count=1: idempotent even if the marker were accidentally duplicated.
    REWARD_FILE.write_text(content.replace(INSERT_MARKER, f"{INSERT_MARKER}\n{entry}", 1),
                           encoding="utf-8")


def log_clean(what: str, skill: str = "none", gate: str = "none", source: str = "AUTO-LOGGED") -> None:
    log_reward("CLEAN", what, skill, gate, source)


def log_solved(what: str, skill: str = "none", gate: str = "none", source: str = "AUTO-LOGGED") -> None:
    log_reward("SOLVED", what, skill, gate, source)


def _parse_entries(content: str) -> list[dict]:
    pattern = re.compile(
        r"^\s*## \[(?P<date>[^\]]+)\] (?P<kind>[A-Z]+) \| (?P<source>[^\r\n]+)\r?\n"
        r"^\s*\*\*Win\*\*\s*: (?P<what>[^\r\n]+)\r?\n"
        r"^\s*\*\*Skill\*\*\s*: (?P<skill>[^\r\n]+)\r?\n"
        r"^\s*\*\*Gate\*\*\s*: (?P<gate>[^\r\n]+)\r?\n"
        r"^\s*\*\*Points\*\*\s*: (?P<points>[0-9]+)",
        re.MULTILINE,
    )
    out = []
    for m in pattern.finditer(content):
        out.append({
            "date": m.group("date").strip(), "kind": m.group("kind").strip(),
            "source": m.group("source").strip(), "what": m.group("what").strip(),
            "skill": m.group("skill").strip(), "gate": m.group("gate").strip(),
            "points": int(m.group("points")),
        })
    return out


def _entries() -> list[dict]:
    if not REWARD_FILE.exists():
        return []
    return _parse_entries(REWARD_FILE.read_text(encoding="utf-8"))


def count_by_skill() -> dict[str, int]:
    """Win COUNT per skill (skill 'none' excluded — no skill to credit)."""
    counts: dict[str, int] = {}
    for e in _entries():
        if e["skill"] == "none":
            continue
        counts[e["skill"]] = counts.get(e["skill"], 0) + 1
    return counts


def points_by_skill() -> dict[str, int]:
    """Weighted reward points per skill (CLEAN=3, SOLVED=1)."""
    pts: dict[str, int] = {}
    for e in _entries():
        if e["skill"] == "none":
            continue
        pts[e["skill"]] = pts.get(e["skill"], 0) + e["points"]
    return pts


def total_points() -> int:
    return sum(e["points"] for e in _entries())


def net_by_skill(mistake_counts: dict[str, int]) -> dict[str, dict]:
    """The denominator the retro was missing: per skill, wins vs failures vs net.

    Pass mistakes.count_by_skill() in (kept as an arg to avoid an import cycle).
    `net` < 0 means failures dominate — a real signal to improve that skill. `net`
    high-positive means the skill is mostly working; don't over-correct on a stray fail.
    """
    wins = count_by_skill()
    skills = set(wins) | set(mistake_counts)
    return {
        s: {"wins": wins.get(s, 0), "losses": mistake_counts.get(s, 0),
            "net": wins.get(s, 0) - mistake_counts.get(s, 0)}
        for s in skills
    }


def check_relevant(task_input: str) -> list[dict]:
    """ACTIVE-equivalent: wins are permanent; surface those sharing task keywords."""
    keywords = [w.lower() for w in re.split(r"\W+", task_input) if len(w) > 2]
    out = []
    for e in _entries():
        searchable = f"{e['what']} {e['skill']} {e['gate']} {e['kind']}".lower()
        if any(kw in searchable for kw in keywords):
            out.append(e)
    return out


def validate() -> list[str]:
    """Cheap drift guard (mirrors ledger.validate): header count vs parsed count, and
    unknown kinds. Never raises; returns a list of problems ([] = clean)."""
    if not REWARD_FILE.exists():
        return []
    content = REWARD_FILE.read_text(encoding="utf-8")
    if INSERT_MARKER in content:
        content = content.split(INSERT_MARKER, 1)[1]
    headers = re.findall(r"(?m)^\s*## \[[^\]]+\][^\n]*$", content)
    parsed = _parse_entries(content)
    problems = []
    if len(headers) > len(parsed):
        problems.append(f"{len(headers)} header(s) but {len(parsed)} parsed — "
                        f"{len(headers) - len(parsed)} malformed (check field order/names)")
    for h in headers:
        m = re.match(r"^\s*## \[[^\]]+\]\s+(\w+)\s*\|", h)
        if m and m.group(1).upper() not in KINDS:
            problems.append(f"unknown kind: {h.strip()[:60]}")
    return problems
