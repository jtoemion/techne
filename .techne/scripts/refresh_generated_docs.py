#!/usr/bin/env python3
"""
refresh_generated_docs.py — refresh deterministic workshop artifacts from touched files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
HARNESS_DIR = REPO_ROOT / "harness"
sys.path.insert(0, str(HARNESS_DIR))

from workshop import (  # noqa: E402
    build_context_index,
    detect_subsystems_for_files,
    find_workshop_paths,
    load_workshop_config,
    now_utc,
    read_context_docs,
    stale_context_reasons,
    touched_files_from_git,
    write_json,
)
from wikilink import build_graph, format_markdown  # noqa: E402


def _write_wikilinks(paths) -> list[str]:
    graph = build_graph()
    writes = []
    root_mem = paths.repo_root / "memory"
    root_mem.mkdir(parents=True, exist_ok=True)
    root_json = root_mem / "wikilinks.json"
    root_md = root_mem / "wikilinks.md"
    root_json.write_text(json.dumps(graph, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    root_md.write_text(format_markdown(graph), encoding="utf-8")
    writes.extend([str(root_json), str(root_md)])

    paths.memory_dir.mkdir(parents=True, exist_ok=True)
    workshop_json = paths.memory_dir / "wikilinks.json"
    workshop_md = paths.memory_dir / "wikilinks.md"
    workshop_json.write_text(json.dumps(graph, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    workshop_md.write_text(format_markdown(graph), encoding="utf-8")
    writes.extend([str(workshop_json), str(workshop_md)])
    return writes


def _load_existing_change_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("events", []) if isinstance(payload, dict) else []
    except Exception:
        return []


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh Techne workshop generated artifacts.")
    ap.add_argument("--task", help="Optional task ID to store refresh artifact under .techne/tasks/<task>/")
    ap.add_argument("--files", nargs="*", help="Explicit touched files, relative to repo root")
    ap.add_argument("--since", help="Git revision/range to diff from (default: HEAD working tree)")
    ap.add_argument("--json", action="store_true", help="Print JSON result")
    args = ap.parse_args()

    if not args.task and not args.files and not args.since:
        print("[refresh_generated_docs] Provide --task, --files, or --since.", file=sys.stderr)
        return 2

    paths = find_workshop_paths(Path.cwd())
    if paths is None:
        print("[refresh_generated_docs] No .techne/config.yaml found while walking upward from cwd.", file=sys.stderr)
        return 2

    context_index = build_context_index(paths)
    write_json(paths.generated_dir / "context_index.json", context_index)
    write_json(paths.generated_dir / "subsystem_map.json", {
        "generated_at": context_index["generated_at"],
        "repo_root": context_index["repo_root"],
        "subsystem_map": {row["path"]: row.get("subsystem") for row in context_index.get("files", []) if row.get("subsystem")},
    })

    if args.files:
        touched = [f.strip() for f in args.files if f and f.strip()]
    else:
        touched = touched_files_from_git(paths.repo_root, since=args.since)

    subsystems = detect_subsystems_for_files(context_index, touched)
    context_docs = read_context_docs(paths)
    stale = stale_context_reasons(touched, context_docs)
    cfg = load_workshop_config(paths)

    wikilink_updates = _write_wikilinks(paths)

    change_log_path = paths.generated_dir / "change_log.json"
    events = _load_existing_change_log(change_log_path)
    event = {
        "generated_at": now_utc(),
        "task_id": args.task,
        "touched_files": touched,
        "subsystems": subsystems,
        "stale_docs": stale,
        "generated_updated": [
            str(paths.generated_dir / "context_index.json"),
            str(paths.generated_dir / "subsystem_map.json"),
            *wikilink_updates,
        ],
    }
    events.append(event)
    change_payload = {
        "repo_root": str(paths.repo_root.resolve()),
        "events": events[-50:],
    }
    write_json(change_log_path, change_payload)

    stale_payload = {
        "generated_at": event["generated_at"],
        "repo_root": str(paths.repo_root.resolve()),
        "stale_docs": stale,
    }
    write_json(paths.generated_dir / "stale_docs.json", stale_payload)

    task_artifact = None
    if args.task:
        task_dir = paths.tasks_dir / args.task
        task_dir.mkdir(parents=True, exist_ok=True)
        task_artifact = task_dir / "refresh_context.json"
        write_json(task_artifact, event)

    result = {
        "task_id": args.task,
        "touched_files": touched,
        "subsystems": subsystems,
        "generated_updated": event["generated_updated"] + [str(change_log_path), str(paths.generated_dir / "stale_docs.json")],
        "stale_docs": stale,
        "task_artifact": str(task_artifact) if task_artifact else None,
        "policies": cfg.get("proposal_policies", {}),
    }

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"[refresh_generated_docs] touched files: {len(touched)}")
        for touched_file in touched:
            print(f"- {touched_file}")
        print(f"[refresh_generated_docs] subsystems: {', '.join(subsystems) if subsystems else '(none)'}")
        print(f"[refresh_generated_docs] stale docs: {len(stale)}")
        if task_artifact:
            print(f"[refresh_generated_docs] task artifact: {task_artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
