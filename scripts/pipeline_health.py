#!/usr/bin/env python3
"""pipeline_health.py — Check pipeline health: DB integrity, stuck tasks, stale state.

Usage:
    python3 scripts/pipeline_health.py                    # full report
    python3 scripts/pipeline_health.py --quick             # status only
    python3 scripts/pipeline_health.py --db path/to.db     # custom DB path
"""

from __future__ import annotations
import argparse, os, sqlite3, subprocess, sys, time
from pathlib import Path

# Windows cp1252 consoles cannot encode emoji — reconfigure stdout to UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
DEFAULT_DB = ROOT / ".techne" / "memory" / "tasks.db"

def fmtage(ts: float | None) -> str:
    if ts is None:
        return "never"
    age = time.time() - ts
    if age < 60:
        return f"{age:.0f}s ago"
    if age < 3600:
        return f"{age/60:.0f}m ago"
    return f"{age/3600:.1f}h ago"

def check_db(db_path: Path) -> tuple[int, list[str]]:
    issues: list[str] = []
    if not db_path.exists():
        return 0, ["DB not found"]
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute("SELECT COUNT(*) FROM tasks")
        count = cur.fetchone()[0]
        cur = conn.execute("SELECT id, status, phase, created_at FROM tasks ORDER BY created_at DESC LIMIT 10")
        tasks = cur.fetchall()
        conn.close()

        stuck = [t for t in tasks if t[1] in ("PENDING", "BLOCKED") and t[3] and (time.time() - t[3]) > 3600]
        for t in stuck:
            issues.append(f"Task {t[0][:12]} {t[1]} in phase {t[2]} ({fmtage(t[3])})")

        return count, issues
    except Exception as e:
        return 0, [f"DB error: {e}"]

def check_git() -> list[str]:
    issues: list[str] = []
    try:
        r = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=ROOT, timeout=10)
        dirty = [l for l in r.stdout.strip().split("\n") if l.strip()]
        if dirty:
            issues.append(f"{len(dirty)} uncommitted files")
        # Check for untracked .techne artifacts
        for l in dirty:
            path = l.split(None, 1)[1] if " " in l else l[3:]
            if ".techne/tasks/" in path or ".techne/memory/" in path:
                issues.append(f"  Generated artifact leak: {path}")
    except Exception: pass
    return issues

def check_state() -> list[str]:
    issues: list[str] = []
    state_file = ROOT / ".techne" / "memory" / "harness-state.json"
    if state_file.exists():
        try:
            import json
            state = json.loads(state_file.read_text())
            if not state.get("honcho_conclusion_id"):
                issues.append("harness-state.json missing honcho_conclusion_id (RECALL gate will loop)")
        except Exception: pass
    return issues

def main():
    parser = argparse.ArgumentParser(description="Check pipeline health")
    parser.add_argument("--quick", action="store_true", help="Status summary only")
    parser.add_argument("--db", default=None, help="Custom DB path")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else DEFAULT_DB
    quick = args.quick

    print("=== Pipeline Health ===\n")
    count, db_issues = check_db(db_path)
    print(f"Tasks in DB: {count}")
    if db_issues:
        print("  Issues:")
        for i in db_issues:
            print(f"  ⚠️  {i}")
    elif count > 0:
        print("  No stuck tasks.")

    if quick:
        if not db_issues:
            print("\nStatus: OK")
        else:
            print(f"\nStatus: {len(db_issues)} issue(s)")
        return

    print()
    git_issues = check_git()
    if git_issues:
        print(f"Git:")
        for i in git_issues:
            print(f"  ⚠️  {i}")
    else:
        print(f"Git: clean")

    state_issues = check_state()
    if state_issues:
        print(f"State:")
        for i in state_issues:
            print(f"  ⚠️  {i}")

    print(f"\nScript: {__file__}")
    print(f"DB:     {db_path}")

if __name__ == "__main__":
    main()
