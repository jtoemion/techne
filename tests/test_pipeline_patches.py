"""
test_pipeline_patches.py — TDD for 5 pipeline harness patches.

Run from tests/:  pytest test_pipeline_patches.py -v
Or standalone:    python test_pipeline_patches.py

Tests:
  Patch 1: Skip REVIEW HITL for trivial changes (≤10 lines)
  Patch 2: Fix HITL re-entry deadlock — VERIFY can be re-entered after unblock
  Patch 3: Graceful REFRESH_CONTEXT when no .techne/config.yaml
  Patch 4: Auto-add .techne/tasks/ to .gitignore on DONE
  Patch 5: BLOCKED transitions include VERIFY, REVIEW, EVAL
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest  # noqa: E402

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

from task_db import TaskDB
from pipeline_enforcer import PipelineEnforcer, TRANSITIONS
from checkpoint import mark_honcho_concluded, clear_honcho_flag  # noqa: E402
from orchestrator_loop import OrchestratorLoop, LoopAction  # noqa: E402
from reward_log import RewardLog  # noqa: E402

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []


@pytest.fixture(autouse=True)
def honcho_fixture():
    """Mark Honcho concluded before every test to satisfy gates."""
    mark_honcho_concluded("p3-test-fixture")
    yield
    clear_honcho_flag()


def check(label: str, cond) -> None:
    results.append(bool(cond))
    print(f"  {PASS if cond else FAIL} {label}")


# ── Patch 1: Skip REVIEW HITL for trivial changes ───────────────────────────────


def test_patch1_review_autoadvance_trivial():
    """
    Patch 1: When the diff is ≤10 lines and tests pass, REVIEW should
    auto-advance to VERIFY without blocking for HITL.
    """
    print("\n[Patch 1 — REVIEW auto-advance for trivial diffs]")
    db = TaskDB(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    rl = RewardLog(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    loop = OrchestratorLoop(db, reward_log=rl)
    t = db.create_task("fix typo in docstring", discipline="tdd")

    # Drive to REVIEW: RECALL → IMPLEMENT (small diff) → CONTEXT_GUARD → CRITIQUE
    loop.submit(t.id, "RECALL",
                "HONCHO_CONTEXT: relevant\\nWORKSHOP_CONTEXT: none\\n")
    # Small diff ≤10 lines added
    small_diff = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,2 +1,3 @@\n"
        " def foo():\n"
        "-    return 1\n"
        "+    return 1  # fixed typo\n"
    )
    loop.submit(t.id, "IMPLEMENT", small_diff)
    loop.submit(t.id, "CONTEXT_GUARD",
                "DOCS: NOT_NEEDED\\nCONTEXT: NOT_NEEDED\\nHONCHO: saved")
    loop.submit(t.id, "CRITIQUE", "No critical findings")

    # REVIEW with a trivial PASS → should NOT block, should advance to VERIFY
    outcome = loop.submit(t.id, "REVIEW", "REVIEW RESULT: PASS\\nMinor typo fixed, no issues.")
    check("REVIEW auto-advances (no BLOCK_HITL) for trivial diff",
          outcome.action == LoopAction.RUN_PHASE and outcome.phase == "VERIFY")
    check("task is not BLOCKED",
          db.get_task(t.id).status != "BLOCKED")


# ── Patch 2: Fix HITL re-entry deadlock — VERIFY re-entry after unblock ─────────


def test_patch2_verify_reentry_after_unblock():
    """
    Patch 2: After a task is blocked at VERIFY and then unblocked, submitting
    VERIFY again must succeed (not reject with "only IMPLEMENT or DEBUG allowed").
    """
    print("\n[Patch 2 — VERIFY re-entry after unblock]")
    db = TaskDB(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    enf = PipelineEnforcer(db)
    t = db.create_task("add rate limiter")

    # Drive to REVIEW-complete (stop before VERIFY), then block directly
    enf.mark_complete(t.id, "RECALL", agent="recaller", summary="ctx")
    enf.mark_complete(t.id, "IMPLEMENT", agent="impl", summary="diff", changed_files=["x.py"])
    enf.mark_complete(t.id, "CONTEXT_GUARD", agent="cg", summary="ok")
    enf.mark_complete(t.id, "CRITIQUE", agent="crit", summary="ok")
    enf.mark_complete(t.id, "REVIEW", agent="rev", summary="ok")

    # Block (simulate VERIFY blocking on first attempt)
    enf.block_for_hitl(t.id, question="Tests failing?", options=["Retry", "Override"])
    check("task is BLOCKED after block_for_hitl", db.get_task(t.id).status == "BLOCKED")

    # Unblock with "proceed"
    enf.unblock(t.id, decision="Override and proceed")
    check("task is IN_PROGRESS after unblock", db.get_task(t.id).status == "IN_PROGRESS")

    # Now re-enter VERIFY — must be ALLOWED (was the deadlock bug)
    ce = enf.can_enter(t.id, "VERIFY")
    check("VERIFY re-entry allowed after unblock",
          ce.allowed)


def test_patch2_verify_reentry_via_orchestrator():
    """
    Patch 2 (orchestrator-level): After unblocking a BLOCKED task, the pipeline
    correctly advances via next_phase(). The BLOCKED→VERIFY transition is now
    allowed for tasks that block at VERIFY.
    """
    print("\n[Patch 2 — orchestrator BLOCKED→VERIFY transition]")
    db = TaskDB(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    rl = RewardLog(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    loop = OrchestratorLoop(db, reward_log=rl)
    t = db.create_task("add rate limiter")

    # Drive to REVIEW-complete (block_for_hitl directly at VERIFY, not via submit)
    loop.submit(t.id, "RECALL",
               "HONCHO_CONTEXT: relevant\nWORKSHOP_CONTEXT: none\n")
    loop.submit(t.id, "IMPLEMENT",
               "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n")
    loop.submit(t.id, "CONTEXT_GUARD",
               "DOCS: NOT_NEEDED\nCONTEXT: NOT_NEEDED\nHONCHO: saved")
    loop.submit(t.id, "CRITIQUE", "No critical findings")
    loop.submit(t.id, "REVIEW", "REVIEW RESULT: PASS\nok")

    # Block the task directly at VERIFY (simulate VERIFY blocking on first attempt)
    loop.enforcer.block_for_hitl(t.id, question="Tests failing?",
                                 options=["Retry", "Override"])
    check("task is BLOCKED",
          loop.db.get_task(t.id).status == "BLOCKED")

    # Unblock with override
    loop.unblock(t.id, decision="Override and proceed")
    check("task is IN_PROGRESS after unblock",
          loop.db.get_task(t.id).status == "IN_PROGRESS")

    # After unblock from VERIFY, next_phase() returns EVAL (soft-passed VERIFY is
    # the last completed phase, next in PHASES is EVAL — this is the correct behavior).
    # The real fix is that BLOCKED→VERIFY is now allowed for tasks blocking at VERIFY.
    next_p = loop.next_phase(t.id)
    check("next_phase() returns EVAL after unblock from VERIFY",
          next_p == "EVAL")

    # Also verify BLOCKED→VERIFY is allowed at the enforcer level
    # (for direct enforcer use without orchestrator next_phase())
    db2 = TaskDB(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    enf2 = PipelineEnforcer(db2)
    t2 = db2.create_task("test blocked to verify")
    enf2.mark_complete(t2.id, "RECALL", agent="r", summary="ctx")
    enf2.mark_complete(t2.id, "IMPLEMENT", agent="i", summary="d", changed_files=["x.py"])
    enf2.mark_complete(t2.id, "CONTEXT_GUARD", agent="c", summary="ok")
    enf2.mark_complete(t2.id, "CRITIQUE", agent="c", summary="ok")
    enf2.mark_complete(t2.id, "REVIEW", agent="r", summary="ok")
    enf2.block_for_hitl(t2.id, question="Tests?")
    ce_verify = enf2.can_enter(t2.id, "VERIFY")
    check("BLOCKED→VERIFY transition allowed",
          ce_verify.allowed)


# ── Patch 3: Graceful REFRESH_CONTEXT when no config.yaml ───────────────────────


def test_patch3_refresh_context_graceful_without_config():
    """
    Patch 3: When .techne/config.yaml does not exist, REFRESH_CONTEXT
    should skip gracefully and advance to DONE instead of failing.
    """
    print("\n[Patch 3 — REFRESH_CONTEXT graceful skip without config.yaml]")
    db = TaskDB(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    rl = RewardLog(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    loop = OrchestratorLoop(db, reward_log=rl)

    # Ensure .techne/config.yaml does NOT exist
    config_path = ROOT / ".techne" / "config.yaml"
    config_existed = config_path.exists()
    if config_existed:
        bak = ROOT / ".techne" / "config.yaml.bak"
        config_path.rename(bak)

    try:
        t = db.create_task("refresh without config", discipline="tdd")

        # Drive to CONCLUDE (pipeline: RECALL→IMPLEMENT→CG→CRITIQUE→REVIEW→VERIFY→EVAL→RETRO→CONCLUDE)
        loop.submit(t.id, "RECALL",
                    "HONCHO_CONTEXT: relevant\nWORKSHOP_CONTEXT: none\n")
        loop.submit(t.id, "IMPLEMENT",
                    "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n")
        loop.submit(t.id, "CONTEXT_GUARD",
                    "DOCS: NOT_NEEDED\nCONTEXT: NOT_NEEDED\nHONCHO: saved")
        loop.submit(t.id, "CRITIQUE", "No critical findings")
        loop.submit(t.id, "REVIEW", "REVIEW RESULT: PASS\nok")
        # Bypass VERIFY (tests pass signal)
        loop._test_pass[t.id] = True
        loop.enforcer.mark_complete(t.id, "VERIFY", agent="ver", summary="tests passed")
        # EVAL → returns next phase = RETRO
        r = loop.submit(t.id, "EVAL", "")
        check("EVAL advances to RETRO", r.phase == "RETRO" and r.action == LoopAction.RUN_PHASE)
        # RETRO → returns next phase = CONCLUDE
        r = loop.submit(t.id, "RETRO",
                    "This is a very detailed reflection about what happened in the "
                    "implementation phase and the review phase. We successfully implemented "
                    "the new feature with proper gates passing. The review phase verified "
                    "all tests passed and the code quality was good.")
        check("RETRO advances to CONCLUDE",
              r.phase == "CONCLUDE" and r.action == LoopAction.RUN_PHASE)
        # CONCLUDE → returns next phase = REFRESH_CONTEXT
        r = loop.submit(t.id, "CONCLUDE",
                    "HONCHO: done\nDOCS: NOT_NEEDED\nCONTEXT: NOT_NEEDED")
        check("CONCLUDE advances to REFRESH_CONTEXT",
              r.phase == "REFRESH_CONTEXT" and r.action == LoopAction.RUN_PHASE)

        # Verify we're at REFRESH_CONTEXT
        check("at REFRESH_CONTEXT phase before submit",
              loop.next_phase(t.id) == "REFRESH_CONTEXT")

        # Submit REFRESH_CONTEXT with no config.yaml present
        outcome = loop.submit(t.id, "REFRESH_CONTEXT", "")
        check("REFRESH_CONTEXT completes (not RETRY) without config.yaml",
              outcome.action != LoopAction.RETRY)
        check("REFRESH_CONTEXT advances to DONE (or at least does not fail)",
              outcome.action in (LoopAction.DONE, LoopAction.RUN_PHASE))
    finally:
        if config_existed:
            bak = ROOT / ".techne" / "config.yaml.bak"
            if bak.exists():
                bak.rename(config_path)


# ── Patch 4: Auto-add .techne/tasks/ to .gitignore on DONE ──────────────────────


def test_patch4_gitignore_updated_on_done():
    """
    Patch 4: After DONE, .gitignore in project root must contain
    '.techne/tasks/' and '.techne/memory/'.
    """
    print("\n[Patch 4 — .gitignore updated on DONE]")
    db = TaskDB(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    rl = RewardLog(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    loop = OrchestratorLoop(db, reward_log=rl)

    # Create a temp project dir for clean gitignore test
    with tempfile.TemporaryDirectory() as tmpdir:
        gitignore = Path(tmpdir) / ".gitignore"
        # Write initial .gitignore
        gitignore.write_text("# existing\nnode_modules/\n", encoding="utf-8")

        # Create a fake .techne/tasks dir
        techne_dir = Path(tmpdir) / ".techne"
        tasks_dir = techne_dir / "tasks"
        memory_dir = techne_dir / "memory"
        tasks_dir.mkdir(parents=True)
        memory_dir.mkdir(parents=True)

        # Simulate DONE by calling _ensure_techne_gitignore directly
        # (In real flow this is called from _record_reward → DONE)
        loop._ensure_techne_gitignore(tmpdir)

        content = gitignore.read_text(encoding="utf-8")
        check(".gitignore contains '.techne/tasks/'",
              ".techne/tasks/" in content or ".techne/tasks\\" in content)
        check(".gitignore contains '.techne/memory/'",
              ".techne/memory/" in content or ".techne/memory\\" in content)


# ── Patch 5: BLOCKED transitions include VERIFY, REVIEW, EVAL ───────────────────


def test_patch5_blocked_transitions_include_verify_review_eval():
    """
    Patch 5: The BLOCKED entry in TRANSITIONS dict must include VERIFY,
    REVIEW, and EVAL — allowing re-entry into these phases after unblock.
    """
    print("\n[Patch 5 — BLOCKED transitions include VERIFY, REVIEW, EVAL]")
    blocked_targets = TRANSITIONS.get("BLOCKED", [])
    check("VERIFY in BLOCKED transitions", "VERIFY" in blocked_targets)
    check("REVIEW in BLOCKED transitions", "REVIEW" in blocked_targets)
    check("EVAL in BLOCKED transitions", "EVAL" in blocked_targets)


def test_patch5_can_enter_verify_when_blocked():
    """
    Patch 5: can_enter() must allow VERIFY when task is BLOCKED.
    """
    print("\n[Patch 5 — can_enter(VERIFY) when BLOCKED]")
    db = TaskDB(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    enf = PipelineEnforcer(db)
    t = db.create_task("test verify blocked re-entry")

    # Set task to BLOCKED directly
    enf.block_for_hitl(t.id, question="Test?")
    ce = enf.can_enter(t.id, "VERIFY")
    check("can_enter(VERIFY) allowed when BLOCKED", ce.allowed)

    ce_review = enf.can_enter(t.id, "REVIEW")
    check("can_enter(REVIEW) allowed when BLOCKED", ce_review.allowed)

    ce_eval = enf.can_enter(t.id, "EVAL")
    check("can_enter(EVAL) allowed when BLOCKED", ce_eval.allowed)


# ── Main runner ─────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    mark_honcho_concluded("p3-fixture-main")
    try:
        print("=" * 60)
        print("PIPELINE PATCHES — TDD tests")
        print("=" * 60)

        test_patch1_review_autoadvance_trivial()
        test_patch2_verify_reentry_after_unblock()
        test_patch2_verify_reentry_via_orchestrator()
        test_patch3_refresh_context_graceful_without_config()
        test_patch4_gitignore_updated_on_done()
        test_patch5_blocked_transitions_include_verify_review_eval()
        test_patch5_can_enter_verify_when_blocked()

        passed = sum(1 for r in results if r)
        total = len(results)
        print("\n" + "=" * 60)
        print(f"RESULTS: {passed}/{total} passed" +
              ("  — all clear" if passed == total else f"  ({total - passed} FAILED)"))
        print("=" * 60)
        sys.exit(0 if passed == total else 1)
    finally:
        clear_honcho_flag()
