"""
test_enforcement.py — the shared deterministic enforcement core and its
integration into the RL orchestrator loop.

These tests pin the merge between conductor and orchestrator_loop: both drivers
now run the SAME gates / scope measurement / SHA verification, and the loop's
reward signal reflects real enforcement instead of hardcoded True.
"""
import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent.parent / "harness"
sys.path.insert(0, str(HARNESS))

from enforcement import (  # noqa: E402
    build_registry, run_gates, measure_scope, verify_tests,
    GateResult, ScopeResult, VerifyResult,
)
from task_db import TaskDB  # noqa: E402
from reward_log import RewardLog  # noqa: E402
from orchestrator_loop import OrchestratorLoop, LoopAction  # noqa: E402
from synthetic_bootstrap import SyntheticBootstrap  # noqa: E402
from checkpoint import mark_honcho_concluded, clear_honcho_flag  # noqa: E402


CLEAN_DIFF = (
    "--- a/rate_limiter.py\n+++ b/rate_limiter.py\n@@ -1 +1,3 @@\n"
    "-old\n+def rate_limiter(rate):\n+    return rate\n"
)
CONSOLE_LOG_DIFF = (
    "--- a/widget.py\n+++ b/widget.py\n@@ -1 +1,2 @@\n"
    "-old\n+console.log('debugging the rate limiter')\n"
)
GOOD_TEST_OUTPUT = (
    "============================= test session starts ===========================\n"
    "collected 12 items\n\n"
    "tests/test_rate_limiter.py ............                                [100%]\n\n"
    "============================== 12 passed in 0.04s ===========================\n"
)


# ─── run_gates ───────────────────────────────────────────────────────────────

def test_run_gates_passes_clean_diff():
    result = run_gates(CLEAN_DIFF)
    assert isinstance(result, GateResult)
    assert result.passed is True
    assert result.gate_name == ""


def test_run_gates_fails_console_log_and_names_gate():
    result = run_gates(CONSOLE_LOG_DIFF)
    assert result.passed is False
    assert result.gate_name == "general/console-log"
    assert "console.log" in result.violation


def test_run_gates_never_raises_on_violation():
    # A direct registry.run_all would raise; run_gates must not.
    run_gates(CONSOLE_LOG_DIFF)  # no exception == pass


# ─── measure_scope ───────────────────────────────────────────────────────────

def test_measure_scope_clean_for_focused_relevant_diff():
    result = measure_scope("add rate_limiter", CLEAN_DIFF)
    assert isinstance(result, ScopeResult)
    assert result.diff_focused is True
    assert result.scope_creep is False
    assert result.intent_mismatch is False
    assert result.scope_clean is True


def test_measure_scope_flags_creep_for_unrelated_files():
    # Task mentions auth; the diff touches a totally unrelated file.
    unrelated = (
        "--- a/payments/invoice.py\n+++ b/payments/invoice.py\n@@ -1 +1,2 @@\n"
        "-old\n+def total(): return 1\n"
    )
    result = measure_scope("add login authentication flow", unrelated)
    assert result.scope_creep is True
    assert result.scope_clean is False


def test_scope_clean_property_composition():
    assert ScopeResult(diff_focused=True, scope_creep=False, intent_mismatch=False).scope_clean
    assert not ScopeResult(diff_focused=False, scope_creep=False).scope_clean
    assert not ScopeResult(diff_focused=True, scope_creep=True).scope_clean
    assert not ScopeResult(diff_focused=True, scope_creep=False, intent_mismatch=True).scope_clean


# ─── verify_tests ────────────────────────────────────────────────────────────

def test_verify_tests_passes_real_output(tmp_path):
    result = verify_tests(GOOD_TEST_OUTPUT, memory_dir=tmp_path)
    assert isinstance(result, VerifyResult)
    assert result.passed is True
    assert len(result.sha) == 64  # sha-256 hex


def test_verify_tests_rejects_too_short_output(tmp_path):
    result = verify_tests("ok", memory_dir=tmp_path)
    assert result.passed is False
    assert "SHA GATE FAIL" in result.error


