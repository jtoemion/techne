#!/usr/bin/env python3
"""context_guard_check.py — Validate CONTEXT_GUARD output.

Reads stdin, checks for required punch list sections.
Usage: cat output.md | python3 scripts/context_guard_check.py
"""

import re, sys

REQUIRED = [
    ("CONCLUDE PUNCH LIST", r"conclude punch list"),
    ("DOCS line", r"^docs:"),
    ("CONTEXT line", r"^context:"),
    ("HONCHO line", r"^honcho:"),
]

def main():
    text = sys.stdin.read()
    if not text.strip():
        print("FAIL: no input"); sys.exit(1)
    text_lower = text.lower()
    passed = 0
    for name, pat in REQUIRED:
        ok = bool(re.search(pat, text_lower, re.MULTILINE))
        print(f"  {'OK' if ok else 'MISSING'} {name}")
        passed += ok
    if passed == len(REQUIRED):
        print("PASS")
    else:
        print(f"FAIL: {len(REQUIRED)-passed} missing"); sys.exit(1)

if __name__ == "__main__":
    main()
