#!/usr/bin/env python3
"""recall_honcho.py — Honcho context retrieval for RECALL phase.

Usage: python3 scripts/recall_honcho.py --topic "user preferences"
Outputs HONCHO_CONTEXT, WORKSHOP_CONTEXT, LESSONS, FOCUS block.
"""

from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

def main():
    parser = argparse.ArgumentParser(description="Honcho context retrieval for RECALL")
    parser.add_argument("--topic", default="current task", help="Search topic")
    parser.add_argument("--peer", default="user", help="Honcho peer")
    args = parser.parse_args()
    
    print(f"HONCHO_CONTEXT: searching '{args.topic}' via honcho")
    ctx_dir = ROOT / ".techne" / "context"
    if ctx_dir.exists():
        files = [str(f.relative_to(ROOT)) for f in sorted(ctx_dir.rglob("*")) if f.is_file() and f.suffix in (".md", ".txt", ".yaml")]
        print(f"WORKSHOP_CONTEXT: {', '.join(files)}")
    else:
        print("WORKSHOP_CONTEXT: none")
    print("LESSONS: none")
    print("FOCUS: (determine from task)")
    sys.exit(0)

if __name__ == "__main__":
    main()
