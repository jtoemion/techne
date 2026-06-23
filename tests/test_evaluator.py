"""
test_evaluator.py — tests the evaluation/scoring system across multiple scenarios.

Simulates 5 different pipeline runs from perfect to catastrophic,
verifies scoring, grading, behavior analysis, recommendations,
trend detection, persistence, and report formatting.

Run from harness/:
    python test_evaluator.py
"""

import json
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(TESTS_DIR)); import _mem_guard  # noqa: snapshots memory/, restores at exit

from evaluator import (
    EvalReport,
    evaluate_pipeline_run,
    load_eval_history,
    save_eval,
    EVAL_HISTORY,
    EVAL_DIR,
    _grade,
    _trend,
)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results: list[tuple[str, bool, str]] = []


def ok(label: str):
    results.append((label, True, ""))
    print(f"  {PASS} {label}")


def fail(label: str, reason: str = ""):
    results.append((label, False, reason))
    print(f"  {FAIL} {label} -- {reason}")


# ─── Scenario 1: Perfect run ─────────────────────────────────────────────────

def test_perfect_run():
    print("\n[Scenario 1: Perfect run — zero violations, all phases pass]")

    report = evaluate_pipeline_run(
        task="Add sale badge to product page",
        pipeline_number=1,
        gate_violations=0,
        retries_used=0,
        pipeline_halted=False,
        sha_passed=True,
        hash_unique=True,
        output_existed=True,
        had_pass_indicators=True,
        skills_loaded=True,
        mistakes_consulted=True,
        diff_focused=True,
        scope_creep=False,
        review_result="PASS",
        shadow_gate_clean=True,
        drift_markers=0,
        retro_ran=True,
        retro_proposals=False,
        retro_questions=7,
    )

    if report.total == 100:
        ok(f"perfect run scores 100/100")
    else:
        fail(f"perfect run scores 100/100", f"got {report.total}")

    if report.grade == "EXCELLENT":
        ok("grade is EXCELLENT")
    else:
        fail("grade is EXCELLENT", f"got {report.grade}")

    text = report.format_report()
    if "EXCELLENT" in text and "100" in text:
        ok("report text contains EXCELLENT and 100")
    else:
        fail("report text format", text[:200])

    if "No significant gap" in report.behavior_gap:
        ok("behavior gap says no significant gap")
    else:
        fail("behavior gap", report.behavior_gap)

    if len(report.recommendations) == 0:
        ok("no recommendations for perfect run")
    else:
        fail("no recommendations for perfect run", str(report.recommendations))


# ─── Scenario 2: One retry, otherwise clean ───────────────────────────────────

def test_one_retry_run():
    print("\n[Scenario 2: One gate violation, corrected on first retry]")

    report = evaluate_pipeline_run(
        task="Fix redirect in login flow",
        pipeline_number=2,
        gate_violations=1,
        retries_used=1,
        pipeline_halted=False,
        sha_passed=True,
        hash_unique=True,
        output_existed=True,
        had_pass_indicators=True,
        skills_loaded=True,
        mistakes_consulted=True,
        diff_focused=True,
        scope_creep=False,
        review_result="PASS",
        shadow_gate_clean=True,
        drift_markers=0,
        retro_ran=True,
        retro_proposals=True,
        retro_questions=7,
    )

    gate_score = report.scores["Gate Compliance"][0]
    if gate_score == 15:
        ok(f"gate compliance: 15/20 for 1 violation + 1 retry")
    else:
        fail(f"gate compliance: 15/20", f"got {gate_score}")

    retro_score = report.scores["Retro Value"][0]
    if retro_score == 20:
        ok(f"retro value: 20/20 with proposals + 7 questions")
    else:
        fail(f"retro value: 20/20", f"got {retro_score}")

    if report.total == 95:
        ok(f"total: 95/100")
    else:
        fail(f"total: 95/100", f"got {report.total}")

    if report.grade == "EXCELLENT":
        ok("grade: EXCELLENT (95 >= 90)")
    else:
        fail("grade", f"got {report.grade}")


# ─── Scenario 3: Multiple issues, SOFT_FAIL review ────────────────────────────

