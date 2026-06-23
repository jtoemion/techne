#!/usr/bin/env python3
"""
pipeline_diagnose.py — Diagnostic tool for pipeline errors, stuck tasks,
retry budgets, and mode overrides.

Usage:
    python3 pipeline_diagnose.py list-failed [--db PATH]
    python3 pipeline_diagnose.py status <task-id> [--db PATH]
    python3 pipeline_diagnose.py overrides [--limit N]
    python3 pipeline_diagnose.py retries <task-id>
    python3 pipeline_diagnose.py --help
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Add harness to path
HARNESS_DIR = Path(__file__).parent.parent / "harness"
sys.path.insert(0, str(HARNESS_DIR))

try:
    from task_db import TaskDB, Task, TaskEvent
except ImportError:
    TaskDB = None
    Task = None
    TaskEvent = None

# ── Colour helpers ────────────────────────────────────────────────────────────

RED   = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN  = "\033[96m"
BOLD  = "\033[1m"
RESET = "\033[0m"


def col(msg: str, c: str) -> str:
    return f"{c}{msg}{RESET}"


def status_color(s: str) -> str:
    s = s.upper()
    if s in ("FAILED",):
        return RED
    if s in ("DONE", "VERIFIED", "IMPLEMENTED", "REVIEWED"):
        return GREEN
    if s in ("BLOCKED", "IN_PROGRESS"):
        return YELLOW
    return ""


# ── Default paths ─────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent.parent
DEFAULT_DB = ROOT / ".techne" / "memory" / "tasks.db"
DEFAULT_OVERRIDES = ROOT / ".techne" / "memory" / "mode_overrides.log"


# ── Shared DB opener ──────────────────────────────────────────────────────────

def open_db(db_path: str | Path | None) -> TaskDB | None:
    p = Path(db_path) if db_path else DEFAULT_DB
    if not p.exists():
        return None
    try:
        return TaskDB(str(p))
    except Exception as e:
        print(f"{RED}Error opening DB at {p}: {e}{RESET}", file=sys.stderr)
        return None


# ── Command: list-failed ──────────────────────────────────────────────────────

HELPFUL_STATUSES = ("FAILED", "BLOCKED")


def cmd_list_failed(db: TaskDB | None, args: argparse.Namespace) -> int:
    if db is None:
        print(f"{YELLOW}No task DB found at default location "
              f"({DEFAULT_DB}) and --db not specified. "
              f"Nothing to list.{RESET}")
        return 0

    tasks = []
    for status in HELPFUL_STATUSES:
        tasks.extend(db.get_tasks_by_status(status))

    if not tasks:
        print(f"{GREEN}No failed or blocked tasks found.{RESET}")
        return 0

    # Header
    print(f"\n{BOLD}{'TASK ID':<14} {'STATUS':<10} {'PHASE MODE':<10} "
          f"{'ATTEMPT':<8} {'TITLE':<40}{RESET}")
    print("-" * 90)

    for t in tasks:
        sc = status_color(t.status)
        title = t.title[:38] + ".." if len(t.title) > 40 else t.title
        print(f"{t.id:<14} {col(t.status, sc):<10} "
              f"{t.phase_mode:<10} {t.attempt}/{t.max_attempts:<6} "
              f"{title:<40}")

    print(f"\n{GREEN}{len(tasks)} task(s) found.{RESET}")

    # Per-task last error from event history
    print(f"\n{BOLD}Last error / block reason per task:{RESET}")
    for t in tasks:
        history = db.get_task_history(t.id)
        # Get the most recent fail/block event
        last_error = None
        for evt in reversed(history):
            if evt.action in ("fail", "block"):
                last_error = evt
                break
        if last_error:
            summary = (last_error.summary or last_error.findings or "")[:80]
            print(f"  [{t.id[:8]}] {col(t.status, status_color(t.status))}: {summary}")
        else:
            print(f"  [{t.id[:8]}] {col(t.status, status_color(t.status))}: (no event details)")

    # Note about retry counts
    print(f"\n{YELLOW}NOTE: Per-phase retry counts (_phase_retry_counts) are kept in-memory "
          f"by the OrchestratorLoop and are NOT persisted in the DB. "
          f"Use the 'retries' command against a live process to see current budgets.{RESET}")

    return 0


# ── Command: status ────────────────────────────────────────────────────────────

def cmd_status(db: TaskDB | None, args: argparse.Namespace) -> int:
    task_id = args.task_id

    if db is None:
        print(f"{RED}Task DB not available.{RESET}", file=sys.stderr)
        return 1

    task = db.get_task(task_id) if db else None
    if task is None:
        print(f"{RED}Task not found: {task_id}{RESET}", file=sys.stderr)
        return 1

    # Basic info
    print(f"\n{BOLD}── Task {task.id} ──{RESET}")
    print(f"  Title:       {task.title}")
    print(f"  Status:      {col(task.status, status_color(task.status))}")
    print(f"  Phase mode:  {task.phase_mode}")
    print(f"  Discipline:  {task.discipline}")
    print(f"  Attempt:     {task.attempt} / {task.max_attempts}")
    print(f"  Agent:       {task.assigned_agent or '(none)'}")
    print(f"  Priority:    {task.priority}")
    print(f"  Tags:        {', '.join(task.tags) if task.tags else '(none)'}")
    print(f"  Parent ID:   {task.parent_id or '(none)'}")
    print(f"  Created:     {task.created_at}")
    print(f"  Updated:     {task.updated_at}")

    # Event history
    history = db.get_task_history(task_id)
    print(f"\n{BOLD}── Event History ({len(history)} event(s)) ──{RESET}")
    if not history:
        print("  (no events)")
    else:
        for evt in history:
            vc = RED if evt.verdict in ("HARD_FAIL", "BLOCK") else GREEN if evt.verdict == "PASS" else ""
            ver = f" [{col(evt.verdict, vc)}]" if evt.verdict else ""
            files = ""
            if evt.changed_files:
                files = f", files={evt.changed_files}"
            summary = (evt.summary or "")[:60]
            print(f"  {evt.timestamp[:19]}  [{evt.agent}] {evt.action}{ver}  {summary}{files}")

    # Last error
    print(f"\n{BOLD}── Last Error / Block ──{RESET}")
    for evt in reversed(history):
        if evt.action in ("fail", "block") and (evt.summary or evt.findings):
            print(f"  [{evt.action.upper()}] {evt.summary or evt.findings}")
            break
    else:
        print("  (none)")

    # Retry note
    print(f"\n{YELLOW}NOTE: Per-phase retry budgets are in-memory only (not persisted). "
          f"Run 'retries {task_id}' with a live orchestrator process to see current counts.{RESET}")

    return 0


# ── Command: overrides ────────────────────────────────────────────────────────

def cmd_overrides(args: argparse.Namespace) -> int:
    log_path = Path(args.overrides_file) if args.overrides_file else DEFAULT_OVERRIDES

    if not log_path.exists():
        print(f"{YELLOW}Override log not found at {log_path}{RESET}")
        return 0

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except Exception as e:
        print(f"{RED}Error reading override log: {e}{RESET}", file=sys.stderr)
        return 1

    recent = lines[-args.limit:] if args.limit > 0 else lines

    if not recent:
        print(f"{GREEN}No override entries found.{RESET}")
        return 0

    print(f"\n{BOLD}{'TIMESTAMP':<28} {'TASK ID':<14} {'SUGGESTED':<10} "
          f"{'CHOSEN':<10} {'DIFF LINES':<10} {'FILES':<6} {'HAS LOGIC':<10}{RESET}")
    print("-" * 96)

    for line in recent:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        ts     = entry.get("timestamp", "")[:19]
        tid    = entry.get("task_id", "")[:12]
        sug    = entry.get("suggested_mode", "")
        chosen = entry.get("chosen_mode", "")
        dl     = entry.get("diff_lines", "-")
        fc     = entry.get("file_count", "-")
        hl     = str(entry.get("has_logic", False))

        # Colour the chosen mode if it differs from suggested
        chosen_col = GREEN if chosen == sug else YELLOW
        sug_col    = GREEN

        print(f"{ts:<28} {tid:<14} {col(sug, sug_col):<10} "
              f"{col(chosen, chosen_col):<10} {str(dl):<10} {str(fc):<6} {hl:<10}")

    print(f"\n{GREEN}{len(recent)} override(s) shown.{RESET}")
    return 0


# ── Command: retries ──────────────────────────────────────────────────────────

def cmd_retries(db: TaskDB | None, args: argparse.Namespace) -> int:
    task_id = args.task_id

    print(f"\n{BOLD}── Retry budget info for task {task_id} ──{RESET}")
    print(f"\n{RED}NOTE: Per-phase retry counts are stored IN-MEMORY by the "
          f"OrchestratorLoop process and are NOT persisted in the task DB.{RESET}")
    print(f"{YELLOW}This command cannot retrieve live retry counts without a "
          f"running orchestrator process.{RESET}\n")

    # Show static info from the DB
    if db is None:
        print(f"{YELLOW}Task DB not available — cannot show attempt info.{RESET}")
        return 1

    task = db.get_task(task_id)
    if task is None:
        print(f"{RED}Task not found: {task_id}{RESET}", file=sys.stderr)
        return 1

    print(f"  Attempt: {task.attempt} / {task.max_attempts} (persisted in DB)")

    # Show MAX_PHASE_RETRIES constants (these are the budgets from orchestrator_loop.py)
    try:
        from orchestrator_loop import MAX_PHASE_RETRIES
        print(f"\n  {BOLD}MAX_PHASE_RETRIES budgets (from orchestrator_loop.py):{RESET}")
        for phase, budget in MAX_PHASE_RETRIES.items():
            print(f"    {phase:<18}: {budget}")
    except ImportError:
        print(f"\n  {YELLOW}Could not import MAX_PHASE_RETRIES from orchestrator_loop.py "
              f"(not in PYTHONPATH).{RESET}")

    print(f"\n  {BOLD}Global budgets (from orchestrator_loop.py):{RESET}")
    try:
        from orchestrator_loop import MAX_IMPLEMENT_RETRIES, MAX_TOTAL_RETRIES
        print(f"    MAX_IMPLEMENT_RETRIES : {MAX_IMPLEMENT_RETRIES}")
        print(f"    MAX_TOTAL_RETRIES     : {MAX_TOTAL_RETRIES}")
    except ImportError:
        print(f"    {YELLOW}(could not import global retry budgets){RESET}")

    return 0


# ── Main ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline_diagnose.py",
        description="Diagnostic tool for pipeline errors, stuck tasks, retry budgets, and mode overrides.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 pipeline_diagnose.py list-failed
  python3 pipeline_diagnose.py list-failed --db /path/to/tasks.db
  python3 pipeline_diagnose.py status 3f9a2c1d
  python3 pipeline_diagnose.py overrides --limit 10
  python3 pipeline_diagnose.py retries 3f9a2c1d
  python3 pipeline_diagnose.py overrides
        """,
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        help=f"Path to task DB (default: {DEFAULT_DB})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list-failed
    p_list = sub.add_parser("list-failed", help="List all FAILED and BLOCKED tasks")

    # status
    p_status = sub.add_parser("status", help="Show full detail for one task")
    p_status.add_argument("task_id", help="Task ID to inspect")

    # overrides
    p_ov = sub.add_parser("overrides", help="Show recent mode classifier overrides")
    p_ov.add_argument(
        "--limit", "-n",
        type=int, default=20,
        metavar="N",
        help="Number of recent entries to show (default: 20)",
    )
    p_ov.add_argument(
        "--overrides-file",
        metavar="PATH",
        default=None,
        help=f"Override log path (default: {DEFAULT_OVERRIDES})",
    )

    # retries
    p_ret = sub.add_parser("retries", help="Show per-phase retry counts for a task")
    p_ret.add_argument("task_id", help="Task ID to inspect")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Open DB for commands that need it
    db = None
    if args.command in ("list-failed", "status", "retries"):
        db = open_db(args.db)

    if args.command == "list-failed":
        return cmd_list_failed(db, args)
    elif args.command == "status":
        return cmd_status(db, args)
    elif args.command == "overrides":
        return cmd_overrides(args)
    elif args.command == "retries":
        return cmd_retries(db, args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
