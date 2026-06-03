"""
intent_grader.py — eval suite 3: L1 + L2 intent reasoning correctness.

L1 (syntactic) and L2 (structural) are deterministic — Techne makes no model
call. L3 (semantic) is host-judged: there is no host in deterministic CI, so
the --l3 flag is a no-op here (the host runs L3 via build_semantic_prompt).

L1 verdict thresholds:
  score >= 0.7 → MATCH
  score >= 0.4 → PARTIAL
  score <  0.4 → MISMATCH
"""
import json
import sys
from pathlib import Path

EVALS_DIR = Path(__file__).parent.parent
HARNESS_DIR = EVALS_DIR.parent.parent / "harness"
sys.path.insert(0, str(HARNESS_DIR))

from measure import measure_intent
from diff_parser import parse_diff
from intent_reasoner import reason_about_intent


def _l1_verdict(score: float) -> str:
    if score >= 0.7:
        return "MATCH"
    elif score >= 0.4:
        return "PARTIAL"
    return "MISMATCH"


def run(verbose: bool = False, run_l3: bool = False) -> dict:
    cases_path = EVALS_DIR / "cases" / "intent_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))

    passed = 0
    failed = 0
    failures = []

    for case in cases:
        task = case["task"]
        diff = case["diff"]
        case_id = case["id"]

        # L1 check
        l1_result = measure_intent(task, diff)
        actual_l1_verdict = _l1_verdict(l1_result["score"])
        expected_l1 = case.get("expected_l1_verdict")

        l1_score_ok = True
        if "expected_l1_score_min" in case:
            l1_score_ok = l1_result["score"] >= case["expected_l1_score_min"]
        if "expected_l1_score_max" in case:
            l1_score_ok = l1_score_ok and l1_result["score"] <= case["expected_l1_score_max"]

        l1_verdict_ok = (expected_l1 is None) or (actual_l1_verdict == expected_l1)
        l1_pass = l1_verdict_ok and l1_score_ok

        if not l1_pass:
            failed += 1
            msg = (
                f"[{case_id}] L1: expected={expected_l1} got={actual_l1_verdict} "
                f"score={l1_result['score']:.2f} | {case.get('note', '')}"
            )
            failures.append(msg)
            if verbose:
                print(f"  FAIL {msg}")
            continue

        # L2 check (deterministic structural — no semantic verdict supplied)
        diff_summary = parse_diff(diff)
        l2_verdict_obj = reason_about_intent(task, diff_summary)
        actual_l2 = l2_verdict_obj.verdict
        expected_l2 = case.get("expected_l2_verdict")

        l2_pass = (expected_l2 is None) or (actual_l2 == expected_l2)

        if not l2_pass:
            failed += 1
            msg = (
                f"[{case_id}] L2: expected={expected_l2} got={actual_l2} "
                f"confidence={l2_verdict_obj.confidence:.2f} | {case.get('note', '')}"
            )
            failures.append(msg)
            if verbose:
                print(f"  FAIL {msg}")
            continue

        # L3 is host-judged — no host in deterministic CI, so --l3 is a no-op here.

        passed += 1
        if verbose:
            print(
                f"  PASS [{case_id}] L1={actual_l1_verdict}({l1_result['score']:.2f}) "
                f"L2={actual_l2} | {case.get('note', '')[:50]}"
            )

    return {
        "suite": "Intent",
        "passed": passed,
        "failed": failed,
        "total": len(cases),
        "failures": failures,
    }