def test_messy_run():
    print("\n[Scenario 3: Multiple violations, cached hash, scope creep, SOFT_FAIL review]")

    report = evaluate_pipeline_run(
        task="Refactor product components",
        pipeline_number=3,
        gate_violations=3,
        retries_used=2,
        pipeline_halted=False,
        sha_passed=True,
        hash_unique=False,  # cached output
        output_existed=True,
        had_pass_indicators=True,
        skills_loaded=True,
        mistakes_consulted=False,  # didn't check mistakes
        diff_focused=False,  # big diff
        scope_creep=True,  # touched unrelated files
        review_result="SOFT_FAIL",
        shadow_gate_clean=True,
        drift_markers=2,
        retro_ran=True,
        retro_proposals=False,
        retro_questions=7,
    )

    gate_score = report.scores["Gate Compliance"][0]
    if gate_score == 10:
        ok(f"gate compliance: 10/20 for 3 violations")
    else:
        fail(f"gate compliance: 10/20", f"got {gate_score}")

    verify_score = report.scores["Verification Integrity"][0]
    if verify_score == 15:
        ok(f"verification: 15/20 for cached hash")
    else:
        fail(f"verification: 15/20", f"got {verify_score}")

    process_score = report.scores["Process Discipline"][0]
    if process_score <= 5:
        ok(f"process discipline: {process_score}/20 (low due to scope creep + no mistakes + unfocused)")
    else:
        fail(f"process discipline should be low", f"got {process_score}")

    if report.grade in ("FAIR", "POOR"):
        ok(f"grade: {report.grade} (expected FAIR or POOR)")
    else:
        fail(f"grade should be FAIR or POOR", f"got {report.grade}")

    if len(report.recommendations) >= 2:
        ok(f"has {len(report.recommendations)} recommendations")
    else:
        fail(f"should have 2+ recommendations", str(report.recommendations))

    text = report.format_report()
    if "RECOMMENDATIONS:" in text:
        ok("report has RECOMMENDATIONS section")
    else:
        fail("report missing RECOMMENDATIONS", text[:300])


# ─── Scenario 4: Pipeline halted ─────────────────────────────────────────────

def test_halted_pipeline():
    print("\n[Scenario 4: Pipeline halted — gate violations not correctable]")

    report = evaluate_pipeline_run(
        task="Add getServerSideProps handler",
        pipeline_number=4,
        gate_violations=3,
        retries_used=3,
        max_retries=3,
        pipeline_halted=True,
        sha_passed=False,
        hash_unique=True,
        output_existed=False,
        had_pass_indicators=False,
        skills_loaded=True,
        mistakes_consulted=True,
        diff_focused=True,
        scope_creep=False,
        review_result="SKIPPED",
        shadow_gate_clean=True,
        drift_markers=0,
        retro_ran=True,
        retro_proposals=False,
        retro_questions=7,
    )

    gate_score = report.scores["Gate Compliance"][0]
    if gate_score == 0:
        ok(f"gate compliance: 0/20 (pipeline halted)")
    else:
        fail(f"gate compliance: 0/20", f"got {gate_score}")

    verify_score = report.scores["Verification Integrity"][0]
    if verify_score == 0:
        ok(f"verification: 0/20 (no output)")
    else:
        fail(f"verification: 0/20", f"got {verify_score}")

    review_score = report.scores["Review Quality"][0]
    if review_score == 0:
        ok(f"review: 0/20 (skipped)")
    else:
        fail(f"review: 0/20", f"got {review_score}")

    # gate=0 + verify=0 + process=20 + review=0 + retro=20 = 40
    if report.total == 40:
        ok(f"total: 40/100 (POOR — halted but retro+process still ran)")
    else:
        fail(f"total: 40/100", f"got {report.total}")

    if report.grade == "POOR":
        ok("grade: POOR")
    else:
        fail("grade: POOR", f"got {report.grade}")

    if len(report.recommendations) >= 2:
        ok(f"has {len(report.recommendations)} recommendations for critical run")
    else:
        fail("should have recommendations", str(report.recommendations))

    text = report.format_report()
    if "POOR" in text and "pipeline halted" in text:
        ok("report text shows POOR + halted reason")
    else:
        fail("report text", text[:300])


# ─── Scenario 5: Degrading trend detection ───────────────────────────────────

def test_trend_detection():
    print("\n[Scenario 5: Trend detection across multiple runs]")

    # Test _trend directly
    history = [
        {"total": 90},
        {"total": 88},
        {"total": 85},
        {"total": 87},
        {"total": 86},
    ]

    trend_up = _trend(history, 95)
    if trend_up == "improving":
        ok("95 vs avg ~87 = improving")
    else:
        fail("95 vs avg ~87 = improving", f"got {trend_up}")

    trend_down = _trend(history, 75)
    if trend_down == "degrading":
        ok("75 vs avg ~87 = degrading")
    else:
        fail("75 vs avg ~87 = degrading", f"got {trend_down}")

    trend_flat = _trend(history, 87)
    if trend_flat == "stable":
        ok("87 vs avg ~87 = stable")
    else:
        fail("87 vs avg ~87 = stable", f"got {trend_flat}")

    trend_new = _trend([], 90)
    if trend_new == "insufficient data":
        ok("empty history = insufficient data")
    else:
        fail("empty history = insufficient data", f"got {trend_new}")


# ─── Grade boundaries ────────────────────────────────────────────────────────

def test_grade_boundaries():
    print("\n[Grade boundaries]")

    tests = [
        (100, "EXCELLENT"), (90, "EXCELLENT"),
        (89, "GOOD"), (75, "GOOD"),
        (74, "FAIR"), (60, "FAIR"),
        (59, "POOR"), (40, "POOR"),
        (39, "CRITICAL"), (0, "CRITICAL"),
    ]
    for score, expected in tests:
        got = _grade(score)
        if got == expected:
            ok(f"score {score} -> {expected}")
        else:
            fail(f"score {score} -> {expected}", f"got {got}")


