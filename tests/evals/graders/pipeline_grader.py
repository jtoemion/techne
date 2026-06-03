"""
pipeline_grader.py — eval suite 4: LLM-as-judge quality assessment.

Uses full_intent_check (L1→L2→L3) as the judge.
Requires ANTHROPIC_API_KEY. Skipped automatically if not set.

Verdict mapping:
  MATCH   → PASS
  PARTIAL → PARTIAL
  MISMATCH → FAIL
"""
import json
import os
import sys
from pathlib import Path

EVALS_DIR = Path(__file__).parent.parent
HARNESS_DIR = EVALS_DIR.parent.parent / "harness"
sys.path.insert(0, str(HARNESS_DIR))

from measure import full_intent_check


def _map_verdict_to_quality(verdict: str) -> str:
    if verdict == "MATCH":
        return "PASS"
    elif verdict == "PARTIAL":
        return "PARTIAL"
    return "FAIL"


def run(verbose: bool = False) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  [suite 4] SKIPPED — ANTHROPIC_API_KEY not set")
        return {
            "suite": "Pipeline E2E",
            "passed": 0,
            "failed": 0,
            "total": 0,
            "skipped": True,
            "failures": [],
        }

    cases_path = EVALS_DIR / "cases" / "pipeline_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))

    passed = 0
    failed = 0
    failures = []

    for case in cases:
        intent = full_intent_check(case["task"], case["diff"], use_llm=True)
        actual_quality = _map_verdict_to_quality(intent["verdict"])
        expected_quality = case["expected_quality"]

        if actual_quality == expected_quality:
            passed += 1
            if verbose:
                print(
                    f"  PASS [{case['id']}] {actual_quality} "
                    f"(confidence {intent['confidence']:.0%}) | {case.get('note', '')[:50]}"
                )
        else:
            failed += 1
            msg = (
                f"[{case['id']}] expected={expected_quality} got={actual_quality} "
                f"({intent['verdict']} {intent['confidence']:.0%}) | {case.get('note', '')}"
            )
            failures.append(msg)
            if verbose:
                print(f"  FAIL {msg}")

    return {
        "suite": "Pipeline E2E",
        "passed": passed,
        "failed": failed,
        "total": len(cases),
        "failures": failures,
    }
