#!/usr/bin/env python3
"""task_gardener.py — Purge old artifacts, rotate logs, compact DB.

Usage:
    python3 scripts/task_gardener.py                    # full cleanup
    python3 scripts/task_gardener.py --dry-run           # preview only
    python3 scripts/task_gardener.py --keep 10           # keep last 10 task dirs
    python3 scripts/task_gardener.py --db path/to.db     # custom DB path
"""

from __future__ import annotations
import argparse, json, os, shutil, sqlite3, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).parent.parent
DEFAULT_DB = ROOT / ".techne" / "memory" / "tasks.db"
CLEANABLE_DIRS = [
    ROOT / ".techne" / "tasks",
    ROOT / ".techne" / "generated",
    ROOT / ".techne" / "scripts",
    ROOT / ".techne" / "memory" / "rewards",
    ROOT / ".techne" / "memory" / "prompt_variants",
]

def bytes_fmt(b: int) -> str:
    if b < 1024: return f"{b}B"
    if b < 1024**2: return f"{b/1024:.1f}KB"
    return f"{b/1024**2:.1f}MB"

def dry_run_msg(msg: str):
    print(f"  [dry-run] would {msg}")

def purge_task_dirs(dry_run: bool, keep: int) -> tuple[int, str]:
    removed = 0
    freed = 0
    for d in CLEANABLE_DIRS:
        if not d.exists():
            continue
        items = sorted(d.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        if len(items) <= keep:
            continue
        for item in items[keep:]:
            if item.is_dir():
                size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file()) if not dry_run else 0
                if dry_run:
                    dry_run_msg(f"rm -rf {item.relative_to(ROOT)} ({bytes_fmt(0)})")
                else:
                    shutil.rmtree(item)
                removed += 1
                freed += size
    return removed, bytes_fmt(freed) if not dry_run else "?"

def rotate_log(dry_run: bool, max_lines: int = 2000) -> str | None:
    log = ROOT / ".techne" / "memory" / "mode_overrides.log"
    if not log.exists():
        return None
    lines = log.read_text().splitlines()
    if len(lines) <= max_lines:
        return None
    trimmed = lines[-max_lines:]
    old_len = len(lines)
    if dry_run:
        dry_run_msg(f"trim mode_overrides.log from {old_len} to {max_lines} lines")
        return None
    log.write_text("\n".join(trimmed) + "\n")
    return f"{old_len - max_lines} lines trimmed"

def compact_db(db_path: Path, dry_run: bool) -> str | None:
    if not db_path.exists():
        return None
    before = db_path.stat().st_size
    if dry_run:
        dry_run_msg(f"VACUUM {db_path.name} ({bytes_fmt(before)})")
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("VACUUM")
        conn.close()
        after = db_path.stat().st_size
        saved = before - after
        return f"{bytes_fmt(before)} → {bytes_fmt(after)} (saved {bytes_fmt(saved)})" if saved > 1024 else "negligible"
    except Exception as e:
        return f"compact failed: {e}"

def check_leak(rel_path: str) -> bool:
    try:
        r = subprocess.run(["git", "check-ignore", rel_path], capture_output=True, text=True, cwd=ROOT, timeout=10)
        return r.returncode == 0
    except Exception: return False

def main():
    parser = argparse.ArgumentParser(description="Task Gardener — clean pipeline artifacts")
    parser.add_argument("--dry-run", action="store_true", help="Preview without deleting")
    parser.add_argument("--keep", type=int, default=5, help="Number of task dirs to keep")
    parser.add_argument("--db", default=None, help="Custom DB path")
    parser.add_argument("--force", action="store_true", help="Skip safety prompts")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else DEFAULT_DB
    dry = args.dry_run

    print(f"{'[DRY-RUN] ' if dry else ''}Task Gardener")
    print()

    # Purge old task dirs
    print(f"Purging task dirs (keep last {args.keep}):")
    removed, freed = purge_task_dirs(dry, args.keep)
    if removed == 0:
        print("  Nothing to clean.")
    else:
        print(f"  Removed {removed} directories ({freed})")

    # Rotate log
    print(f"Rotating mode_overrides.log (max 2000 lines):")
    result = rotate_log(dry)
    if result is None:
        print("  Under limit — no rotation needed.")
    else:
        print(f"  {result}")

    # Compact DB
    print(f"Compacting DB ({db_path}):")
    result = compact_db(db_path, dry)
    if result is None:
        print("  DB not found.")
    else:
        print(f"  {result}")

    # Report leaks
    print("Checking for .gitignore leaks:")
    leaks = 0
    for d in CLEANABLE_DIRS:
        if d.exists() and any(d.iterdir()):
            rel = d.relative_to(ROOT)
            if check_leak(str(rel)):
                print(f"  ✅ {rel} is gitignored")
            else:
                print(f"  ⚠️  {rel} — NOT in .gitignore (will be committed!)")
                leaks += 1
    if leaks == 0:
        print("  No leaks detected.")

    if not dry and (removed > 0 or result):
        print(f"\nDone.")
    elif dry:
        print(f"\nDry-run complete. Run without --dry-run to execute.")

if __name__ == "__main__":
    main()
