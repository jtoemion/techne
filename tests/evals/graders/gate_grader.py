"""
gate_grader.py — eval suite 2: gate correctness.
Tests each gate with known-good and known-bad diffs.
No API key needed — fully deterministic.
"""
import json
import sys
from pathlib import Path

EVALS_DIR = Path(__file__).parent.parent
HARNESS_DIR = EVALS_DIR.parent.parent / "harness"
sys.path.insert(0, str(HARNESS_DIR))

from gates import (
    GateViolation,
    gate_no_redirect_outside_middleware,
    gate_no_router_import,
    gate_no_gSSP,
    gate_no_ts_ignore,
    gate_no_console_log,
    run_all_gates,
)

GATE_MAP = {
    "gate_no_redirect_outside_middleware": gate_no_redirect_outside_middleware,
    "gate_no_router_import": gate_no_router_import,
    "gate_no_gSSP": gate_no_gSSP,
    "gate_no_ts_ignore": gate_no_ts_ignore,
    "gate_no_console_log": gate_no_console_log,
    "run_all_gates": run_all_gates,
}


def run(verbose: bool = False) -> dict:
    cases_path = EVALS_DIR / "cases" / "gate_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))

    passed = 0
    failed = 0
    failures = []

    for case in cases:
        gate_fn = GATE_MAP[case["gate"]]
        diff = case["diff"]
        expected_fire = case["should_fire"]

        try:
            gate_fn(diff)
            actually_fired = False
        except GateViolation:
            actually_fired = True

        if actually_fired == expected_fire:
            passed += 1
            if verbose:
                status = "fired" if actually_fired else "silent"
                print(f"  PASS [{case['id']}] {case['gate']} -> {status} (expected)")
        else:
            failed += 1
            direction = "should have fired but didn't" if expected_fire else "fired but shouldn't have"
            msg = f"[{case['id']}] {case['gate']}: {direction} | {case.get('note', '')}"
            failures.append(msg)
            if verbose:
                print(f"  FAIL {msg}")

    return {
        "suite": "Gates",
        "passed": passed,
        "failed": failed,
        "total": len(cases),
        "failures": failures,
    }
