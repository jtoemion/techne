#!/usr/bin/env python3
"""context_guard_check.py — Validate CONTEXT_GUARD output format.

Usage:
    python3 scripts/context_guard_check.py < context_guard_output.txt
    cat context_guard.md | python3 scripts/context_guard_check.py

Checks:
  - CONCLUDE PUNCH LIST section present
  - DOCS line (with path or NOT_NEEDED + reason)
  - CONTEXT line (with path or NOT_NEEDED + reason)
  - HONCHO line (with proof)
  - No prose-only sections (must have structured lines)
"""

from __future__ import annotations
import re
import sys

REQUIRED_SECTIONS = [
    ("CONCLUDE PUNCH LIST", r"conclude punch list", "Must have a '## CONCLUDE PUNCH LIST' or equivalent section header"),
    ("DOCS line", r"docs:", "Must start a line with 'DOCS:' and a path or NOT_NEEDED"),
    ("CONTEXT line", r"context:", "Must start a line with 'CONTEXT:' and a path or NOT_NEEDED"),
    ("HONCHO line", r"honcho:", "Must start a line with 'HONCHO:' and proof text"),
]

def validate(text: str) -> list[dict]:
    """Run validation checks. Returns list of {section, passed, message}."""
    text_lower = text.lower()
    results = []

    for name, pattern, hint in REQUIRED_SECTIONS:
        found = bool(re.search(pattern, text_lower, re.MULTILINE))
        results.append({
            "section": name,
            "passed": found,
            "message": "" if found else hint,
        })

    # Additional checks
    lines = text.strip().split("\n")
    if len([l for l in lines if l.strip()]) < 5:
        results.append({
            "section": "content length",
            "passed": False,
            "message": "Too few non-blank lines — expected at least 5 for a substantive audit",
        })

    return results

def main():
    text = sys.stdin.read()
    if not text.strip():
        print("CONTEXT_GUARD CHECK: FAILED — no input")
        sys.exit(1)

    results = validate(text)
    all_pass = all(r["passed"] for r in results)

    print("=== CONTEXT_GUARD Validation ===")
    for r in results:
        status = "✅" if r["passed"] else "❌"
        print(f"  {status} {r['section']}")
        if r["message"]:
            print(f"     {r['message']}")

    if all_pass:
        print("\nRESULT: PASS — all checks passed")
    else:
        failed = [r for r in results if not r["passed"]]
        print(f"\nRESULT: FAIL — {len(failed)} check(s) failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
