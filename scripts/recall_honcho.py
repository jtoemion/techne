#!/usr/bin/env python3
"""recall_honcho.py — Honcho context retrieval for RECALL phase.

Usage:
    python3 scripts/recall_honcho.py --topic "user preferences" --peer user
    python3 scripts/recall_honcho.py --task auth --level minimal

Outputs structured YAML-ready context block for the recaller output format:
  HONCHO_CONTEXT, WORKSHOP_CONTEXT, WORKSHOP_FILES, LESSONS, FOCUS
"""

from __future__ import annotations
import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent

def search_honcho(topic: str, peer: str = "user", level: str = "medium") -> str:
    """Run honcho_search or honcho_reasoning and return the result."""
    cmd = ["honcho", "search" if level == "minimal" else "reasoning", topic, "--peer", peer]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return result.stdout.strip()
        return f"# Honcho {cmd[1]} failed (exit {result.returncode}): {result.stderr[:200]}"
    except FileNotFoundError:
        return "# honcho CLI not found — install honcho-client or run honcho_context directly"
    except subprocess.TimeoutExpired:
        return "# Honcho search timed out"

def find_workshop_files() -> list[str]:
    """Find .techne/context files in the project root."""
    context_dir = ROOT / ".techne" / "context"
    if not context_dir.exists():
        return []
    return sorted(str(f.relative_to(ROOT)) for f in context_dir.rglob("*") if f.is_file() and f.suffix in (".md", ".txt", ".yaml", ".json"))

def check_mistakes(limit: int = 5) -> list[str]:
    """Check recent mistakes entries for relevance."""
    mistakes_file = ROOT / ".techne" / "memory" / "mistakes.md"
    if not mistakes_file.exists():
        return []
    entries = []
    with open(mistakes_file) as f:
        for line in f:
            if line.startswith("- **") and len(entries) < limit:
                entries.append(line.strip().lstrip("- ").rstrip(","))
    return entries

def main():
    parser = argparse.ArgumentParser(description="Honcho context retrieval for RECALL phase")
    parser.add_argument("--topic", default="", help="Search topic/phrase for Honcho")
    parser.add_argument("--task", default="", help="Task title (used if --topic not given)")
    parser.add_argument("--peer", default="user", help="Honcho peer to query (default: user)")
    parser.add_argument("--level", choices=["minimal", "low", "medium", "high"], default="medium",
                        help="Reasoning level (default: medium)")
    args = parser.parse_args()

    topic = args.topic or args.task or "current task"
    print(f"# RECALL — Honcho Context Retrieval")
    print(f"# Topic: {topic}")
    print()

    # Honcho search
    context = search_honcho(topic, args.peer, args.level)
    print("HONCHO_CONTEXT:", context.replace("\n", " ")[:500])
    print()

    # Workshop files
    files = find_workshop_files()
    if files:
        print("WORKSHOP_CONTEXT:", ", ".join(files))
    else:
        print("WORKSHOP_CONTEXT: none (.techne/context/ not found)")
    
    # Recent mistakes
    mistakes = check_mistakes()
    if mistakes:
        print("LESSONS:", "; ".join(mistakes))
    else:
        print("LESSONS: none")

    print("FOCUS: (fill from task requirements)")

if __name__ == "__main__":
    main()