def test_verify_tests_rejects_failure_output(tmp_path):
    bad = "running tests...\n" + "x" * 60 + "\n 1 failed in 0.1s\n"
    result = verify_tests(bad, memory_dir=tmp_path)
    assert result.passed is False


# ─── loop integration: real signals reach the reward log ─────────────────────

@pytest.fixture
def loop(tmp_path):
    db = TaskDB(str(tmp_path / "tasks.db"))
    rewards = RewardLog(str(tmp_path / "rewards.db"))
    lp = OrchestratorLoop(db, reward_log=rewards)
    yield lp
    lp.db.close()
    lp.reward_log.close()


@pytest.fixture(autouse=True)
def honcho_fixture():
    """P3 fix: mark Honcho concluded before every test that drives RECALL.
    clear_honcho_flag() runs after each test to prevent cross-test leakage.

    Also reset .techne/context to a clean state so the CONCLUDE gate
    (which blocks on uncommitted context changes) passes in full-pipeline tests."""
    mark_honcho_concluded("p3-test-fixture")
    # Reset .techne/context to HEAD so CONCLUDE's uncommitted-changes gate clears
    import subprocess
    repo_root = Path(__file__).resolve().parent.parent
    try:
        subprocess.run(
            ["git", "checkout", "HEAD", "--", ".techne/context/"],
            capture_output=True, check=False, cwd=str(repo_root),
        )
    except Exception:
        pass  # git not available or no repo — best-effort
    yield
    clear_honcho_flag()


def test_loop_implement_retries_on_real_gate_violation(loop):
    task = loop.db.create_task("add a debug widget", discipline="implement")
    loop.submit(task.id, "RECALL",
                "HONCHO_CONTEXT: prior work\nWORKSHOP_CONTEXT: workshop retrieval packet")
    outcome = loop.submit(task.id, "IMPLEMENT", CONSOLE_LOG_DIFF)
    assert outcome.action == LoopAction.RETRY
    assert loop._gate_pass.get(task.id) is False
    # Did NOT advance to context-guard
    assert outcome.phase == "IMPLEMENT"


def test_loop_implement_passes_clean_diff_and_records_signals(loop):
    task = loop.db.create_task("add rate_limiter", discipline="implement")
    loop.submit(task.id, "RECALL",
                "HONCHO_CONTEXT: prior work\nWORKSHOP_CONTEXT: workshop retrieval packet")
    outcome = loop.submit(task.id, "IMPLEMENT", CLEAN_DIFF)
    assert outcome.action == LoopAction.RUN_PHASE
    assert outcome.phase == "CONTEXT_GUARD"
    assert loop._gate_pass.get(task.id) is True
    assert loop._scope_clean.get(task.id) is True


