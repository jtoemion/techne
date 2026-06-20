"""
test_conclude_gate.py — Tests for the CONCLUDE proof gate and context-guard punch list enforcement.

Covers the bugs found during review:
1. Keyword bypass: "The conclusion is that..." without HONCHO line should fail
2. SHA scoping: SHA on HONCHO line should NOT satisfy CONTEXT line requirement
3. Context-updated detection: lines without "context" prefix handled correctly
4. Punch list enforcement: context-guard missing punch list → RETRY
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add harness to path
HARNESS_DIR = Path(__file__).parent.parent / "harness"
sys.path.insert(0, str(HARNESS_DIR))

from task_db import TaskDB
from orchestrator_loop import OrchestratorLoop, LoopAction
from reward_log import RewardLog


def _make_loop():
    """Create a fresh OrchestratorLoop with an in-memory DB.
    Mocks _get_uncommitted_context_files to avoid real git checks in tests."""
    from unittest.mock import patch
    db = TaskDB(":memory:")
    reward_log = RewardLog()
    loop = OrchestratorLoop(db, reward_log=reward_log)
    # Suppress real git-state check — integration-level concern, not unit test scope
    patch.object(loop, "_get_uncommitted_context_files", return_value=[]).start()
    return loop


def _make_task(loop: OrchestratorLoop, title: str = "test task") -> str:
    """Create a task and return its ID."""
    task = loop.db.create_task(title, description="test", discipline="tdd")
    return task.id


def _setup_for_conclude(loop: OrchestratorLoop, task_id: str):
    """Mark all phases up to CONCLUDE as complete."""
    phases = ["RECALL", "IMPLEMENT", "CONTEXT_GUARD", "CRITIQUE", "REVIEW", "VERIFY", "EVAL", "RETRO"]
    for phase in phases:
        loop.enforcer.mark_complete(task_id, phase, agent="test", summary=f"{phase} done")


# ── CONCLUDE proof validation tests ──────────────────────────────────────

def test_valid_proof_passes():
    """A properly formatted proof with all three sections passes."""
    loop = _make_loop()
    task_id = _make_task(loop)
    _setup_for_conclude(loop, task_id)

    proof = """HONCHO: conclusion-id-abc123 — saved badge component pattern
DOCS: NOT_NEEDED: trivial UI change, no docs affected
CONTEXT: NOT_NEEDED: no .techne/context files changed"""

    outcome = loop.submit(task_id, "CONCLUDE", proof)
    assert outcome.action == LoopAction.DONE, f"Expected DONE, got {outcome.action}: {outcome.message}"


def test_keyword_bypass_rejected():
    """'The conclusion is that the diff is clean' without HONCHO line should fail."""
    loop = _make_loop()
    task_id = _make_task(loop)
    _setup_for_conclude(loop, task_id)

    # Contains "conclusion" but not as a HONCHO: line prefix
    proof = """The conclusion is that the diff is clean and well-structured.
DOCS: NOT_NEEDED: no documentation changes required
CONTEXT: NOT_NEEDED: no context files changed"""

    outcome = loop.submit(task_id, "CONCLUDE", proof)
    assert outcome.action == LoopAction.RETRY, f"Expected RETRY (keyword bypass), got {outcome.action}"
    assert "HONCHO" in outcome.message, f"Should mention HONCHO is missing: {outcome.message}"


def test_sha_on_wrong_line_rejected():
    """SHA on the HONCHO line should NOT satisfy the CONTEXT line requirement."""
    loop = _make_loop()
    task_id = _make_task(loop)
    _setup_for_conclude(loop, task_id)

    # SHA is on the HONCHO line, not CONTEXT line
    proof = """HONCHO: conclusion-id-abc123 sha:abc123def456789012345678901234567890abcd
DOCS: docs/api.md updated with new endpoint
CONTEXT: .techne/context/project.md refreshed"""

    outcome = loop.submit(task_id, "CONCLUDE", proof)
    assert outcome.action == LoopAction.RETRY, f"Expected RETRY (SHA on wrong line), got {outcome.action}"
    assert "SHA" in outcome.message, f"Should mention SHA is missing: {outcome.message}"


def test_sha_on_context_line_passes():
    """SHA on the CONTEXT line should pass when context is updated."""
    loop = _make_loop()
    task_id = _make_task(loop)
    _setup_for_conclude(loop, task_id)

    proof = """HONCHO: conclusion-id-abc123
