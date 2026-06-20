#!/usr/bin/env python3
"""
context_search.py — graph-aware workshop retrieval for RECALL and debugging.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
HARNESS_DIR = REPO_ROOT / "harness"
sys.path.insert(0, str(HARNESS_DIR))

from workshop import (  # noqa: E402
    find_workshop_paths,
    load_context_index,
    parse_frontmatter,
    read_context_docs,
    score_text,
    workshop_memory_candidates,
)


def _query_terms(query: str) -> list[str]:
    return [t for t in re.split(r"\W+", query.lower()) if t]


def _load_wikilinks(paths) -> dict:
    mem = workshop_memory_candidates(paths)
    p = mem["wikilinks_json"]
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _search_context_docs(query_terms: list[str], docs: list[dict]) -> list[dict]:
    scored = []
    for doc in docs:
        score = score_text(query_terms, doc["subsystem"], " ".join(doc.get("tags", [])), doc.get("body", ""), " ".join(doc.get("paths", [])))
        if score > 0:
            scored.append({"score": score, **doc})
    return sorted(scored, key=lambda x: (-x["score"], x["subsystem"]))


def _search_files(query_terms: list[str], index: dict) -> list[dict]:
    scored = []
    for entry in index.get("files", []):
        score = score_text(query_terms, entry["path"], entry.get("subsystem") or "")
        if score > 0:
            scored.append({"score": score, **entry})
    return sorted(scored, key=lambda x: (-x["score"], x["path"]))


def _search_memory(query_terms: list[str], wikilinks: dict) -> tuple[list[dict], list[dict], list[dict]]:
    entries = wikilinks.get("entries", []) if isinstance(wikilinks, dict) else []
    lessons, mistakes, decisions = [], [], []
    for entry in entries:
        score = score_text(query_terms, entry.get("what", ""), entry.get("why", ""), entry.get("lesson", ""), entry.get("skill", ""))
        if score <= 0:
            continue
        enriched = {"score": score, **entry}
        kind = entry.get("kind")
        if kind == "MISTAKE":
            mistakes.append(enriched)
        elif kind == "DECISION":
            decisions.append(enriched)
        else:
            lessons.append(enriched)
    sorter = lambda rows: sorted(rows, key=lambda x: (-x["score"], x.get("date", "")), reverse=False)
    return sorter(lessons), sorter(mistakes), sorter(decisions)


def _render_human(query: str, subsystems: list[dict], docs: list[dict], files: list[dict], lessons: list[dict], mistakes: list[dict], decisions: list[dict]) -> str:
    lines = [f"QUERY: {query}"]
    lines.append("LIKELY_SUBSYSTEMS:")
    if subsystems:
        for s in subsystems:
            lines.append(f"- {s['name']} ({s['score']:.2f})")
    else:
        lines.append("- none")

    lines.append("\nCONTEXT_DOCS:")
    for doc in docs[:5]:
        lines.append(f"- {doc['path']} ({doc['subsystem']})")
    if not docs:
        lines.append("- none")

    lines.append("\nFILES:")
    for file in files[:8]:
        lines.append(f"- {file['path']}")
    if not files:
        lines.append("- none")

    lines.append("\nLESSONS:")
    for row in lessons[:5]:
        lines.append(f"- {row.get('what', '')}")
    if not lessons:
        lines.append("- none")

    lines.append("\nMISTAKES:")
    for row in mistakes[:5]:
        lines.append(f"- {row.get('what', '')}")
    if not mistakes:
        lines.append("- none")

    lines.append("\nDECISIONS:")
    for row in decisions[:5]:
        lines.append(f"- {row.get('what', '')}")
    if not decisions:
        lines.append("- none")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Search the Techne workshop context graph.")
    ap.add_argument("query", nargs="?", help="Free-text query")
    ap.add_argument("--task", help="Task text to search as a query")
    ap.add_argument("--kind", choices=["subsystem", "context", "file", "lesson", "mistake", "decision"], help="Optional result focus")
    ap.add_argument("--json", action="store_true", help="Print JSON output")
    args = ap.parse_args()

    query = args.query or args.task
    if not query:
        print("[context_search] Provide a query or --task.", file=sys.stderr)
        return 2

    paths = find_workshop_paths(Path.cwd())
    if paths is None:
        print("[context_search] No .techne/config.yaml found while walking upward from cwd.", file=sys.stderr)
        return 2

    try:
        index = load_context_index(paths)
    except FileNotFoundError as e:
        print(f"[context_search] {e}", file=sys.stderr)
        return 2

    terms = _query_terms(query)
    docs = read_context_docs(paths)
    wikilinks = _load_wikilinks(paths)

    doc_hits = _search_context_docs(terms, docs)
    file_hits = _search_files(terms, index)
    lesson_hits, mistake_hits, decision_hits = _search_memory(terms, wikilinks)

    subsystem_scores: dict[str, float] = {}
    for hit in doc_hits[:8]:
        subsystem_scores[hit["subsystem"]] = subsystem_scores.get(hit["subsystem"], 0.0) + hit["score"] * 1.5
    for hit in file_hits[:12]:
        if hit.get("subsystem"):
            subsystem_scores[hit["subsystem"]] = subsystem_scores.get(hit["subsystem"], 0.0) + hit["score"]

    max_score = max(subsystem_scores.values()) if subsystem_scores else 1.0
    subsystems = [
        {"name": name, "score": round(score / max_score, 2)}
        for name, score in sorted(subsystem_scores.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    result = {
        "query": query,
        "subsystems": subsystems,
        "context_docs": [{"path": d["path"], "subsystem": d["subsystem"], "score": d["score"]} for d in doc_hits[:8]],
        "files": [{"path": f["path"], "subsystem": f.get("subsystem"), "score": f["score"]} for f in file_hits[:12]],
        "lessons": lesson_hits[:8],
        "mistakes": mistake_hits[:8],
        "decisions": decision_hits[:8],
    }

    if args.kind:
        kind_map = {
            "subsystem": {"query": query, "subsystems": result["subsystems"]},
            "context": {"query": query, "context_docs": result["context_docs"]},
            "file": {"query": query, "files": result["files"]},
            "lesson": {"query": query, "lessons": result["lessons"]},
            "mistake": {"query": query, "mistakes": result["mistakes"]},
            "decision": {"query": query, "decisions": result["decisions"]},
        }
        result = kind_map[args.kind]

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(_render_human(
            query,
            result.get("subsystems", []),
            result.get("context_docs", []),
            result.get("files", []),
            result.get("lessons", []),
            result.get("mistakes", []),
            result.get("decisions", []),
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
