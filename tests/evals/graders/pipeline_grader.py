"""
pipeline_grader.py — eval suite 4: host-judged quality assessment.

Techne makes no model call. Suite 4 is HOST-JUDGED: a host supplies a judge
callable `host_judge(task, diff) -> verdict` (an IntentVerdict or a dict with a
"verdict" key of MATCH / PARTIAL / MISMATCH). The host runs the semantic check
itself via intent_reasoner.build_semantic_prompt + parse_semantic_response.

Without a host judge (e.g. deterministic CI via run_evals.py), the suite skips.

Verdict mapping:
  MATCH    -> PASS
  PARTIAL  -> PARTIAL
  MISMATCH -> FAIL
"""
import json
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


def run(verbose: bool = False, host_judge=None) -> dict:
    if host_judge is None:
        print("  [suite 4] SKIPPED - host-judged (no host judge wired)")
        return {
            "suite": "Pipeline E2E",
            "passed": 0,
            "failed": 0,
            "total": 0,
            "skipped": True,
            "skip_reason": "host-judged",
            "failures": [],
        }

    cases_path = EVALS_DIR / "cases" / "pipeline_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))

    passed = 0
    failed = 0
    failures = []

    for case in cases:
        verdict = host_judge(case["task"], case["diff"])
        intent = full_intent_check(case["task"], case["diff"], semantic_verdict=verdict)
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
