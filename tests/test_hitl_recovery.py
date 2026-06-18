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

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

from task_db import TaskDB
from pipeline_enforcer import PipelineEnforcer

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []


def check(label, cond):
    results.append(bool(cond))
    print(f"  {PASS if cond else FAIL} {label}")


def _blocked_task():
    """A task driven to IMPLEMENT+CONTEXT_GUARD complete, then blocked (as a CRITIQUE
    critical would). Returns (db, enforcer, task_id)."""
    db = TaskDB(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    enf = PipelineEnforcer(db)
    t = db.create_task("fix trustedOrigins production fallback")
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
    loop.submit(t.id, "IMPLEMENT", "diff --git a/x b/x\n@@ -1 +1 @@\n+guard")
    loop.submit(t.id, "CONTEXT_GUARD", "audit clean")
    block = loop.submit(t.id, "CRITIQUE", "CRITICAL: fails open in Convex Cloud")
    check("critique blocked for HITL", block.action == LoopAction.BLOCK_HITL)
    loop.unblock(t.id, decision="Send to debugger")
    # A debugger fix submitted via DEBUG must re-enter the pipeline (not crash/stick).
    out = loop.submit(t.id, "DEBUG", "diff --git a/x b/x\n@@ -1 +2 @@\n+convex guard\n+more")
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


if __name__ == "__main__":
    print("=" * 60)
    print("HITL RECOVERY — block → debugger → re-enter")
    print("=" * 60)
    test_blocked_state_is_reachable()
    test_unblock_debugger_allows_reimplement()
    test_proceed_advances_past_the_blocked_phase()
    test_orchestrator_debug_submit_reenters()
    test_next_phase_after_unblock_is_implement()
    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed" + ("  -- all clear" if passed == total else f"  ({total-passed} FAILED)"))
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
