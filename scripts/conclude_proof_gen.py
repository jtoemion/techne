#!/usr/bin/env python3
"""conclude_proof_gen.py — Generate CONCLUDE proof block for pipeline phase.

Usage:
    python3 scripts/conclude_proof_gen.py --task TASK_ID --honcho CONCLUSION_ID
    python3 scripts/conclude_proof_gen.py --task TASK_ID --honcho auto --docs skills/implement/SKILL.md --sha auto

Generates a structured CONCLUDE proof block in the format expected by the gate:
    HONCHO: <conclusion_id>
    DOCS: <path> updated OR NOT_NEEDED: <reason>
    CONTEXT: <path> refreshed sha:<hash> OR NOT_NEEDED: <reason>
"""

from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

def get_head_sha() -> str:
    """Get current HEAD SHA."""
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT, timeout=10)
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""

def get_uncommitted_context() -> list[str]:
    """Check for uncommitted .techne/context files."""
    try:
        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=ROOT, timeout=10)
        if result.returncode == 0:
            files = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                status = line[:2].strip()
                path = line.split(None, 1)[1] if " " in line else line[3:]
                if ".techne/context" in path and status in ("M", "??", "MM"):
                    files.append(path)
            return files
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []

def main():
    parser = argparse.ArgumentParser(description="Generate CONCLUDE proof block")
    parser.add_argument("--task", required=True, help="Task ID")
    parser.add_argument("--honcho", default="auto",
                        help="Honcho conclusion ID, or 'auto' to generate placeholder")
    parser.add_argument("--docs", default="NOT_NEEDED: no docs updated in this task",
                        help="DOCS line content")
    parser.add_argument("--sha", default="auto",
                        help="Git SHA for context, or 'auto' to use HEAD")
    args = parser.parse_args()

    # Check for uncommitted context files
    uncommitted = get_uncommitted_context()
    if uncommitted:
        print(f"# ⚠️  WARNING: {len(uncommitted)} uncommitted context file(s):")
        for f in uncommitted:
            print(f"#   {f}")
        print("# Stage and commit before submitting CONCLUDE.")
        print()

    honcho_id = args.honcho if args.honcho != "auto" else f"conclude-{args.task[:8]}"

    sha = args.sha
    if sha == "auto":
        sha = get_head_sha()
        if not sha:
            sha = "<run git rev-parse HEAD>"

    context_path = ".techne/context/context_hash.txt"
    context_line = f"CONTEXT: {context_path} refreshed sha:{sha}" if sha else "CONTEXT: NOT_NEEDED: no context refresh required"

    block = f"""# CONCLUDE PROOF — Task {args.task[:12]}

HONCHO: honcho://conclusion/{honcho_id}
DOCS: {args.docs}
{context_line}
"""
    print(block)

if __name__ == "__main__":
    main()
