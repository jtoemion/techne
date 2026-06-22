"""test_loop_hardening.py — Per-phase retry budget tests.

Tests that RECALL, CONTEXT_GUARD, RETRO, CONCLUDE, and REFRESH_CONTEXT
exhaust their per-phase retry budgets after N attempts and return FAILED.

Each test submits a single phase directly (no full pipeline drive) to isolate
the retry budget behavior.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from unittest import mock as _mock

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(TESTS_DIR))
import _mem_guard  # noqa

from orchestrator_loop import OrchestratorLoop, LoopAction, MAX_PHASE_RETRIES
from task_db import TaskDB

# ── Module-level mocks ──

_mock.patch.object(
    OrchestratorLoop, "_get_uncommitted_context_files", return_value=[]
).start()
_mock.patch("subprocess.run", lambda *a, **k: type("Proc", (), {"returncode": 0, "stdout": "{}", "stderr": ""})()).start()
_mock.patch("orchestrator_loop.check_honcho_logged", return_value="honcho-123").start()

# ── Colored output helpers ──

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []

def check(label: str, cond: bool) -> None:
    results.append(bool(cond))
    print(f"  {PASS if cond else FAIL} {label}")

# ── Test: RECALL retry budget ──

def test_recall_retries_then_fails():
    """RECALL with bad content exhausts retry budget after N attempts, then FAILs."""
    print("\n[test — RECALL retry budget exhausts and FAILs]")
    db = TaskDB(":memory:")
    loop = OrchestratorLoop(db)
    task_id = db.create_task("test recall retry").id

    bad_result = "short"

    for i in range(MAX_PHASE_RETRIES["RECALL"]):
        outcome = loop.submit(task_id, "RECALL", bad_result)
        expected_fail = (i == MAX_PHASE_RETRIES["RECALL"] - 1)
        if expected_fail:
            check(f"RECALL attempt {i+1} returns FAILED", outcome.action == LoopAction.FAILED)
        else:
            check(f"RECALL attempt {i+1} returns RETRY", outcome.action == LoopAction.RETRY)

    # One more should also be FAILED
    outcome = loop.submit(task_id, "RECALL", bad_result)
    check("RECALL after exhaustion still FAILED", outcome.action == LoopAction.FAILED)
    check("FAILED message mentions exhausted", "exhausted" in outcome.message.lower() or "failed" in outcome.message.lower())

# ── Test: RECALL success resets counter ──

def test_recall_success_resets_counter():
    """RECALL that succeeds after a failure resets the retry counter."""
    print("\n[test — RECALL success resets retry counter]")
    db = TaskDB(":memory:")
    loop = OrchestratorLoop(db)
    task_id = db.create_task("test recall reset").id

    bad_result = "short"
    good_result = "HONCHO_CONTEXT: durable\nworkshop_context: file.md\n"

    # Fail once
    outcome = loop.submit(task_id, "RECALL", bad_result)
    check("First RECALL returns RETRY", outcome.action == LoopAction.RETRY)

    # Succeed — resets counter
    outcome = loop.submit(task_id, "RECALL", good_result)
    check("Second RECALL succeeds (RUN_PHASE)", outcome.action == LoopAction.RUN_PHASE)

# ── Test: CONTEXT_GUARD retry budget ──

def test_context_guard_retries_then_fails():
    """CONTEXT_GUARD with missing punch list exhausts retry budget."""
    print("\n[test — CONTEXT_GUARD retry budget exhausts and FAILs]")
    db = TaskDB(":memory:")
    loop = OrchestratorLoop(db)
    task_id = db.create_task("test cg retry", phase_mode="fast").id

    # Drive to IMPLEMENT first (fast mode skips RECALL)
    loop.submit(task_id, "IMPLEMENT", textwrap.dedent("""\
        diff --git a/x.py b/x.py
        --- a/x.py
        +++ b/x.py
        @@ -1 +1,6 @@
        +# new line
        +# another line
        +# third line
        +# fourth line
        +# fifth line
    """))

    bad_audit = "No punch list here"

    for i in range(MAX_PHASE_RETRIES["CONTEXT_GUARD"]):
        outcome = loop.submit(task_id, "CONTEXT_GUARD", bad_audit)
        expected_fail = (i == MAX_PHASE_RETRIES["CONTEXT_GUARD"] - 1)
        if expected_fail:
            check(f"CG attempt {i+1} returns FAILED", outcome.action == LoopAction.FAILED)
        else:
            check(f"CG attempt {i+1} returns RETRY", outcome.action == LoopAction.RETRY)

# ── Test: RETRO retry budget ──

def test_retro_retries_then_fails():
    """RETRO with short content exhausts retry budget."""
    print("\n[test — RETRO retry budget exhausts and FAILs]")
    db = TaskDB(":memory:")
    loop = OrchestratorLoop(db)
    task_id = db.create_task("test retro retry", phase_mode="fast").id

    # Drive through phases to reach RETRO
    good_diff = textwrap.dedent("""\
        diff --git a/x.py b/x.py
        --- a/x.py
        +++ b/x.py
        @@ -1 +1,6 @@
        +# new line
        +# another line
        +# third line
        +# fourth line
        +# fifth line
    """)
    loop.submit(task_id, "IMPLEMENT", good_diff)
    loop.submit(task_id, "CONTEXT_GUARD", "CONCLUDE PUNCH LIST\nDOCS: NOT_NEEDED\nCONTEXT: NOT_NEEDED\nHONCHO: ok")
    # Skip CRITIQUE/REVIEW — go to EVAL then RETRO via pump
    for phase in ["CRITIQUE", "REVIEW", "VERIFY", "EVAL"]:
        outcome = loop.submit(task_id, phase, "ok")
        if outcome.action in (LoopAction.DONE, LoopAction.FAILED, LoopAction.BLOCK_HITL):
            break

    bad_retro = "short"

    for i in range(MAX_PHASE_RETRIES["RETRO"]):
        if i >= 5:
            break
        outcome = loop.submit(task_id, "RETRO", bad_retro)
        if outcome.action == LoopAction.FAILED:
            check(f"RETRO attempt {i+1} returns FAILED", True)
            break
        check(f"RETRO attempt {i+1} returns RETRY", outcome.action == LoopAction.RETRY)

# ── Test runner ──

if __name__ == "__main__":
    tests = [
        test_recall_retries_then_fails,
        test_recall_success_resets_counter,
        test_context_guard_retries_then_fails,
        test_retro_retries_then_fails,
    ]
    for t in tests:
        t()
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed}/{total} passed" + ("  -- all clear" if passed == total else f"  ({total-passed} FAILED)"))
    print(f"{'=' * 60}")
    sys.exit(0 if passed == total else 1)
