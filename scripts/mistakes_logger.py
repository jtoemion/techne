#!/usr/bin/env python3
"""mistakes_logger.py — Log a mistake to mistakes.md with proper format.

Usage:
    python3 scripts/mistakes_logger.py log "The lesson" "The root cause" --phase retro
    python3 scripts/mistakes_logger.py list                          # recent entries
    python3 scripts/mistakes_logger.py resolve <id>                  # mark resolved
"""

from __future__ import annotations
import argparse, sys, json, datetime, os, re
from pathlib import Path

ROOT = Path(__file__).parent.parent
MISTAKES_FILE = ROOT / ".techne" / "memory" / "mistakes.md"

def load_entries() -> list[dict]:
    if not MISTAKES_FILE.exists():
        return []
    text = MISTAKES_FILE.read_text()
    entries = []
    current = {}
    for line in text.splitlines():
        m_id = re.match(r"^- \*\*(mistake-\d+)\*\*:", line)
        if m_id:
            if current:
                entries.append(current)
            current = {"id": m_id.group(1), "lines": [line]}
        elif current:
            current["lines"].append(line)
    if current:
        entries.append(current)
    for e in entries:
        full = "\n".join(e["lines"])
        e["lesson"] = re.search(r"\*\*Lesson:\*\* (.+)", full)
        e["lesson"] = e["lesson"].group(1) if e["lesson"] else e["id"]
        e["status"] = "resolved" if "**Status:** resolved" in full else "active"
    return entries

def format_entry(lesson: str, root_cause: str, phase: str, task_id: str) -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lid = f"mistake-{int(datetime.datetime.now().timestamp())}"
    return (
        f"- **{lid}:**\n"
        f"  - **Lesson:** {lesson}\n"
        f"  - **Root Cause:** {root_cause}\n"
        f"  - **Phase:** {phase}\n"
        f"  - **Task:** {task_id}\n"
        f"  - **Status:** active\n"
        f"  - **Date:** {now}\n"
    )

def cmd_log(lesson: str, root_cause: str, phase: str, task_id: str):
    entry = format_entry(lesson, root_cause, phase, task_id)
    MISTAKES_FILE.parent.mkdir(parents=True, exist_ok=True)
    MISTAKES_FILE.write_text(entry) if not MISTAKES_FILE.exists() else MISTAKES_FILE.write_text(
        MISTAKES_FILE.read_text().rstrip() + "\n" + entry
    )
    print(f"Logged {entry.splitlines()[0].strip()}")

def cmd_list():
    entries = load_entries()
    if not entries:
        print("No entries.")
        return
    for e in entries:
        badge = "🔴" if e["status"] == "active" else "✅"
        print(f"  {badge} {e['id']:30} {e['lesson'][:50]}")
    active = sum(1 for e in entries if e["status"] == "active")
    print(f"\n{len(entries)} total, {active} active")

def cmd_resolve(mistake_id: str):
    if not MISTAKES_FILE.exists():
        print(f"Not found: {mistake_id}"); sys.exit(1)
    text = MISTAKES_FILE.read_text()
    old = f"**Status:** active"
    new = f"**Status:** resolved"
    if old not in text:
        print(f"No active entry matching {mistake_id}"); sys.exit(1)
    text = text.replace(old, new)
    MISTAKES_FILE.write_text(text)
    print(f"Resolved {mistake_id}")

def main():
    parser = argparse.ArgumentParser(description="Log mistakes to mistakes.md")
    sub = parser.add_subparsers(dest="command", required=True)
    
    p_log = sub.add_parser("log", help="Log a new mistake")
    p_log.add_argument("lesson", help="What was learned")
    p_log.add_argument("root_cause", help="Why it happened")
    p_log.add_argument("--phase", default="general", help="Pipeline phase")
    p_log.add_argument("--task", default="-", help="Task ID")
    
    p_list = sub.add_parser("list", help="List recent entries")
    p_resolve = sub.add_parser("resolve", help="Mark entry as resolved")
    p_resolve.add_argument("mistake_id", help="Mistake ID to resolve")

    args = parser.parse_args()
    if args.command == "log": cmd_log(args.lesson, args.root_cause, args.phase, args.task)
    elif args.command == "list": cmd_list()
    elif args.command == "resolve": cmd_resolve(args.mistake_id)

if __name__ == "__main__":
    main()
