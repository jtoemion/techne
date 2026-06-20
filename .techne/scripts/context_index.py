#!/usr/bin/env python3
"""
context_index.py — build deterministic workshop indexes from `.techne/context/*.CONTEXT.md`
and the repo file tree.
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

from workshop import build_context_index, find_workshop_paths, write_json  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Build Techne workshop context indexes.")
    ap.add_argument("--subsystem", help="Optional subsystem filter for printed output")
    ap.add_argument("--json", action="store_true", help="Print JSON instead of summary text")
    args = ap.parse_args()

    paths = find_workshop_paths(Path.cwd())
    if paths is None:
        print("[context_index] No .techne/config.yaml found while walking upward from cwd.", file=sys.stderr)
        return 2

    index = build_context_index(paths)
    write_json(paths.generated_dir / "context_index.json", index)
    subsystem_map = {
        entry["path"]: entry.get("subsystem")
        for entry in index.get("files", [])
        if entry.get("subsystem")
    }
    write_json(paths.generated_dir / "subsystem_map.json", {
        "generated_at": index["generated_at"],
        "repo_root": index["repo_root"],
        "subsystem_map": subsystem_map,
    })

    if args.subsystem:
        filtered = [s for s in index.get("subsystems", []) if s["name"] == args.subsystem]
        payload = {
            "generated_at": index["generated_at"],
            "repo_root": index["repo_root"],
            "subsystems": filtered,
            "files": [f for f in index.get("files", []) if f.get("subsystem") == args.subsystem],
        }
    else:
        payload = index

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        subsystems = payload.get("subsystems", [])
        print(f"[context_index] wrote {paths.generated_dir / 'context_index.json'}")
        print(f"[context_index] wrote {paths.generated_dir / 'subsystem_map.json'}")
        print(f"[context_index] subsystem docs: {len(subsystems)}")
        for subsystem in subsystems:
            print(
                f"- {subsystem['name']}: {subsystem.get('file_count', 0)} files | "
                f"doc {subsystem.get('context_doc')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
