#!/usr/bin/env python3
"""task_reset.py — Force-reset a truly stuck task (PENDING/BLOCKED with no recovery).

Usage:
    python3 scripts/task_reset.py <task_id>                    # reset to PENDING
    python3 scripts/task_reset.py <task_id> --phase RECALL     # reset to specific phase
    python3 scripts/task_reset.py <task_id> --status FAILED    # mark as failed
    python3 scripts/task_reset.py <task_id> --dry-run          # preview only
"""

from __future__ import annotations
import argparse, sqlite3, sys, json, time
from pathlib import Path

ROOT = Path(__file__).parent.parent
DEFAULT_DB = ROOT / "techne" / "tasks.db"
STATE_FILE = ROOT / ".techne" / "memory" / "harness-state.json"

VALID_PHASES = ("RECALL", "IMPLEMENT", "CONTEXT_GUARD", "CRITIQUE", "REVIEW",
                "VERIFY", "EVAL", "RETRO", "CONCLUDE", "REFRESH_CONTEXT", "APPROVAL")
VALID_STATUSES = ("PENDING", "RUNNING", "FAILED", "DONE", "CANCELLED")

def find_task(conn, task_id: str) -> tuple | None:
    cur = conn.execute("SELECT id, status, phase, title FROM tasks WHERE id LIKE ?", (f"{task_id}%",))
    rows = cur.fetchall()
    if len(rows) == 0:
        return None
    if len(rows) > 1:
        matches = "\n".join(f"  {r[0][:12]} {r[1]:12} {r[2]:18} {str(r[3] or '')[:30]}" for r in rows)
        print(f"Multiple matches:\n{matches}")
        sys.exit(1)
    return rows[0]

def dry_run_msg(msg: str):
    print(f"  [dry-run] {msg}")

def main():
    parser = argparse.ArgumentParser(description="Force-reset a stuck task")
    parser.add_argument("task_id", help="Task ID (prefix OK if unique)")
    parser.add_argument("--phase", choices=VALID_PHASES, default=None, help="Reset to phase")
    parser.add_argument("--status", choices=VALID_STATUSES, default="PENDING", help="Set status")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    if args.phase and args.status != "PENDING":
        print("Cannot set both --phase and --status. --phase implies PENDING.")
        sys.exit(1)

    db = DEFAULT_DB
    if not db.exists():
        print(f"DB not found: {db}"); sys.exit(1)

    conn = sqlite3.connect(str(db))
    task = find_task(conn, args.task_id)
    if not task:
        print(f"Task not found: {args.task_id}"); sys.exit(1)

    tid, curr_status, curr_phase, title = task
    new_status = args.status
    new_phase = args.phase if args.phase else curr_phase

    print(f"=== Task Reset ===")
    print(f"Task:   {tid[:12]} ({title[:40]})")
    print(f"Before: {curr_status:12} / {curr_phase}")
    print(f"After:  {new_status:12} / {new_phase}")
    print()

    if curr_status == "DONE":
        print("WARNING: Task is DONE. Resetting a completed task may cause data loss.")
    if args.dry_run:
        dry_run_msg(f"UPDATE tasks SET status='{new_status}', phase='{new_phase}' WHERE id='{tid}'")
        conn.close()
        print("\nDry-run complete. Run without --dry-run to execute.")
        return

    confirm = input(f"Reset task {tid[:12]} to {new_status}/{new_phase}? [y/N] ")
    if confirm.lower() not in ("y", "yes"):
        print("Cancelled.")
        conn.close()
        sys.exit(1)

    conn.execute("UPDATE tasks SET status=?, phase=? WHERE id=?", (new_status, new_phase, tid))
    conn.commit()
    conn.close()

    # Update harness state if resetting to PENDING
    if new_status == "PENDING" and STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
            if "pipeline_runs" in state:
                state["pipeline_runs"] = max(0, state["pipeline_runs"] - 1)
                STATE_FILE.write_text(json.dumps(state, indent=2))
                print(f"  Updated harness-state.json.")
        except: pass

    print(f"\nTask {tid[:12]} reset to {new_status}/{new_phase}")
    print("Remember to log why: python3 scripts/mistakes_logger.py log ...")

if __name__ == "__main__":
    main()
