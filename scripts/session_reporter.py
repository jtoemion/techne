#!/usr/bin/env python3
"""session_reporter.py — Summarize session from task history + Honcho conclusions.

Usage:
    python3 scripts/session_reporter.py                 # recent session summary
    python3 scripts/session_reporter.py --last 24h       # last 24 hours
    python3 scripts/session_reporter.py --last 10        # last 10 tasks
    python3 scripts/session_reporter.py --full           # full detail
"""

from __future__ import annotations
import argparse, json, os, sqlite3, subprocess, sys, time
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
DEFAULT_DB = ROOT / "techne" / "tasks.db"
STATE_FILE = ROOT / ".techne" / "memory" / "harness-state.json"

def task_age(ts: float | None) -> str:
    if ts is None: return "unknown"
    age_s = time.time() - ts
    if age_s < 60: return "just now"
    if age_s < 3600: return f"{age_s//60}m ago"
    if age_s < 86400: return f"{age_s//3600}h ago"
    return f"{age_s//86400}d ago"

def fmt_ts(ts: float | None) -> str:
    if ts is None: return "-"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M")

class Task:
    def __init__(self, row: tuple):
        self.id = row[0]
        self.status = row[1] or "-"
        self.phase = row[2] or "-"
        self.title = (row[3] or "")[:60]
        self.ts = row[4]

def load_tasks(db_path: Path, limit: int = 10) -> list[Task]:
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute(
            "SELECT id, status, phase, title, created_at FROM tasks "
            "ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        tasks = [Task(r) for r in cur.fetchall()]
        conn.close()
        return tasks
    except: return []

def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try: return json.loads(STATE_FILE.read_text())
    except: return {}

def format_task_list(tasks: list[Task], full: bool) -> str:
    if not tasks:
        return "  (no tasks in DB)"
    lines = []
    for t in tasks:
        age = task_age(t.ts)
        if full:
            lines.append(f"  {t.id[:12]}  {t.status:<12} {t.phase:<18} {t.title}")
        else:
            lines.append(f"  {t.id[:12]}  {t.status:<12} {t.phase:<18} {t.title[:40]} {age}")
    return "\n".join(lines)

def recent_git_activity() -> list[str]:
    try:
        r = subprocess.run(["git", "log", "--oneline", "-5", "--", ".techne/context/", "skills/", "harness/"],
                         capture_output=True, text=True, cwd=ROOT, timeout=10)
        if r.stdout.strip():
            return [f"  {l.split(' ', 1)[1][:50] if ' ' in l else l}" for l in r.stdout.strip().split("\n")]
    except: pass
    return []

def main():
    parser = argparse.ArgumentParser(description="Session Reporter — task history summary")
    parser.add_argument("--last", default="5", help="Number of tasks (e.g. '5', '10', 'all')")
    parser.add_argument("--full", action="store_true", help="Show full detail")
    parser.add_argument("--db", default=None, help="Custom DB path")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else DEFAULT_DB
    limit = 100 if args.last == "all" else int(args.last)

    tasks = load_tasks(db_path, limit)
    state = load_state()

    print("=== Session Report ===\n")

    # Summary header
    if tasks:
        done = sum(1 for t in tasks if t.status == "DONE")
        failed = sum(1 for t in tasks if t.status in ("FAILED", "CANCELLED"))
        running = sum(1 for t in tasks if t.status in ("PENDING", "BLOCKED"))
        print(f"Recent tasks: {len(tasks)} total — {done} done, {failed} failed, {running} running\n")

    # Task list
    print(f"Tasks (last {len(tasks)}):")
    print(f"  {'ID':<14} {'Status':<12} {'Phase':<18} {'Title'}")
    print(f"  {'-'*14} {'-'*12} {'-'*18} {'-'*40}")
    print(format_task_list(tasks, args.full))

    # State
    if state:
        print(f"\nHarness state:")
        for k, v in state.items():
            vs = str(v)[:40]
            if k.endswith("_id"):
                vs = vs[:12]
            print(f"  {k}: {vs}")
    else:
        print(f"\nHarness state: not found ({STATE_FILE})")

    # Recent git activity
    git_log = recent_git_activity()
    if git_log:
        print(f"\nRecent context/skill changes:")
        for l in git_log:
            print(l)

    # Summary
    print(f"\nScript: {__file__}")
    print(f"DB:     {db_path}")

if __name__ == "__main__":
    main()
