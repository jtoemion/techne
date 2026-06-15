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
    db.close()
    rewards.close()


def test_loop_implement_retries_on_real_gate_violation(loop):
    task = loop.db.create_task("add a debug widget", discipline="implement")
    outcome = loop.submit(task.id, "IMPLEMENT", CONSOLE_LOG_DIFF)
    assert outcome.action == LoopAction.RETRY
    assert loop._gate_pass[task.id] is False
    # Did NOT advance to context-guard
    assert outcome.phase == "IMPLEMENT"


def test_loop_implement_passes_clean_diff_and_records_signals(loop):
    task = loop.db.create_task("add rate_limiter", discipline="implement")
    outcome = loop.submit(task.id, "IMPLEMENT", CLEAN_DIFF)
    assert outcome.action == LoopAction.RUN_PHASE
    assert outcome.phase == "CONTEXT_GUARD"
    assert loop._gate_pass[task.id] is True
    assert loop._scope_clean[task.id] is True


def test_loop_full_run_records_real_reward(loop):
    task = loop.db.create_task("add rate_limiter", discipline="implement")
    assert loop.submit(task.id, "IMPLEMENT", CLEAN_DIFF).action == LoopAction.RUN_PHASE
    loop.submit(task.id, "CONTEXT_GUARD", "1 file changed, in scope")
    loop.submit(task.id, "CRITIQUE", "No critical findings")
    loop.submit(task.id, "REVIEW", "REVIEW RESULT: PASS\nNo findings")
    outcome = loop.submit(task.id, "VERIFY", GOOD_TEST_OUTPUT)
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


def test_loop_verify_blocks_on_faked_test_output(loop):
    task = loop.db.create_task("add rate_limiter", discipline="implement")
    loop.submit(task.id, "IMPLEMENT", CLEAN_DIFF)
    loop.submit(task.id, "CONTEXT_GUARD", "ok")
    loop.submit(task.id, "CRITIQUE", "No critical findings")
    loop.submit(task.id, "REVIEW", "REVIEW RESULT: PASS")
    outcome = loop.submit(task.id, "VERIFY", "tests pass")  # too short / faked
    assert outcome.action == LoopAction.BLOCK_HITL
    assert loop._test_pass[task.id] is False


# ─── synthetic bootstrap seeds real signal, idempotently ─────────────────────

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
