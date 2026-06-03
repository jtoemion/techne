"""
router_grader.py — eval suite 1: skill routing correctness.
Imports harness/router.py directly. No API key, no LLM.
"""
import json
import sys
from pathlib import Path

EVALS_DIR = Path(__file__).parent.parent
HARNESS_DIR = EVALS_DIR.parent.parent / "harness"
sys.path.insert(0, str(HARNESS_DIR))

from router import route


def run(verbose: bool = False) -> dict:
    cases_path = EVALS_DIR / "cases" / "router_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))

    passed = 0
    failed = 0
    failures = []

    for case in cases:
        result = route(case["input"])
        actual = result["id"] if result else None
        expected = case["expected_skill"]

        if actual == expected:
            passed += 1
            if verbose:
                print(f"  PASS [{case['id']}] '{case['input'][:50]}' -> {actual}")
        else:
            failed += 1
            msg = f"[{case['id']}] expected={expected} got={actual} | {case['input'][:60]}"
            failures.append(msg)
            if verbose:
                print(f"  FAIL {msg}")

    return {
        "suite": "Router",
        "passed": passed,
        "failed": failed,
        "total": len(cases),
        "failures": failures,
    }