def test_loop_full_run_records_real_reward(loop):
    task = loop.db.create_task("add rate_limiter", discipline="implement")
    loop.submit(task.id, "RECALL",
                "HONCHO_CONTEXT: prior work\nWORKSHOP_CONTEXT: workshop retrieval packet")
    assert loop.submit(task.id, "IMPLEMENT", CLEAN_DIFF).action == LoopAction.RUN_PHASE
    loop.submit(task.id, "CONTEXT_GUARD",
                "All scoped clean.\n\n"
                "CONCLUDE PUNCH LIST\n"
                "DOCS: NOT_NEEDED\n"
                "CONTEXT: NOT_NEEDED\n"
                "HONCHO: saved pattern")
    loop.submit(task.id, "CRITIQUE", "No critical findings")
    loop.submit(task.id, "REVIEW", "REVIEW RESULT: PASS\nNo findings")
    assert loop.submit(task.id, "VERIFY", GOOD_TEST_OUTPUT).action == LoopAction.RUN_PHASE
    loop.submit(task.id, "EVAL", "")      # deterministic score
    # RETRO needs ≥ 100 chars and must reference completed phases
    retro_outcome = loop.submit(task.id, "RETRO",
        "retro: clean run completed successfully. All phases passed as expected. "
        "The implementation was focused, tests passed, and no scope creep was detected. "
        "This is a reference example of a correct pipeline execution. "
        "IMPLEMENT passed, VERIFY passed, REVIEW passed, and CONTEXT_GUARD cleared.")
    assert retro_outcome.action == LoopAction.RUN_PHASE, f"RETRO should advance, got {retro_outcome.action}"
    assert retro_outcome.phase == "CONCLUDE"

    # CONCLUDE: close the punch list (DOCS + CONTEXT both NOT_NEEDED for a focused task)
    conclude_outcome = loop.submit(task.id, "CONCLUDE",
        "HONCHO: conclusion recorded — task completed cleanly.\n"
        "DOCS: NOT_NEEDED: no documentation was generated for this focused change.\n"
        "CONTEXT: NOT_NEEDED: no context artifacts needed for this implementation.")
    assert conclude_outcome.action == LoopAction.RUN_PHASE, f"CONCLUDE should advance, got {conclude_outcome.action}"
    assert conclude_outcome.phase == "REFRESH_CONTEXT"

    # REFRESH_CONTEXT: the script will find no touched files, so it succeeds with no-op
    outcome = loop.submit(task.id, "REFRESH_CONTEXT", "")
    assert outcome.action == LoopAction.DONE
    # The reward was recorded from real signals, not hardcoded True.
    rows = loop.reward_log._conn.execute(
        "SELECT gate_pass, test_pass, scope_clean FROM rewards WHERE task_id = ?",
        (task.id,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["gate_pass"] == 1
    assert rows[0]["test_pass"] == 1
    assert rows[0]["scope_clean"] == 1


def test_loop_records_loss_on_escalation(loop):
    """A task that exhausts retries must train the loop too, not just wins."""
    task = loop.db.create_task("add a debug widget", discipline="implement")
    loop.submit(task.id, "RECALL",
                "HONCHO_CONTEXT: prior work\nWORKSHOP_CONTEXT: workshop retrieval packet")
    outcome = None
    for _ in range(5):  # MAX_TOTAL_RETRIES gate failures -> escalate
        outcome = loop.submit(task.id, "IMPLEMENT", CONSOLE_LOG_DIFF)
    assert outcome.action == LoopAction.BLOCK_HITL  # escalated to debugger
    rows = loop.reward_log._conn.execute(
        "SELECT gate_pass, test_pass FROM rewards WHERE task_id = ?",
        (task.id,),
    ).fetchall()
    assert len(rows) == 1               # one loss recorded at escalation, not per-retry
    assert rows[0]["gate_pass"] == 0    # real failure signal
    assert rows[0]["test_pass"] == 0    # never reached verify


def test_loop_verify_blocks_on_faked_test_output(loop):
    task = loop.db.create_task("add rate_limiter", discipline="implement")
    loop.submit(task.id, "RECALL",
                "HONCHO_CONTEXT: prior work\nWORKSHOP_CONTEXT: workshop retrieval packet")
    loop.submit(task.id, "IMPLEMENT", CLEAN_DIFF)
    loop.submit(task.id, "CONTEXT_GUARD", "All scoped clean.\n\n"
                "CONCLUDE PUNCH LIST\n"
                "DOCS: NOT_NEEDED\n"
                "CONTEXT: NOT_NEEDED\n"
                "HONCHO: saved pattern")
    loop.submit(task.id, "CRITIQUE", "No critical findings")
    loop.submit(task.id, "REVIEW", "REVIEW RESULT: PASS")
    outcome = loop.submit(task.id, "VERIFY", "tests pass")  # too short / faked
    assert outcome.action == LoopAction.BLOCK_HITL
    assert loop._test_pass.get(task.id) is False


def test_loop_does_not_record_reward_on_in_budget_retry(loop):
    """Retries within budget are not terminal — no reward until DONE or escalation."""
    task = loop.db.create_task("add a debug widget", discipline="implement")
    loop.submit(task.id, "RECALL",
                "HONCHO_CONTEXT: prior work\nWORKSHOP_CONTEXT: workshop retrieval packet")
    outcome = loop.submit(task.id, "IMPLEMENT", CONSOLE_LOG_DIFF)
    assert outcome.action == LoopAction.RETRY
    count = loop.reward_log._conn.execute(
        "SELECT COUNT(*) FROM rewards WHERE task_id = ?", (task.id,)
    ).fetchone()[0]
    assert count == 0


# ─── synthetic bootstrap seeds real signal, idempotently ─────────────────────

def test_composite_score_stays_within_unit_interval():
    from reward_log import _composite_score
    # Degenerate attempt_count=0 must not push the composite above 1.0.
    best = _composite_score(
        gate_pass=True, test_pass=True, review_findings=[],
        critique_accuracy=1.0, scope_clean=True, attempt_count=0,
    )
    worst = _composite_score(
        gate_pass=False, test_pass=False, review_findings=["a", "b", "c", "d", "e", "f"],
        critique_accuracy=0.0, scope_clean=False, attempt_count=9,
    )
    assert 0.0 <= worst <= best <= 1.0


def test_reward_log_has_task(tmp_path):
    log = RewardLog(str(tmp_path / "r.db"))
    assert log.has_task("nope") is False
    log.record(
        task_id="seen", task_type="auth", prompt_variant="v1",
        gate_pass=True, test_pass=True, review_findings=[],
        critique_predictions=[], scope_clean=True, attempt_count=1,
    )
    assert log.has_task("seen") is True
    log.close()


def test_synthetic_bootstrap_is_idempotent(tmp_path):
    log = RewardLog(str(tmp_path / "r.db"))
    first = SyntheticBootstrap(log).run()
    assert first["tasks_scored"] > 0
    assert first["tasks_skipped"] == 0
    # Re-running must seed nothing new (no duplicate rows).
    second = SyntheticBootstrap(log).run()
    assert second["tasks_scored"] == 0
    assert second["tasks_skipped"] == first["tasks_scored"]
    total = log._conn.execute("SELECT COUNT(*) FROM rewards").fetchone()[0]
    assert total == first["tasks_scored"]
    log.close()


# ─── Honcho gate ─────────────────────────────────────────────────────────────

def test_recall_rejects_missing_honcho_conclusion(tmp_path):
    """P3 negative test: RECALL must be rejected when no Honcho was logged.
    This proves check_honcho_logged() correctly blocks the gate."""
    clear_honcho_flag()  # ensure no prior Honcho flag
    db = TaskDB(str(tmp_path / "tasks.db"))
    rewards = RewardLog(str(tmp_path / "rewards.db"))
    loop = OrchestratorLoop(db, reward_log=rewards)

    task = loop.db.create_task("test task", discipline="implement")
    # Submit RECALL with sufficient text but NO prior call to mark_honcho_concluded()
    outcome = loop.submit(
        task.id,
        "RECALL",
        "HONCHO_CONTEXT: some prior work\nWORKSHOP_CONTEXT: workshop retrieval packet",
    )

    # The gate MUST reject: missing Honcho proof → RETRY
    assert outcome.action == LoopAction.RETRY, (
        f"Expected RETRY when no Honcho was logged, got {outcome.action}. "
        "check_honcho_logged() is not enforcing the gate."
    )
    assert outcome.phase == "RECALL"
    assert "HONCHO_CONTEXT" in outcome.message

    db.close()
    rewards.close()


def test_recall_accepts_when_honcho_was_logged(tmp_path):
    """P3 positive complement: RECALL passes when mark_honcho_concluded() was called."""
    mark_honcho_concluded("p3-negative-test-positive-side")
    db = TaskDB(str(tmp_path / "tasks.db"))
    rewards = RewardLog(str(tmp_path / "rewards.db"))
    loop = OrchestratorLoop(db, reward_log=rewards)

    task = loop.db.create_task("test task", discipline="implement")
    outcome = loop.submit(
        task.id,
        "RECALL",
        "HONCHO_CONTEXT: some prior work\nWORKSHOP_CONTEXT: workshop retrieval packet",
    )

    assert outcome.action == LoopAction.RUN_PHASE, (
        f"Expected RUN_PHASE when Honcho was logged, got {outcome.action}. "
        "The Honcho gate is too strict."
    )
    assert outcome.phase == "IMPLEMENT"

    db.close()
    rewards.close()
    clear_honcho_flag()


if __name__ == "__main__":
    import pytest as _pt
    raise SystemExit(_pt.main([__file__, "-q"]))
