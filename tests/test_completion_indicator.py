"""
test_completion_indicator.py — Unit tests for summarize_incomplete().

Tests:
  1. A task driven to DONE prints ✓ case with full phase list.
  2. A task that hits BLOCK_HITL (critique CRITICAL) and stops prints ⚠ with
     correct completed / stuck-at / never-reached lists.
  3. A completed fast-mode task does NOT list skipped phases under "Never reached".
  4. A completed micro-mode task has the correct expected 5 phases.

Run from tests/:  python test_completion_indicator.py
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

from orchestrator_loop import OrchestratorLoop
from task_db import TaskDB, TaskEvent


def _make_event(task_id: str, agent: str, action: str, verdict: str = "PASS",
                summary: str = "", findings: str = "") -> TaskEvent:
    return TaskEvent(
        id=str(uuid.uuid4()),
        task_id=task_id,
        agent=agent,
        action=action,
        summary=summary,
        verdict=verdict,
        findings=findings,
        timestamp="2025-01-01T00:00:00Z",
    )


class TestCompletionIndicator(unittest.TestCase):
    """Tests for OrchestratorLoop.summarize_incomplete()."""

    def setUp(self):
        self.db = TaskDB(db_path=":memory:")
        self.loop = OrchestratorLoop(self.db)

    def _build_history(self, task_id: str, events: list[TaskEvent],
                        task_status: str | None = None) -> None:
        """Splice events directly into the DB so get_task_history returns them.
        If task_status is set, also update the task's status column."""
        import sqlite3
        conn = self.db._conn
        for e in events:
            conn.execute(
                """INSERT INTO task_events
                   (id, task_id, agent, action, summary, changed_files, diff_summary,
                    findings, verdict, test_output_hash, mistakes_found, timestamp)
                   VALUES (?, ?, ?, ?, ?, '[]', '', ?, ?, '', '[]', ?)""",
                (e.id, e.task_id, e.agent, e.action, e.summary,
                 e.findings, e.verdict, e.timestamp),
            )
        if task_status is not None:
            conn.execute(
                "UPDATE tasks SET status = ? WHERE id = ?",
                (task_status, task_id),
            )
        conn.commit()

    # ── Test 1: ✓ TASK COMPLETE — all phases done ──────────────────────────

    def test_done_full_mode_shows_checkmark_and_all_phases(self):
        """A full-mode task at DONE prints ✓ with the full 12-phase pipeline."""
        task = self.db.create_task("full task", phase_mode="full")
        events = [
            _make_event(task.id, "recaller", "RECALL"),
            _make_event(task.id, "implementer", "IMPLEMENT"),
            _make_event(task.id, "context-guard", "CONTEXT_GUARD"),
            _make_event(task.id, "critique", "CRITIQUE"),
            _make_event(task.id, "reviewer", "REVIEW"),
            _make_event(task.id, "verifier", "VERIFY"),
            _make_event(task.id, "evaluator", "EVAL"),
            _make_event(task.id, "retro", "RETRO"),
            _make_event(task.id, "concluder", "CONCLUDE"),
            _make_event(task.id, "refresh_context", "REFRESH_CONTEXT"),
            _make_event(task.id, "orchestrator", "DONE"),
        ]
        self._build_history(task.id, events, task_status="DONE")

        result = self.loop.summarize_incomplete(task.id)

        self.assertTrue(result.startswith("✓"), f"Expected ✓ but got: {result}")
        self.assertIn("TASK COMPLETE", result)
        self.assertIn("(12/12 phases)", result)
        # Every phase should appear in the completion chain
        for phase in ("RECALL", "IMPLEMENT", "CONTEXT_GUARD", "CRITIQUE",
                      "REVIEW", "VERIFY", "EVAL", "RETRO", "CONCLUDE",
                      "REFRESH_CONTEXT", "DONE"):
            self.assertIn(phase, result, f"{phase} missing from: {result}")

    # ── Test 2: ⚠ TASK INCOMPLETE — BLOCK_HITL ─────────────────────────────

    def test_blocked_at_review_shows_warn_and_never_reached(self):
        """A task blocked at REVIEW by HITL shows completed phases, stuck phase,
        and all downstream phases under 'Never reached'."""
        task = self.db.create_task("blocked task", phase_mode="full")
        events = [
            _make_event(task.id, "recaller", "RECALL"),
            _make_event(task.id, "implementer", "IMPLEMENT"),
            _make_event(task.id, "context-guard", "CONTEXT_GUARD"),
            _make_event(task.id, "critique", "CRITIQUE"),
            _make_event(task.id, "reviewer", "REVIEW"),
            # HITL block on REVIEW
            _make_event(task.id, "orchestrator", "hitl_request",
                        verdict="BLOCK", summary="HITL: CRITICAL issue found"),
        ]
        self._build_history(task.id, events)

        result = self.loop.summarize_incomplete(task.id)

        self.assertTrue(result.startswith("⚠"), f"Expected ⚠ but got: {result}")
        self.assertIn("TASK INCOMPLETE", result)
        # Completed phases
        self.assertIn("RECALL", result)
        self.assertIn("IMPLEMENT", result)
        self.assertIn("CONTEXT_GUARD", result)
        self.assertIn("CRITIQUE", result)
        # Stuck phase
        self.assertIn("Stuck at", result)
        # Never reached
        self.assertIn("Never reached", result)
        self.assertIn("VERIFY", result)
        self.assertIn("EVAL", result)
        self.assertIn("RETRO", result)
        self.assertIn("CONCLUDE", result)
        self.assertIn("REFRESH_CONTEXT", result)
        self.assertIn("DONE", result)

    def test_incomplete_task_shows_retry_count_in_stuck_reason(self):
        """When a phase hit BLOCK_HITL after retries, the retry count appears."""
        task = self.db.create_task("retried task", phase_mode="full")
        events = [
            _make_event(task.id, "recaller", "RECALL"),
            _make_event(task.id, "implementer", "IMPLEMENT"),
            _make_event(task.id, "context-guard", "CONTEXT_GUARD"),
            _make_event(task.id, "critique", "CRITIQUE"),
            _make_event(task.id, "reviewer", "REVIEW", verdict="SOFT_FAIL"),
            _make_event(task.id, "reviewer", "REVIEW", verdict="SOFT_FAIL"),
            _make_event(task.id, "reviewer", "REVIEW", verdict="SOFT_FAIL"),
            _make_event(task.id, "orchestrator", "hitl_request",
                        verdict="BLOCK", summary="HITL: CRITICAL"),
        ]
        self._build_history(task.id, events)

        result = self.loop.summarize_incomplete(task.id)

        self.assertIn("3 retries", result)
        self.assertIn("BLOCK_HITL", result)

    # ── Test 3: Fast mode — skipped phases absent from "Never reached" ─────

    def test_fast_mode_completed_excludes_skipped_from_never_reached(self):
        """A completed fast-mode task must NOT list RECALL/CONCLUDE/REFRESH_CONTEXT
        under 'Never reached'."""
        task = self.db.create_task("fast task", phase_mode="fast")
        events = [
            _make_event(task.id, "implementer", "IMPLEMENT"),
            _make_event(task.id, "context-guard", "CONTEXT_GUARD"),
            _make_event(task.id, "critique", "CRITIQUE"),
            _make_event(task.id, "reviewer", "REVIEW"),
            _make_event(task.id, "verifier", "VERIFY"),
            _make_event(task.id, "evaluator", "EVAL"),
            _make_event(task.id, "retro", "RETRO"),
            # fast mode skips CONCLUDE and REFRESH_CONTEXT, goes straight to DONE
            _make_event(task.id, "orchestrator", "DONE"),
        ]
        self._build_history(task.id, events, task_status="DONE")

        result = self.loop.summarize_incomplete(task.id)

        self.assertTrue(result.startswith("✓"), f"Expected ✓ but got: {result}")
        # Skipped phases must NOT appear under "Never reached"
        self.assertNotIn("RECALL", result)
        self.assertNotIn("CONCLUDE", result)
        self.assertNotIn("REFRESH_CONTEXT", result)
        # Should still list what was completed
        self.assertIn("IMPLEMENT", result)
        self.assertIn("DONE", result)

    # ── Test 4: Micro mode — correct 5-phase expected list ──────────────────

    def test_micro_mode_completed_has_5_expected_phases(self):
        """A completed micro-mode task reports (5/5 phases) and lists only
        IMPLEMENT → CONTEXT_GUARD → VERIFY → EVAL → DONE."""
        task = self.db.create_task("micro task", phase_mode="micro")
        events = [
            _make_event(task.id, "implementer", "IMPLEMENT"),
            _make_event(task.id, "context-guard", "CONTEXT_GUARD"),
            _make_event(task.id, "verifier", "VERIFY"),
            _make_event(task.id, "evaluator", "EVAL"),
            _make_event(task.id, "orchestrator", "DONE"),
        ]
        self._build_history(task.id, events, task_status="DONE")

        result = self.loop.summarize_incomplete(task.id)

        self.assertTrue(result.startswith("✓"), f"Expected ✓ but got: {result}")
        self.assertIn("(5/5 phases)", result)
        # All 5 micro phases should be present
        for phase in ("IMPLEMENT", "CONTEXT_GUARD", "VERIFY", "EVAL", "DONE"):
            self.assertIn(phase, result, f"{phase} missing from: {result}")
        # Full-mode-only phases must NOT appear at all
        for phase in ("RECALL", "CRITIQUE", "REVIEW", "RETRO", "CONCLUDE", "REFRESH_CONTEXT"):
            self.assertNotIn(phase, result, f"{phase} should not appear in micro mode: {result}")

    def test_micro_mode_incomplete_never_reached_shows_micro_phases(self):
        """A micro-mode task stuck at VERIFY lists only EVAL and DONE as never reached."""
        task = self.db.create_task("micro blocked", phase_mode="micro")
        events = [
            _make_event(task.id, "implementer", "IMPLEMENT"),
            _make_event(task.id, "context-guard", "CONTEXT_GUARD"),
            _make_event(task.id, "verifier", "VERIFY"),
            _make_event(task.id, "orchestrator", "hitl_request",
                        verdict="BLOCK", summary="HITL: tests failing"),
        ]
        self._build_history(task.id, events)

        result = self.loop.summarize_incomplete(task.id)

        self.assertTrue(result.startswith("⚠"), f"Expected ⚠ but got: {result}")
        self.assertIn("Never reached", result)
        self.assertIn("EVAL", result)
        self.assertIn("DONE", result)
        # Full-mode phases must NOT appear in never-reached
        self.assertNotIn("RECALL", result)
        self.assertNotIn("CRITIQUE", result)
        self.assertNotIn("REVIEW", result)
        self.assertNotIn("RETRO", result)
        self.assertNotIn("CONCLUDE", result)
        self.assertNotIn("REFRESH_CONTEXT", result)


if __name__ == "__main__":
    unittest.main()