DOCS: docs/api.md updated
CONTEXT: .techne/context/project.md refreshed sha:abc123def456789012345678901234567890abcd"""

    outcome = loop.submit(task_id, "CONCLUDE", proof)
    assert outcome.action == LoopAction.DONE, f"Expected DONE, got {outcome.action}: {outcome.message}"


def test_context_not_needed_skips_sha():
    """CONTEXT: NOT_NEEDED should not require a SHA."""
    loop = _make_loop()
    task_id = _make_task(loop)
    _setup_for_conclude(loop, task_id)

    proof = """HONCHO: conclusion-id-abc123
DOCS: NOT_NEEDED: no doc changes
CONTEXT: NOT_NEEDED: no context changes"""

    outcome = loop.submit(task_id, "CONCLUDE", proof)
    assert outcome.action == LoopAction.DONE, f"Expected DONE, got {outcome.action}: {outcome.message}"


def test_missing_honcho_rejected():
    """Proof without HONCHO line should be rejected."""
    loop = _make_loop()
    task_id = _make_task(loop)
    _setup_for_conclude(loop, task_id)

    proof = """DOCS: NOT_NEEDED: no changes
CONTEXT: NOT_NEEDED: no changes"""

    outcome = loop.submit(task_id, "CONCLUDE", proof)
    assert outcome.action == LoopAction.RETRY, f"Expected RETRY (missing HONCHO), got {outcome.action}"
    assert "HONCHO" in outcome.message


def test_missing_docs_rejected():
    """Proof without DOCS line should be rejected."""
    loop = _make_loop()
    task_id = _make_task(loop)
    _setup_for_conclude(loop, task_id)

    proof = """HONCHO: conclusion-id-abc123
CONTEXT: NOT_NEEDED: no changes"""

    outcome = loop.submit(task_id, "CONCLUDE", proof)
    assert outcome.action == LoopAction.RETRY, f"Expected RETRY (missing DOCS), got {outcome.action}"
    assert "DOCS" in outcome.message


def test_missing_context_rejected():
    """Proof without CONTEXT line should be rejected."""
    loop = _make_loop()
    task_id = _make_task(loop)
    _setup_for_conclude(loop, task_id)

    proof = """HONCHO: conclusion-id-abc123
DOCS: NOT_NEEDED: no changes"""

    outcome = loop.submit(task_id, "CONCLUDE", proof)
    assert outcome.action == LoopAction.RETRY, f"Expected RETRY (missing CONTEXT), got {outcome.action}"
    assert "CONTEXT" in outcome.message


def test_short_proof_rejected():
    """Proof shorter than 40 chars should be rejected."""
    loop = _make_loop()
    task_id = _make_task(loop)
    _setup_for_conclude(loop, task_id)

    outcome = loop.submit(task_id, "CONCLUDE", "too short")
    assert outcome.action == LoopAction.RETRY


def test_honcho_keyword_in_body_not_counted():
    """'honcho' appearing in the body of a DOCS line should not satisfy HONCHO requirement."""
    loop = _make_loop()
    task_id = _make_task(loop)
    _setup_for_conclude(loop, task_id)

    proof = """DOCS: docs/honcho-integration.md updated
