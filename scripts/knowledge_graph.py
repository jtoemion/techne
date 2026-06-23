#!/usr/bin/env python3
"""knowledge_graph.py — Query and explore the Techne knowledge graph.

Builds from: wikilinks.json (phase links), tasks.db (task outcomes), 
mistakes.md (lesson recurrence), rewards.db (GRPO scores).

Usage:
    python3 scripts/knowledge_graph.py status               # overall graph health
    python3 scripts/knowledge_graph.py phases               # phase outcome breakdown
    python3 scripts/knowledge_graph.py mistakes             # mistake recurrence
    python3 scripts/knowledge_graph.py skill <name>         # skill graph
    python3 scripts/knowledge_graph.py file <path>          # file graph (project mode)
    python3 scripts/knowledge_graph.py search <term>        # search nodes
"""

from __future__ import annotations
import argparse, json, sqlite3, subprocess, sys, re
from pathlib import Path

ROOT = Path(__file__).parent.parent
WIKILINKS = ROOT / ".techne" / "memory" / "wikilinks.json"
TASKS_DB = ROOT / ".techne" / "memory" / "tasks.db"
MISTAKES = ROOT / ".techne" / "memory" / "mistakes.md"

def load_wikilinks() -> dict:
    if not WIKILINKS.exists():
        return {}
    return json.loads(WIKILINKS.read_text())

def cmd_status():
    g = load_wikilinks()
    if not g:
        print("Graph: empty — no wikilinks data.")
        return
    nodes = g.get("nodes", [])
    edges = g.get("edges", [])
    entries = g.get("entries", [])
    skills = g.get("skills", [])
    print(f"Nodes:  {len(nodes)}")
    print(f"Edges:  {len(edges)}")
    print(f"Entries:{len(entries)}")
    print(f"Skills: {len(skills)}")
    # Node kind breakdown
    types: dict[str, int] = {}
    for n in nodes:
        t = n.get("kind", "unknown")
        types[t] = types.get(t, 0) + 1
    if types:
        print(f"\nNode types:")
        for t, c in sorted(types.items(), key=lambda x: -x[1]):
            print(f"  {t}: {c}")

def cmd_phases():
    db = TASKS_DB
    if not db.exists():
        print("No tasks.db — no phase data.")
        return
    try:
        conn = sqlite3.connect(str(db))
        cur = conn.execute("SELECT phase, status, COUNT(*) FROM tasks GROUP BY phase, status")
        rows = cur.fetchall()
        conn.close()
    except sqlite3.OperationalError as e:
        print(f"DB schema issue — cannot query phases: {e}")
        return
    if not rows:
        print("No phase data.")
        return
    phases: dict[str, dict[str, int]] = {}
    for phase, status, count in rows:
        if phase not in phases:
            phases[phase] = {}
        phases[phase][status or "unknown"] = count
    print("Phase outcomes:")
    print(f"  {'Phase':<20} {'Done':<8} {'Failed':<8} {'Running':<8}")
    print(f"  {'-'*20} {'-'*8} {'-'*8} {'-'*8}")
    for phase, stats in sorted(phases.items()):
        d = stats.get("DONE", 0)
        f = stats.get("FAILED", 0) + stats.get("CANCELLED", 0)
        r = stats.get("PENDING", 0) + stats.get("BLOCKED", 0)
        print(f"  {phase:<20} {d:<8} {f:<8} {r:<8}")

def cmd_mistakes():
    if not MISTAKES.exists():
        print("No mistakes.md.")
        return
    text = MISTAKES.read_text()
    entries = re.findall(r"- \*\*(mistake-\d+)\*\*:", text)
    phases = re.findall(r"\*\*Phase:\*\* (\w+)", text)
    active = text.count("**Status:** active")
    resolved = text.count("**Status:** resolved")
    print(f"Total entries: {len(entries)}")
    print(f"Active:  {active}")
    print(f"Resolved:{resolved}")
    if phases:
        from collections import Counter
        phase_counts = Counter(phases)
        print(f"\nBy phase:")
        for p, c in phase_counts.most_common(5):
            print(f"  {p}: {c}")

def cmd_skill(name: str):
    g = load_wikilinks()
    if not g:
        print("Graph empty.")
        return
    nodes = g.get("nodes", [])
    edges = g.get("edges", [])
    # Find skill nodes
    skill_nodes = [n for n in nodes if n.get("kind") == "skill" and name.lower() in n.get("id", "").lower()]
    if not skill_nodes:
        print(f"No skill nodes matching '{name}'")
        return
    for sn in skill_nodes:
        sid = sn.get("id", "?")
        print(f"Skill: {sid}")
        linked = [e for e in edges if e.get("source") == sid or e.get("target") == sid]
        for e in linked[:10]:
            src = e.get("source", "?")
            tgt = e.get("target", "?")
            kind = e.get("type", "link")
            print(f"  {src[:40]:40} --{kind}--> {tgt[:40]}")
        if len(linked) > 10:
            print(f"  ... and {len(linked)-10} more edges")

def cmd_file(search_path: str):
    """Project graph mode — search file nodes in wikilinks."""
    g = load_wikilinks()
    if not g:
        print("Graph empty.")
        return
    nodes = g.get("nodes", [])
    edges = g.get("edges", [])
    file_nodes = [n for n in nodes if n.get("kind") in ("file", "module") and search_path in n.get("id", "")]
    if not file_nodes:
        print(f"No file nodes matching '{search_path}'")
        return
    for fn in file_nodes:
        fid = fn.get("id", "?")
        print(f"File: {fid}")
        linked = [e for e in edges if e.get("source") == fid or e.get("target") == fid]
        for e in linked[:8]:
            src = e.get("source", "?")
            tgt = e.get("target", "?")
            kind = e.get("type", "link")
            print(f"  {src[:40]:40} --{kind}--> {tgt[:40]}")

def cmd_search(term: str):
    g = load_wikilinks()
    if not g:
        print("Graph empty.")
        return
    nodes = g.get("nodes", [])
    matches = []
    for n in nodes:
        nid = n.get("id", "")
        ndesc = n.get("description", "")
        if term.lower() in nid.lower() or term.lower() in ndesc.lower():
            matches.append(n)
    matches = matches[:20]
    if not matches:
        print(f"No nodes matching '{term}'")
        return
    print(f"Found {len(matches)} node(s):")
    for m in matches:
        print(f"  {m.get('id', '?'):50} [{m.get('type', '?')}]  {m.get('description', '')[:40]}")

def main():
    parser = argparse.ArgumentParser(description="Knowledge graph query tool")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Overall graph health")
    sub.add_parser("phases", help="Phase outcome breakdown")
    sub.add_parser("mistakes", help="Mistake recurrence")
    p_skill = sub.add_parser("skill", help="Skill graph")
    p_skill.add_argument("name", help="Skill name to query")
    p_file = sub.add_parser("file", help="File graph (project mode)")
    p_file.add_argument("path", help="File path to search")
    p_search = sub.add_parser("search", help="Search nodes")
    p_search.add_argument("term", help="Search term")

    args = parser.parse_args()
    if args.command == "status": cmd_status()
    elif args.command == "phases": cmd_phases()
    elif args.command == "mistakes": cmd_mistakes()
    elif args.command == "skill": cmd_skill(args.name)
    elif args.command == "file": cmd_file(args.path)
    elif args.command == "search": cmd_search(args.term)

if __name__ == "__main__":
    main()
