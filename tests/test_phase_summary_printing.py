"""
test_phase_summary_printing.py — capsys tests for per-phase summary output.

Verifies that _print_phase_summary produces correctly formatted one-line
summaries with the bracketed phase tag, the (!) marker for non-clean
outcomes, and the next-phase arrow.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock as _mock

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(TESTS_DIR))

# Suppress real .techne/context git-state check.
_mock.patch.object(
    __import__("orchestrator_loop", fromlist=["OrchestratorLoop"]).OrchestratorLoop,
    "_get_uncommitted_context_files",
    return_value=[],
).start()
_mock.patch("checkpoint.check_honcho_logged", return_value="auto-honcho-123").start()

from orchestrator_loop import OrchestratorLoop, LoopOutcome, LoopAction
from task_db import TaskDB


class _FakeEnforcer:
    """Minimal stand-in for PipelineEnforcer that satisfies mark_complete / block_for_hitl."""
    def __init__(self, db):
        self.db = db
    def mark_complete(self, *a, **k):
        pass
    def block_for_hitl(self, *a, **k):
        pass
    def unblock(self, *a, **k):
        pass
    def get_phase(self, task_id):
        return None


def _make_loop() -> OrchestratorLoop:
    """Build an OrchestratorLoop with a fresh in-memory DB and fake enforcer."""
    db = TaskDB()
    enforcer = _FakeEnforcer(db)
    loop = OrchestratorLoop(db, enforcer=enforcer)
    return loop


# ── helpers ────────────────────────────────────────────────────────────────

def _capture(loop: OrchestratorLoop, phase: str, result: str, task_id: str = "t0") -> tuple[str, str]:
    """Call submit() for the given phase and return (stdout, stderr) from capsys."""
    with _mock.patch.object(loop, "enforcer", _FakeEnforcer(loop.db)):
        loop.submit(task_id, phase, result)
    import io
    from contextlib import redirect_stdout, redirect_stderr
    return "", ""  # placeholder; actual capture done by pytest's capsys fixture


# ── Test 1: clean RECALL prints [RECALL] tag ────────────────────────────────

def test_recall_clean_has_bracket_tag(capsys, monkeypatch):
    """Clean RECALL outcome prints the [RECALL] bracketed tag."""
    monkeypatch.setenv("HONCHO_SESSION_ID", "test-session-123")
    loop = _make_loop()
    task_id = loop.db.create_task("test recall").id

    # A result that passes RECALL's gates
    result = "HONCHO_CONTEXT: some durable context\nworkshop_context: file.md"

    outcome = loop._submit_recall(task_id, result)

    captured = capsys.readouterr()
    assert "[RECALL]" in captured.out, (
        f"Expected [RECALL] tag in output, got: {captured.out!r}"
    )


def test_recall_clean_no_warning_marker(capsys, monkeypatch):
    """Clean RECALL outcome has no (!) warning marker."""
    monkeypatch.setenv("HONCHO_SESSION_ID", "test-session-123")
    loop = _make_loop()
    task_id = loop.db.create_task("test recall").id

    result = "HONCHO_CONTEXT: some durable context\nworkshop_context: file.md"
    outcome = loop._submit_recall(task_id, result)

    captured = capsys.readouterr()
    assert "(!)" not in captured.out, (
        f"Clean outcome should not have (!) marker, got: {captured.out!r}"
    )


def test_recall_clean_shows_next_phase(capsys, monkeypatch):
    """Clean RECALL output mentions the next phase (IMPLEMENT)."""
    monkeypatch.setenv("HONCHO_SESSION_ID", "test-session-123")
    loop = _make_loop()
    task_id = loop.db.create_task("test recall").id

    result = "HONCHO_CONTEXT: some durable context\nworkshop_context: file.md"
    outcome = loop._submit_recall(task_id, result)

    captured = capsys.readouterr()
    assert "IMPLEMENT" in captured.out or "implement" in captured.out.lower(), (
        f"Expected IMPLEMENT (next phase) in output, got: {captured.out!r}"
    )


# ── Test 2: IMPLEMENT gate violation → RETRY with (!) ───────────────────────

def test_implement_retry_has_warning_marker(capsys, monkeypatch):
    """IMPLEMENT diff with no @@ markers produces (!) in summary line."""
    monkeypatch.setenv("HONCHO_SESSION_ID", "test-session-456")
    loop = _make_loop()
    task_id = loop.db.create_task("test implement").id

    # No valid diff markers → gate rejection → RETRY
    bad_diff = "just some text that isn't a diff"
    outcome = loop._submit_implement(task_id, bad_diff)

    captured = capsys.readouterr()
    assert "(!)" in captured.out, (
        f"RETRY/BLOCK_HITL outcome should have (!) marker, got: {captured.out!r}"
    )
    assert outcome.action == LoopAction.RETRY


def test_implement_retry_has_phase_tag(capsys, monkeypatch):
    """IMPLEMENT retry output includes the [IMPLEMENT] tag."""
    monkeypatch.setenv("HONCHO_SESSION_ID", "test-session-456")
    loop = _make_loop()
    task_id = loop.db.create_task("test implement").id

    bad_diff = "not a diff"
    outcome = loop._submit_implement(task_id, bad_diff)

    captured = capsys.readouterr()
    assert "[IMPLEMENT]" in captured.out, (
        f"Expected [IMPLEMENT] tag in output, got: {captured.out!r}"
    )


# ── Test 3: clean VERIFY prints [VERIFY] without (!) ─────────────────────────

def test_verify_clean_no_warning_marker(capsys, monkeypatch):
    """VERIFY with passing tests prints [VERIFY] without (!)."""
    monkeypatch.setenv("HONCHO_SESSION_ID", "test-session-789")
    loop = _make_loop()
    task_id = loop.db.create_task("test verify").id

    # Set up minimal state so VERIFY doesn't immediately reject on gates
    loop._diff[task_id] = "--- a/f.js\n+++ b/f.js\n@@ -1 +1 @@\n-old\n+new"
    loop._scope[task_id] = type("Scope", (), {"scope_clean": True, "intent_mismatch": False})()
    loop._gate_pass[task_id] = True

    # Passing test output — patch verify_tests so the SHA gate doesn't emit extra lines
    fake_verify = type("VerifyResult", (), {"passed": True, "message": "SHA gate passed"})()
    with _mock.patch("orchestrator_loop.verify_tests", return_value=fake_verify):
        passing_tests = "=== BUILD ===\nCompiled successfully\n\n=== TYPE CHECK ===\nNo issues found\n\n=== TESTS ===\n✓ test_a\n✓ test_b"
        outcome = loop._submit_verify(task_id, passing_tests)

    captured = capsys.readouterr()
    # Only look at the [VERIFY] line (our phase summary), not SHA gate output
    verify_line = next((l for l in captured.out.splitlines() if "[VERIFY]" in l), captured.out)
    assert "[VERIFY]" in verify_line, (
        f"Expected [VERIFY] tag in output, got: {captured.out!r}"
    )
    assert "(!)" not in verify_line, (
        f"Clean VERIFY outcome should not have (!) marker, got: {verify_line!r}"
    )


# ── Test 4: faked-output VERIFY → BLOCK_HITL with (!) ───────────────────────

def test_verify_faked_output_block_hitl_has_warning_marker(capsys, monkeypatch):
    """VERIFY with clearly faked/rejected test output shows (!) and BLOCK_HITL."""
    monkeypatch.setenv("HONCHO_SESSION_ID", "test-session-abc")
    loop = _make_loop()
    task_id = loop.db.create_task("test verify").id

    # Same setup as clean case, but test output will fail SHA gate
    loop._diff[task_id] = "--- a/f.js\n+++ b/f.js\n@@ -1 +1 @@\n-old\n+new"
    loop._scope[task_id] = type("Scope", (), {"scope_clean": True, "intent_mismatch": False})()
    loop._gate_pass[task_id] = True

    # Faked output — same hash as previous run, no unique indicators
    fake_output = "ALL TESTS PASSED"  # no real build/test markers
    outcome = loop._submit_verify(task_id, fake_output)

    captured = capsys.readouterr()
    assert "(!)" in captured.out, (
        f"BLOCK_HITL outcome should have (!) marker, got: {captured.out!r}"
    )
    assert "[VERIFY]" in captured.out, (
        f"Expected [VERIFY] tag in output, got: {captured.out!r}"
    )
    assert outcome.action == LoopAction.BLOCK_HITL


# ── Test 5: summary message keyword presence ─────────────────────────────────

def test_recall_summary_contains_context_keyword(capsys, monkeypatch):
    """RECALL clean summary mentions 'context' (the recall artifact)."""
    monkeypatch.setenv("HONCHO_SESSION_ID", "test-session-def")
    loop = _make_loop()
    task_id = loop.db.create_task("test recall").id

    result = "HONCHO_CONTEXT: durable facts\nworkshop_context: retrieved docs"
    outcome = loop._submit_recall(task_id, result)

    captured = capsys.readouterr()
    # The message from the clean RECALL path includes "Context recalled"
    assert "Context" in captured.out or "context" in captured.out.lower(), (
        f"Summary should mention context, got: {captured.out!r}"
    )


def test_conclude_proof_summary_has_proof_keyword(capsys, monkeypatch):
    """CONCLUDE clean summary mentions 'Conclusion recorded'."""
    monkeypatch.setenv("HONCHO_SESSION_ID", "test-session-ghi")
    monkeypatch.setattr("pathlib.Path.exists", lambda p: True)  # skip config check
    loop = _make_loop()
    task_id = loop.db.create_task("test conclude").id

    # Pre-mark EVAL so CONCLUDE doesn't fail on eval lookup
    loop._eval[task_id] = type("Report", (), {"total": 85, "grade": "A"})()

    # Patch check_honcho_logged to return truthy (simulatesHoncho was logged)
    # and _get_uncommitted_context_files to return [] (no uncommitted changes)
    with _mock.patch.object(loop, "_get_uncommitted_context_files", return_value=[]):
            result = "HONCHO: done\nDOCS: updated\nCONTEXT: .techne/context refreshed sha:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
            outcome = loop._submit_conclude(task_id, result)

    captured = capsys.readouterr()
    assert "[CONCLUDE]" in captured.out, (
        f"Expected [CONCLUDE] tag in output, got: {captured.out!r}"
    )
    # Clean CONCLUDE → RUN_PHASE → no (!)
    assert "(!)" not in captured.out, (
        f"Clean outcome should not have (!) marker, got: {captured.out!r}"
    )
    assert "context refresh" in captured.out, (
        f"Expected next phase 'context refresh' in output, got: {captured.out!r}"
    )
