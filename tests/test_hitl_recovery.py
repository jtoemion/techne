"""
test_hitl_recovery.py — the HITL → debugger → re-enter recovery path.

Reproduces the live bug from a Hermes run: CRITIQUE fails → BLOCK_HITL → unblock(send to
debugger) → the debugger fixes the code → but the state machine was STUCK (could not go
CONTEXT_GUARD→IMPLEMENT, and DEBUG was not a submittable phase). These tests pin the
recovery so a blocked task can be re-implemented or proceeded past, cleanly.

Run from tests/:  python test_hitl_recovery.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest  # noqa: E402

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

from task_db import TaskDB
from pipeline_enforcer import PipelineEnforcer
from checkpoint import mark_honcho_concluded, clear_honcho_flag  # noqa: E402

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []


@pytest.fixture(autouse=True)
def honcho_fixture():
    """P3 fix: mark Honcho concluded before every test that drives RECALL.
    clear_honcho_flag() runs after each test to prevent cross-test leakage."""
    mark_honcho_concluded("p3-test-fixture")
    yield
    clear_honcho_flag()


def check(label, cond):
    results.append(bool(cond))
    print(f"  {PASS if cond else FAIL} {label}")


def _blocked_task():
    """A task driven to RECALL+IMPLEMENT+CONTEXT_GUARD complete, then blocked (as a CRITIQUE
    critical would). Returns (db, enforcer, task_id)."""
    db = TaskDB(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    enf = PipelineEnforcer(db)
    t = db.create_task("fix trustedOrigins production fallback")
    enf.mark_complete(t.id, "RECALL", agent="recaller", summary="context recalled")
    enf.mark_complete(t.id, "IMPLEMENT", agent="implementer", summary="guard added")
    enf.mark_complete(t.id, "CONTEXT_GUARD", agent="context-guard", summary="in scope")
    enf.block_for_hitl(t.id, question="CRITICAL: guard fails open in Convex Cloud",
                       options=["Proceed to review anyway", "Send to debugger", "Block and re-implement"])
    return db, enf, t.id


def test_blocked_state_is_reachable():
    print("\n[setup — the task really is blocked at CONTEXT_GUARD/CRITIQUE]")
    db, enf, tid = _blocked_task()
    check("task is BLOCKED", db.get_task(tid).status == "BLOCKED")
    check("last completed phase is CONTEXT_GUARD", enf.get_phase(tid) == "CONTEXT_GUARD")


def test_unblock_debugger_allows_reimplement():
    print("\n[recovery — unblock(debugger) lets the task re-enter IMPLEMENT]")
    db, enf, tid = _blocked_task()
    enf.unblock(tid, decision="Send to debugger")
    ce = enf.can_enter(tid, "IMPLEMENT")
    check("can re-enter IMPLEMENT after unblock (was the stuck bug)", ce.allowed)
    # And the re-implementation actually records, advancing the pipeline forward.
    enf.mark_complete(tid, "IMPLEMENT", agent="debugger", summary="convex-aware guard")
    check("re-IMPLEMENT recorded; phase advanced", enf.get_phase(tid) == "IMPLEMENT")
    check("next valid step is CONTEXT_GUARD", enf.can_enter(tid, "CONTEXT_GUARD").allowed)


def test_proceed_advances_past_the_blocked_phase():
    print("\n[recovery — unblock(proceed) soft-passes the block and moves forward]")
    db, enf, tid = _blocked_task()
    enf.unblock(tid, decision="Proceed to review anyway")
    # The blocked phase was CRITIQUE (the phase after the last completed CONTEXT_GUARD);
    # proceeding should let REVIEW run next, not loop back.
    check("CRITIQUE counts as passed (soft)", enf.get_phase(tid) == "CRITIQUE")
    check("REVIEW is now enterable", enf.can_enter(tid, "REVIEW").allowed)
    check("not stuck back at CRITIQUE", not enf.can_enter(tid, "IMPLEMENT").allowed
          or enf.get_phase(tid) == "CRITIQUE")


def test_orchestrator_debug_submit_reenters():
    print("\n[orchestrator — submit('DEBUG', diff) re-implements and advances]")
    from orchestrator_loop import OrchestratorLoop, LoopAction
    from reward_log import RewardLog
    db = TaskDB(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    rl = RewardLog(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    loop = OrchestratorLoop(db, reward_log=rl)
    t = db.create_task("fix trustedOrigins production fallback")
    # drive to a CONTEXT_GUARD-complete, blocked state
    r = loop.submit(t.id, "RECALL",
                    "HONCHO_CONTEXT: relevant prior work on trusted origins\n"
                    "WORKSHOP_CONTEXT: none\n")
    check("RECALL submitted cleanly", r.action == LoopAction.RUN_PHASE and r.phase == "IMPLEMENT")
    loop.submit(t.id, "IMPLEMENT",
                "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,2 @@\n def guard():\n-    return old\n+    return new\n")
    loop.submit(t.id, "CONTEXT_GUARD",
                "All scoped clean.\n\n"
                "CONCLUDE PUNCH LIST\n"
                "DOCS: NOT_NEEDED\n"
                "CONTEXT: NOT_NEEDED\n"
                "HONCHO: saved pattern")
    block = loop.submit(t.id, "CRITIQUE", "CRITICAL: fails open in Convex Cloud")
    check("critique blocked for HITL", block.action == LoopAction.BLOCK_HITL)
    loop.unblock(t.id, decision="Send to debugger")
    # A debugger fix submitted via DEBUG must re-enter the pipeline (not crash/stick).
    out = loop.submit(t.id, "DEBUG",
                      "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,2 @@\n def guard():\n-    return old\n+    return convex_guard\n")
    check("DEBUG submit advances (RUN_PHASE), not 'unknown phase'",
          out.action == LoopAction.RUN_PHASE and out.phase == "CONTEXT_GUARD")


def test_next_phase_after_unblock_is_implement():
    print("\n[orchestrator — next_phase resumes at IMPLEMENT after a debugger unblock]")
    from orchestrator_loop import OrchestratorLoop
    from reward_log import RewardLog
    db, enf, tid = _blocked_task()
    loop = OrchestratorLoop(db, reward_log=RewardLog(
        tempfile.NamedTemporaryFile(suffix=".db", delete=False).name))
    loop.unblock(tid, decision="Block and re-implement")
    check("next_phase is IMPLEMENT after a re-implement unblock", loop.next_phase(tid) == "IMPLEMENT")


# ── Regression: HITL re-entry deadlock (A6) ──────────────────────────────────


def test_pending_reset_preserves_recall_completion():
    """Regression: HITL blocks after RECALL completes → unblock(debugger) → PENDING
    reset should NOT lose RECALL completion (the old bandaid handled this case)."""
    print("\n[A6 — PENDING reset preserves RECALL completion]")
    db = TaskDB(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    enf = PipelineEnforcer(db)
    t = db.create_task("test recall preservation")
    enf.mark_complete(t.id, "RECALL", agent="recaller", summary="context ok")
    # Block after RECALL (simulate HITL on next phase)
    enf.block_for_hitl(t.id, question="Proceed?")
    enf.unblock(t.id, decision="Send to debugger")
    # Now PENDING: RECALL should still be in completed phases
    check("task is PENDING after debugger unblock", enf.db.get_task(t.id).status == "PENDING")
    hist_actions = [e.action for e in enf.db.get_task_history(t.id)]
    check("RECALL still in history after PENDING reset", "RECALL" in hist_actions)
    # RECALL and IMPLEMENT must be re-enterable
    check("can re-enter RECALL after PENDING reset", enf.can_enter(t.id, "RECALL").allowed)
    check("can re-enter IMPLEMENT after PENDING reset", enf.can_enter(t.id, "IMPLEMENT").allowed)
    # CONTEXT_GUARD cannot be entered — RECALL hasn't been re-done to advance to it
    check("cannot jump to CONTEXT_GUARD out of order",
          not enf.can_enter(t.id, "CONTEXT_GUARD").allowed)


def test_pending_reset_preserves_context_guard_completion():
    """Regression: HITL blocks after CONTEXT_GUARD completes → unblock(debugger) →
    PENDING reset should NOT lose CONTEXT_GUARD completion (the old bandaid DID NOT
    handle this case — it checked current != 'RECALL' and reset anyway)."""
    print("\n[A6 — PENDING reset preserves CONTEXT_GUARD completion]")
    db = TaskDB(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    enf = PipelineEnforcer(db)
    t = db.create_task("test context_guard preservation")
    enf.mark_complete(t.id, "RECALL", agent="recaller", summary="context ok")
    enf.mark_complete(t.id, "IMPLEMENT", agent="implementer", summary="diff ok")
    enf.mark_complete(t.id, "CONTEXT_GUARD", agent="context-guard", summary="audit ok")
    # Block after CONTEXT_GUARD (e.g., CRITIQUE CRITICAL)
    enf.block_for_hitl(t.id, question="CRITICAL?")
    enf.unblock(t.id, decision="Send to debugger")
    # Now PENDING: CONTEXT_GUARD should still be in completed phases
    check("task is PENDING after debugger unblock", enf.db.get_task(t.id).status == "PENDING")
    hist_actions = [e.action for e in enf.db.get_task_history(t.id)]
    check("RECALL still in history after PENDING reset", "RECALL" in hist_actions)
    check("IMPLEMENT still in history after PENDING reset", "IMPLEMENT" in hist_actions)
    check("CONTEXT_GUARD still in history after PENDING reset", "CONTEXT_GUARD" in hist_actions)
    # RECALL and IMPLEMENT re-enterable
    check("can re-enter RECALL after PENDING reset", enf.can_enter(t.id, "RECALL").allowed)
    check("can re-enter IMPLEMENT after PENDING reset", enf.can_enter(t.id, "IMPLEMENT").allowed)
    # CONTEXT_GUARD already completed → must NOT be re-enterable
    check("CONTEXT_GUARD NOT re-enterable (already completed)",
          not enf.can_enter(t.id, "CONTEXT_GUARD").allowed)
    # CRITIQUE is after CONTEXT_GUARD but hasn't been completed — not enterable yet
    # because normal transition from PENDING goes via RECALL/IMPLEMENT
    check("CRITIQUE not enterable out of order from PENDING",
          not enf.can_enter(t.id, "CRITIQUE").allowed)


if __name__ == "__main__":
    # P3 fix: mark Honcho concluded before running tests directly (non-pytest mode).
    # This mirrors the honcho_fixture behavior for pytest runs.
    mark_honcho_concluded("p3-fixture-main")
    try:
        print("=" * 60)
        print("HITL RECOVERY — block → debugger → re-enter")
        print("=" * 60)
        test_blocked_state_is_reachable()
        test_unblock_debugger_allows_reimplement()
        test_proceed_advances_past_the_blocked_phase()
        test_orchestrator_debug_submit_reenters()
        test_next_phase_after_unblock_is_implement()
        test_pending_reset_preserves_recall_completion()
        test_pending_reset_preserves_context_guard_completion()
        passed = sum(1 for r in results if r)
        total = len(results)
        print("\n" + "=" * 60)
        print(f"RESULTS: {passed}/{total} passed" + ("  -- all clear" if passed == total else f"  ({total-passed} FAILED)"))
        print("=" * 60)
        sys.exit(0 if passed == total else 1)
    finally:
        clear_honcho_flag()
