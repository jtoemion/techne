"""
wikilink.py — generate a wikilink registry (md + json) from mistakes + ledger.

The "wikilink" idea: lessons, disciplines, and recurring mistakes should be
*discoverable* — not just appended and forgotten. This module builds a
bidirectional index:

  - Every entry gets a stable slug
  - Every entry links to the skill it relates to
  - Every skill links back to the entries that mention it

Two artifacts:
  1. memory/wikilinks.md     — human-readable wiki index
  2. memory/wikilinks.json   — machine-readable graph for tools

Run periodically (after every retro_learn trigger fires, or on demand):
    python3 harness/wikilink.py              # build both
    python3 harness/wikilink.py --md-only    # just the wiki
    python3 harness/wikilink.py --json-only  # just the graph
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HARNESS_DIR = Path(__file__).parent
ROOT = HARNESS_DIR.parent
MISTAKES_FILE = ROOT / "memory" / "mistakes.md"
LEDGER_FILE = ROOT / "memory" / "ledger.md"
WIKILINK_MD = ROOT / "memory" / "wikilinks.md"
WIKILINK_JSON = ROOT / "memory" / "wikilinks.json"
WORKSHOP_DIR = ROOT / ".techne"
WORKSHOP_CONTEXT_INDEX = WORKSHOP_DIR / "generated" / "context_index.json"
WORKSHOP_WIKILINK_MD = WORKSHOP_DIR / "memory" / "wikilinks.md"
WORKSHOP_WIKILINK_JSON = WORKSHOP_DIR / "memory" / "wikilinks.json"


def _slug(text: str) -> str:
    """Stable slug from entry text — first 6 words, lowercased, hyphenated."""
    words = re.split(r"\W+", text.lower())
    words = [w for w in words if w][:6]
    return "-".join(words) or "entry"


# ── parsers (mirror mistakes.py / ledger.py — kept duplicated to avoid coupling) ──

def parse_mistakes() -> list[dict]:
    if not MISTAKES_FILE.exists():
        return []
    content = MISTAKES_FILE.read_text(encoding="utf-8")
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
    return [
        {
            "kind": "MISTAKE",
            "date": m.group("date").strip(),
            "phase": m.group("phase").strip(),
            "source": m.group("source").strip(),
            "what": m.group("error").strip(),
            "why": m.group("cause").strip(),
            "lesson": m.group("lesson").strip(),
            "gate": m.group("gate").strip(),
            "skill": (m.group("skill") or "none").strip(),
            "status": m.group("status").strip(),
        }
        for m in pattern.finditer(content)
    ]


def parse_ledger() -> list[dict]:
    if not LEDGER_FILE.exists():
        return []
    content = LEDGER_FILE.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^\s*## \[(?P<date>[^\]]+)\] (?P<kind>[A-Z]+) \| (?P<source>[^\n]+)\n"
        r"^\s*\*\*What\*\*\s*: (?P<what>[^\n]+)\n"
        r"^\s*\*\*Why\*\*\s*: (?P<why>[^\n]+)\n"
        r"(?:^\s*\*\*Skill\*\*\s*: (?P<skill>[^\n]+)\n)?"
        r"^\s*\*\*Status\*\*\s*: (?P<status>[^\n]+)",
        re.MULTILINE,
    )
    return [
        {
            "kind": m.group("kind").strip(),  # DECISION / LESSON / DISCIPLINE
            "date": m.group("date").strip(),
            "source": m.group("source").strip(),
            "what": m.group("what").strip(),
            "why": m.group("why").strip(),
            "skill": (m.group("skill") or "none").strip(),
            "status": m.group("status").strip(),
        }
        for m in pattern.finditer(content)
    ]


# ── graph builder ──

def build_graph() -> dict:
    """Build the full wikilink graph.

    Returns dict with:
      entries: list of all entries (mistakes + ledger), each with a slug
      skills:  map of skill_name -> list of entry slugs that mention it
      summary: counts by kind + status
    """
    mistakes = parse_mistakes()
    ledger = parse_ledger()
    all_entries = mistakes + ledger

    # Slug each entry — slug uniqueness via date prefix
    seen_slugs: set[str] = set()
    for e in all_entries:
        base = _slug(e.get("what") or e.get("error", ""))
        slug = f"{e['date'][:10]}-{base}"
        # If still collide, append a counter
        counter = 1
        candidate = slug
        while candidate in seen_slugs:
            counter += 1
            candidate = f"{slug}-{counter}"
        seen_slugs.add(candidate)
        e["slug"] = candidate
        e["anchor"] = candidate.replace("-", "")  # for markdown anchors

    # Build skill -> entries reverse index
    skill_to_entries: dict[str, list[str]] = defaultdict(list)
    for e in all_entries:
        skill_to_entries[e["skill"]].append(e["slug"])

    # Summary counts
    summary = {
        "total": len(all_entries),
        "by_kind": {
            "MISTAKE": sum(1 for e in all_entries if e["kind"] == "MISTAKE"),
            "DECISION": sum(1 for e in all_entries if e["kind"] == "DECISION"),
            "LESSON": sum(1 for e in all_entries if e["kind"] == "LESSON"),
            "DISCIPLINE": sum(1 for e in all_entries if e["kind"] == "DISCIPLINE"),
        },
        "by_status": {
            "ACTIVE": sum(1 for e in all_entries if e["status"] == "ACTIVE"),
            "RESOLVED": sum(1 for e in all_entries if e["status"] == "RESOLVED"),
        },
        "skills_referenced": len([s for s in skill_to_entries if s != "none"]),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    graph = {
        "entries": all_entries,
        "skills": dict(skill_to_entries),
        "summary": summary,
    }
    _attach_workshop_graph(graph)
    return graph


def _attach_workshop_graph(graph: dict) -> None:
    """Augment the legacy memory graph with project/workshop context nodes."""
    if not WORKSHOP_CONTEXT_INDEX.exists():
        return
    try:
        context_index = json.loads(WORKSHOP_CONTEXT_INDEX.read_text(encoding="utf-8"))
    except Exception:
        return

    project = {
        "name": context_index.get("project_name", ROOT.name),
        "repo_root": context_index.get("repo_root", str(ROOT.resolve())),
        "generated_at": graph["summary"].get("generated_at"),
        "version": 2,
    }
    nodes: list[dict] = [
        {
            "id": "project:root",
            "kind": "project",
            "title": project["name"],
            "path": ".",
            "tags": ["workshop", "root"],
            "metadata": {"repo_root": project["repo_root"]},
        }
    ]
    edges: list[dict] = []

    for subsystem in context_index.get("subsystems", []):
        subsystem_id = f"subsystem:{subsystem['name']}"
        nodes.append(
            {
                "id": subsystem_id,
                "kind": "subsystem",
                "title": subsystem["name"],
                "path": ", ".join(subsystem.get("paths", [])),
                "tags": subsystem.get("tags", []),
                "metadata": {
                    "context_doc": subsystem.get("context_doc"),
                    "refresh_policy": subsystem.get("refresh_policy"),
                    "file_count": subsystem.get("file_count", 0),
                },
            }
        )
        edges.append(
            {
                "from": "project:root",
                "type": "project_contains",
                "to": subsystem_id,
                "weight": 1.0,
                "source": "context_index",
            }
        )

    for context_doc in context_index.get("context_docs", []):
        doc_id = f"context:{context_doc['subsystem']}"
        nodes.append(
            {
                "id": doc_id,
                "kind": "context_doc",
                "title": context_doc["path"],
                "path": context_doc["path"],
                "tags": context_doc.get("tags", []),
                "metadata": {
                    "refresh_policy": context_doc.get("refresh_policy"),
                    "paths": context_doc.get("paths", []),
                },
            }
        )
        edges.append(
            {
                "from": doc_id,
                "type": "context_describes",
                "to": f"subsystem:{context_doc['subsystem']}",
                "weight": 1.0,
                "source": "context_index",
            }
        )

    for file_entry in context_index.get("files", []):
        subsystem = file_entry.get("subsystem")
        if not subsystem:
            continue
        file_id = f"file:{file_entry['path']}"
        nodes.append(
            {
                "id": file_id,
                "kind": "file",
                "title": file_entry["path"],
                "path": file_entry["path"],
                "tags": [],
                "metadata": {"ext": file_entry.get("ext", "")},
            }
        )
        edges.append(
            {
                "from": f"subsystem:{subsystem}",
                "type": "subsystem_contains",
                "to": file_id,
                "weight": 0.5,
                "source": "context_index",
            }
        )

    graph["project"] = project
    graph["nodes"] = nodes
    graph["edges"] = edges
    graph["summary"]["graph_nodes"] = len(nodes)
    graph["summary"]["graph_edges"] = len(edges)


# ── markdown formatter ──

def format_markdown(graph: dict) -> str:
    lines = [
        "# Wikilinks — Method Memory Index",
        "",
        f"_Generated: {graph['summary']['generated_at']}_  ",
        f"Total entries: **{graph['summary']['total']}**  ",
        f"Skills referenced: **{graph['summary']['skills_referenced']}**",
        "",
        "Each entry below links to the skill it relates to. Each skill at the bottom",
        "lists every entry that mentions it — click through to see the failure history",
        "and the methods that earned their place.",
        "",
    ]

    # By kind
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for e in graph["entries"]:
        by_kind[e["kind"]].append(e)

    for kind in ("MISTAKE", "DISCIPLINE", "LESSON", "DECISION"):
        if not by_kind[kind]:
            continue
        lines.append(f"## {kind}s")
        lines.append("")
        for e in by_kind[kind]:
            anchor = e["anchor"]
            skill = e.get("skill", "none")
            skill_link = f" → [[skills/{skill}]]" if skill not in ("none", "") else ""
            status = e["status"]
            status_badge = f" `[{status}]`" if status != "ACTIVE" else " `ACTIVE`"
            lines.append(f"### <a id=\"{anchor}\"></a>{e['what'][:80]}{status_badge}")
            lines.append(f"*{e['date']}* · `{e['slug']}` · skill: `{skill}`{skill_link}")
            if e["kind"] == "MISTAKE":
                lines.append(f"- **Cause**: {e.get('cause', '—')}")
                lines.append(f"- **Lesson**: {e.get('lesson', '—')}")
                lines.append(f"- **Gate**: {e.get('gate', '—')}")
            else:
                lines.append(f"- **Why**: {e.get('why', '—')}")
            lines.append("")

    # Reverse index: skill -> entries
    lines.append("## Skills → Entries (reverse index)")
    lines.append("")
    for skill in sorted(graph["skills"]):
        if skill == "none":
            continue
        lines.append(f"### `{skill}`")
        for slug in graph["skills"][skill]:
            entry = next((e for e in graph["entries"] if e["slug"] == slug), None)
            if entry:
                lines.append(f"- [{entry['what'][:70]}](#{entry['anchor']}) — `{entry['kind']}` {entry['date']}")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build wikilink index from mistakes + ledger.")
    ap.add_argument("--md-only", action="store_true", help="Write only Markdown")
    ap.add_argument("--json-only", action="store_true", help="Write only JSON")
    args = ap.parse_args()

    graph = build_graph()

    if not args.json_only:
        WIKILINK_MD.parent.mkdir(parents=True, exist_ok=True)
        WIKILINK_MD.write_text(format_markdown(graph), encoding="utf-8")
        print(f"[wikilink] wrote {WIKILINK_MD}")
        if WORKSHOP_DIR.exists():
            WORKSHOP_WIKILINK_MD.parent.mkdir(parents=True, exist_ok=True)
            WORKSHOP_WIKILINK_MD.write_text(format_markdown(graph), encoding="utf-8")
            print(f"[wikilink] wrote {WORKSHOP_WIKILINK_MD}")

    if not args.md_only:
        WIKILINK_JSON.parent.mkdir(parents=True, exist_ok=True)
        # entries can have a 'phase' or 'kind' — both are kept
        WIKILINK_JSON.write_text(
            json.dumps(graph, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"[wikilink] wrote {WIKILINK_JSON}")
        if WORKSHOP_DIR.exists():
            WORKSHOP_WIKILINK_JSON.parent.mkdir(parents=True, exist_ok=True)
            WORKSHOP_WIKILINK_JSON.write_text(
                json.dumps(graph, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"[wikilink] wrote {WORKSHOP_WIKILINK_JSON}")

    summary = graph["summary"]
    print(f"[wikilink] {summary['total']} entries ({summary['by_kind']}) "
          f"across {summary['skills_referenced']} skills")
    return 0


if __name__ == "__main__":
    sys.exit(main())
