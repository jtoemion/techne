"""
run_evals.py — Techne eval runner.

Usage:
  python tests/evals/run_evals.py                  # all suites
  python tests/evals/run_evals.py --verbose         # show each case result
  python tests/evals/run_evals.py --l3              # also run L3 LLM layer in suite 3
  python tests/evals/run_evals.py --save-baseline   # overwrite baseline
  python tests/evals/run_evals.py --suite router    # run one suite only

Exit code: 0 = all passed, 1 = failures present
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

EVALS_DIR = Path(__file__).parent
sys.path.insert(0, str(EVALS_DIR / "graders"))

from router_grader import run as run_router
from gate_grader import run as run_gates
from intent_grader import run as run_intent
from pipeline_grader import run as run_pipeline

SUITE_MAP = {
    "router": run_router,
    "gates": run_gates,
    "intent": run_intent,
    "pipeline": run_pipeline,
}

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
SKIP = "\033[93mSKIP\033[0m"


def _load_baseline() -> dict | None:
    baseline = EVALS_DIR / "results" / "baseline.json"
    if baseline.exists():
        return json.loads(baseline.read_text(encoding="utf-8"))
    return None


def _save_results(results: list[dict], is_baseline: bool = False) -> Path:
    results_dir = EVALS_DIR / "results"
    results_dir.mkdir(exist_ok=True)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    out = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "suites": results,
        "total_passed": sum(r["passed"] for r in results),
        "total_failed": sum(r["failed"] for r in results),
        "total_cases": sum(r["total"] for r in results),
    }

    path = results_dir / f"{date_str}.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    if is_baseline:
        baseline_path = results_dir / "baseline.json"
        baseline_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"\nBaseline saved -> {baseline_path}")

    return path


def _print_summary(results: list[dict], baseline: dict | None):
    print("\n" + "=" * 64)
    print("EVAL RESULTS")
    print("=" * 64)

    for r in results:
        if r.get("skipped"):
            icon = SKIP
            line = f"  {icon} {r['suite']:20} SKIPPED (no API key)"
        elif r["failed"] == 0:
            icon = PASS
            pct = 100 * r["passed"] // max(r["total"], 1)
            line = f"  {icon} {r['suite']:20} {r['passed']}/{r['total']} ({pct}%)"
        else:
            icon = FAIL
            pct = 100 * r["passed"] // max(r["total"], 1)
            line = f"  {icon} {r['suite']:20} {r['passed']}/{r['total']} ({pct}%) — {r['failed']} failed"

        print(line)

        if r.get("failures"):
            for f in r["failures"]:
                print(f"      X {f}")

    total_p = sum(r["passed"] for r in results)
    total_t = sum(r["total"] for r in results)
    total_pct = 100 * total_p // max(total_t, 1) if total_t else 0

    print(f"\nOVERALL: {total_p}/{total_t} ({total_pct}%)")

    if baseline:
        baseline_total = baseline.get("total_passed", 0)
        baseline_cases = baseline.get("total_cases", 0)
        if total_p < baseline_total:
            drop = baseline_total - total_p
            print(f"\nWARNING REGRESSION: {drop} case(s) that passed baseline now failing")
            print(f"  Baseline: {baseline_total}/{baseline_cases}")
        elif total_p > baseline_total:
            gain = total_p - baseline_total
            print(f"\nIMPROVEMENT: +{gain} case(s) vs baseline ({baseline_total}/{baseline_cases})")
        else:
            print(f"\n-> Same as baseline ({baseline_total}/{baseline_cases})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--l3", action="store_true", help="Run L3 LLM layer in intent suite")
    parser.add_argument("--save-baseline", action="store_true")
    parser.add_argument("--suite", choices=["router", "gates", "intent", "pipeline"])
    args = parser.parse_args()

    print("=" * 64)
    print("TECHNE EVALS")
    print("=" * 64)

    suites_to_run = [args.suite] if args.suite else ["router", "gates", "intent", "pipeline"]
    results = []

    for suite_name in suites_to_run:
        print(f"\n[Suite: {suite_name.upper()}]")
        fn = SUITE_MAP[suite_name]

        if suite_name == "intent":
            r = fn(verbose=args.verbose, run_l3=args.l3)
        else:
            r = fn(verbose=args.verbose)

        results.append(r)

    baseline = _load_baseline()
    _print_summary(results, baseline)

    path = _save_results(results, is_baseline=args.save_baseline)
    print(f"Results saved -> {path}")
    print("=" * 64)

    any_failed = any(r["failed"] > 0 for r in results)
    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