CONTEXT: NOT_NEEDED: no changes"""

    # This should fail because there's no HONCHO: line prefix
    outcome = loop.submit(task_id, "CONCLUDE", proof)
    assert outcome.action == LoopAction.RETRY, f"Expected RETRY (honcho in body), got {outcome.action}"
    assert "HONCHO" in outcome.message


# ── Context-guard punch list enforcement tests ───────────────────────────

def test_context_guard_missing_punch_list_retries():
    """Context-guard output without punch list should trigger RETRY."""
    loop = _make_loop()
    task_id = _make_task(loop)

    # Simulate: task has passed RECALL + IMPLEMENT (required before CONTEXT_GUARD)
    loop.enforcer.mark_complete(task_id, "RECALL", agent="test", summary="recall ok")
    loop.enforcer.mark_complete(task_id, "IMPLEMENT", agent="test", summary="diff ok")

    # Submit context-guard output without punch list
    audit = "All files look good. No scope creep detected. Diff is clean."
    outcome = loop.submit(task_id, "CONTEXT_GUARD", audit)
    assert outcome.action == LoopAction.RETRY, f"Expected RETRY (missing punch list), got {outcome.action}"
    assert "PUNCH LIST" in outcome.message, f"Should mention punch list: {outcome.message}"


def test_context_guard_with_punch_list_passes():
    """Context-guard output with punch list should advance."""
    loop = _make_loop()
    task_id = _make_task(loop)

    loop.enforcer.mark_complete(task_id, "RECALL", agent="test", summary="recall ok")
    loop.enforcer.mark_complete(task_id, "IMPLEMENT", agent="test", summary="diff ok")

    audit = """CONTEXT-GUARD REPORT
Files changed: 3
Scope: IN_SCOPE

CONCLUDE PUNCH LIST
DOCS: NOT_NEEDED: no API changes
CONTEXT: NOT_NEEDED: no context changes
HONCHO: saved badge component pattern"""

    outcome = loop.submit(task_id, "CONTEXT_GUARD", audit)
    assert outcome.action == LoopAction.RUN_PHASE, f"Expected RUN_PHASE, got {outcome.action}: {outcome.message}"
    assert outcome.phase == "CRITIQUE"


# ── PhaseRouter tests ───────────────────────────────────────────────────

def test_phase_router_dispatches_by_phase():
    """PhaseRouter routes different phases to different models."""
    from model_backends import PhaseRouter

    call_log = []

    def implementer(system, user, phase):
        call_log.append(("implementer", phase))
        return "implement-diff"

    def reviewer(system, user, phase):
        call_log.append(("reviewer", phase))
        return "review-result"

    router = PhaseRouter(default=implementer)
    router.route("review", reviewer)

    # IMPLEMENT → default (implementer)
    result = router("sys", "user", "IMPLEMENT")
    assert result == "implement-diff"
    assert call_log[-1] == ("implementer", "IMPLEMENT")

    # REVIEW → reviewer
    result = router("sys", "user", "REVIEW")
    assert result == "review-result"
    assert call_log[-1] == ("reviewer", "REVIEW")

    # CRITIQUE → default (implementer, no route registered)
    result = router("sys", "user", "CRITIQUE")
    assert result == "implement-diff"
    assert call_log[-1] == ("implementer", "CRITIQUE")


def test_phase_router_longest_prefix_wins():
    """PhaseRouter picks the longest matching prefix."""
    from model_backends import PhaseRouter

    def model_a(system, user, phase):
        return "A"

    def model_b(system, user, phase):
        return "B"

    router = PhaseRouter(default=model_a)
    router.route("context", model_b)  # matches CONTEXT_GUARD, CONTEXT
    router.route("context_guard", model_a)  # more specific

    result = router("sys", "user", "CONTEXT_GUARD")
    assert result == "A", f"Expected model_a (longer prefix), got {result}"


if __name__ == "__main__":
    import traceback

    tests = [
        test_valid_proof_passes,
        test_keyword_bypass_rejected,
        test_sha_on_wrong_line_rejected,
        test_sha_on_context_line_passes,
        test_context_not_needed_skips_sha,
        test_missing_honcho_rejected,
        test_missing_docs_rejected,
        test_missing_context_rejected,
        test_short_proof_rejected,
        test_honcho_keyword_in_body_not_counted,
        test_context_guard_missing_punch_list_retries,
        test_context_guard_with_punch_list_passes,
        test_phase_router_dispatches_by_phase,
        test_phase_router_longest_prefix_wins,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {test.__name__}: {e}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed}/{passed + failed} passed" + ("" if failed == 0 else f" ({failed} FAILED)"))
    print(f"{'='*60}")
    sys.exit(0 if failed == 0 else 1)