# ─── Persistence ──────────────────────────────────────────────────────────────

def test_persistence():
    print("\n[Eval persistence]")

    # Save original
    original = None
    if EVAL_HISTORY.exists():
        original = EVAL_HISTORY.read_text(encoding="utf-8")

    try:
        # Clear
        if EVAL_HISTORY.exists():
            EVAL_HISTORY.unlink()

        # Run two evals
        r1 = evaluate_pipeline_run(task="task A", pipeline_number=100, sha_passed=True, output_existed=True, had_pass_indicators=True, review_result="PASS", retro_ran=True, retro_questions=7)
        r2 = evaluate_pipeline_run(task="task B", pipeline_number=101, gate_violations=2, retries_used=2, sha_passed=True, output_existed=True, had_pass_indicators=True, review_result="SOFT_FAIL", retro_ran=True, retro_questions=7)

        history = load_eval_history()
        if len(history) == 2:
            ok("2 runs persisted to eval_history.json")
        else:
            fail("2 runs persisted", f"got {len(history)}")

        if history[0]["task"] == "task A" and history[1]["task"] == "task B":
            ok("tasks stored in order")
        else:
            fail("tasks in order", str([h["task"] for h in history]))

        if history[0]["total"] > history[1]["total"]:
            ok(f"task A ({history[0]['total']}) scored higher than task B ({history[1]['total']})")
        else:
            fail("scoring order", f"A={history[0]['total']} B={history[1]['total']}")

        # Check latest_eval.txt written
        latest = EVAL_DIR / "latest_eval.txt"
        if latest.exists() and "EVALUATION REPORT" in latest.read_text(encoding="utf-8"):
            ok("latest_eval.txt written with report text")
        else:
            fail("latest_eval.txt", "missing or empty")

    finally:
        if original:
            EVAL_HISTORY.write_text(original, encoding="utf-8")
        elif EVAL_HISTORY.exists():
            EVAL_HISTORY.unlink()
        # Clean up latest_eval.txt
        latest = EVAL_DIR / "latest_eval.txt"
        if latest.exists():
            latest.unlink()


# ─── Report format ────────────────────────────────────────────────────────────

def test_report_format():
    print("\n[Report format validation]")

    report = evaluate_pipeline_run(
        task="Format test run",
        pipeline_number=999,
        gate_violations=1,
        retries_used=1,
        sha_passed=True,
        hash_unique=True,
        output_existed=True,
        had_pass_indicators=True,
        review_result="PASS",
        shadow_gate_clean=True,
        retro_ran=True,
        retro_questions=7,
    )

    text = report.format_report()
    required_sections = [
        "EVALUATION REPORT",
        "Pipeline #999",
        "SCORES:",
        "Gate Compliance",
        "Verification Integrity",
        "Process Discipline",
        "Review Quality",
        "Retro Value",
        "TOTAL:",
        "AGENT BEHAVIOR ANALYSIS:",
        "What happened:",
        "What should be:",
        "Gap:",
        "RECOMMENDATIONS:",
        "TREND:",
    ]

    for section in required_sections:
        if section in text:
            ok(f"report contains '{section}'")
        else:
            fail(f"report missing '{section}'", text[:500])

    # Verify to_dict has all expected keys
    d = report.to_dict()
    expected_keys = ["task", "pipeline_number", "timestamp", "scores", "total", "grade", "behavior", "recommendations"]
    for key in expected_keys:
        if key in d:
            ok(f"to_dict has '{key}'")
        else:
            fail(f"to_dict missing '{key}'")

    # Clean up
    if EVAL_HISTORY.exists():
        history = load_eval_history()
        history = [h for h in history if h.get("pipeline_number") != 999]
        EVAL_HISTORY.write_text(json.dumps(history, indent=2), encoding="utf-8")
    latest = EVAL_DIR / "latest_eval.txt"
    if latest.exists():
        latest.unlink()


# ─── Run all ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 64)
    print("EVALUATOR — STRESS TEST")
    print("=" * 64)

    test_perfect_run()
    test_one_retry_run()
    test_messy_run()
    test_halted_pipeline()
    test_trend_detection()
    test_grade_boundaries()
    test_persistence()
    test_report_format()

    total = len(results)
    passed = sum(1 for _, ok_flag, _ in results if ok_flag)
    failed = total - passed

    print("\n" + "=" * 64)
    print(f"RESULTS: {passed}/{total} passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
        print("\nFailed tests:")
        for label, ok_flag, reason in results:
            if not ok_flag:
                print(f"  {FAIL} {label}: {reason}")
    else:
        print("  -- all clear")
    print("=" * 64)

    sys.exit(0 if failed == 0 else 1)
