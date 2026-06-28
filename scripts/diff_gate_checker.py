#!/usr/bin/env python3
"""diff_gate_checker.py — Pre-flight diff against gate requirements before submit.

Usage:
    python3 scripts/diff_gate_checker.py < diff.txt         # check a diff
    git diff HEAD | python3 scripts/diff_gate_checker.py     # check staged diff
    python3 scripts/diff_gate_checker.py --phase implement  # phase-specific checks
"""

from __future__ import annotations
import argparse, re, sys

CHECKS: dict[str, list[dict]] = {
    "implement": [
        {"name": "has @@ markers", "test": lambda t: "@@" in t,
         "hint": "Gate rejects diffs without @@ markers. Add --unified=3 to git diff."},
        {"name": "not prose-only", "test": lambda t: bool(re.search(r"^[+-]", t, re.MULTILINE)),
         "hint": "Gate needs actual diff lines starting with +/-. Output contains only prose."},
        {"name": "has --- a/", "test": lambda t: "--- a/" in t,
         "hint": "Gate checks for '--- a/' header. Missing file prefix in git diff output."},
    ],
    "context-guard": [
        {"name": "has PUNCH LIST", "test": lambda t: "punch list" in t.lower(),
         "hint": "Must include '## CONCLUDE PUNCH LIST' section."},
        {"name": "DOCS line present", "test": lambda t: bool(re.search(r"^docs:", t, re.MULTILINE | re.IGNORECASE)),
         "hint": "Must start a line with 'DOCS:' + path or NOT_NEEDED."},
        {"name": "HONCHO line present", "test": lambda t: bool(re.search(r"^honcho:", t, re.MULTILINE | re.IGNORECASE)),
         "hint": "Must start a line with 'HONCHO:' + proof."},
    ],
    "conclude": [
        {"name": "SHA format (40-char)", "test": lambda t: bool(re.search(r"sha:[0-9a-f]{40}", t, re.IGNORECASE)),
         "hint": "SHA must be full 40-char hex with sha: prefix."},
        {"name": "HONCHO line present", "test": lambda t: bool(re.search(r"^honcho:", t, re.MULTILINE | re.IGNORECASE)),
         "hint": "Must start a line with 'HONCHO:' + conclusion ID."},
        {"name": "DOCS line present", "test": lambda t: bool(re.search(r"^docs:", t, re.MULTILINE | re.IGNORECASE)),
         "hint": "Must start a line with 'DOCS:' + path or NOT_NEEDED."},
    ],
}

def main():
    parser = argparse.ArgumentParser(description="Pre-flight diff against gate requirements")
    parser.add_argument("--phase", choices=list(CHECKS.keys()), default="implement",
                        help="Phase to check against")
    args = parser.parse_args()

    text = sys.stdin.read()
    if not text.strip():
        print("FAIL: no input")
        sys.exit(1)

    checks = CHECKS[args.phase]
    print(f"=== Diff Gate Checker — {args.phase} ===")
    print(f"Input: {len(text)} chars, {len(text.splitlines())} lines\n")

    passed = 0
    for c in checks:
        ok = c["test"](text)
        status = "PASS" if ok else "MISSING"
        print(f"  [{status:7}] {c['name']}")
        if not ok:
            print(f"           {c['hint']}")
        passed += ok

    print(f"\nResult: {passed}/{len(checks)} checks passed")
    if passed < len(checks):
        sys.exit(1)

if __name__ == "__main__":
    main()
