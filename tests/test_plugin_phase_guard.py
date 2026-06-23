"""Tests for harness/plugins/phase_guard.py"""

from __future__ import annotations

import json
from pathlib import Path

from harness.plugins.phase_guard import check_write_allowed, log_blocked, get_blocked_log


def _create_state(techne_root: Path, phase="RECALL"):
    """Create a state.json at .techne/loop/state.json."""
    loop_dir = techne_root / ".techne" / "loop"
    loop_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "task_id": "test-1",
        "phase": phase,
        "created_at": "2026-06-23T12:00:00+00:00",
        "updated_at": "2026-06-23T12:00:00+00:00",
        "phase_timeout_min": 30,
        "summary": "",
    }
    (loop_dir / "state.json").write_text(json.dumps(state, indent=2))


class TestNoState:
    def test_no_state_blocks_project_writes(self, tmp_path):
        """No state.json → writes to project files blocked."""
        (tmp_path / ".techne" / "loop").mkdir(parents=True)
        allowed, reason = check_write_allowed("src/app.py", cwd=str(tmp_path))
        assert not allowed
        assert "No active pipeline" in reason
        assert "start the loop" in reason

    def test_no_state_allows_techne_writes(self, tmp_path):
        """No state.json → writes to .techne/ allowed."""
        (tmp_path / ".techne" / "loop").mkdir(parents=True)
        allowed, reason = check_write_allowed(".techne/loop/state.json", cwd=str(tmp_path))
        assert allowed, f"Expected allowed, got: {reason}"


class TestActiveState:
    def test_allows_source_writes(self, tmp_path):
        """Active state → writes to project source files allowed."""
        _create_state(tmp_path, phase="IMPLEMENT")
        allowed, reason = check_write_allowed("src/app.py", cwd=str(tmp_path))
        assert allowed, f"Expected allowed, got: {reason}"

    def test_blocks_audit_dir_writes(self, tmp_path):
        """Active state → writes to .techne/audit/ blocked."""
        _create_state(tmp_path, phase="IMPLEMENT")
        allowed, reason = check_write_allowed(".techne/audit/chain.jsonl", cwd=str(tmp_path))
        assert not allowed
        assert "audit" in reason or "forbidden" in reason

    def test_allows_current_phase_artifact(self, tmp_path):
        """Writes to current phase artifact path allowed."""
        _create_state(tmp_path, phase="RECALL")
        allowed, reason = check_write_allowed(".techne/loop/recall.txt", cwd=str(tmp_path))
        assert allowed, f"Expected allowed, got: {reason}"

    def test_blocks_other_phase_artifact(self, tmp_path):
        """Writes to other phase's artifact path blocked."""
        _create_state(tmp_path, phase="RECALL")
        allowed, reason = check_write_allowed(".techne/loop/test_output.txt", cwd=str(tmp_path))
        assert not allowed
        assert "not the current phase artifact" in reason

    def test_blocks_diff_during_recall(self, tmp_path):
        """Writing diff.txt during RECALL is blocked."""
        _create_state(tmp_path, phase="RECALL")
        allowed, reason = check_write_allowed(".techne/loop/diff.txt", cwd=str(tmp_path))
        assert not allowed
        assert "not the current phase artifact" in reason

    def test_allows_diff_during_implement(self, tmp_path):
        """Writing diff.txt during IMPLEMENT is allowed."""
        _create_state(tmp_path, phase="IMPLEMENT")
        allowed, reason = check_write_allowed(".techne/loop/diff.txt", cwd=str(tmp_path))
        assert allowed, f"Expected allowed, got: {reason}"


class TestBlockedLog:
    def test_blocked_write_logged(self, tmp_path):
        """Blocked writes create entries in blocked.log."""
        (tmp_path / ".techne" / "loop").mkdir(parents=True)
        log_blocked("src/app.py", "No active pipeline", cwd=str(tmp_path))
        entries = get_blocked_log(cwd=str(tmp_path))
        assert len(entries) == 1
        assert entries[0]["path"] == "src/app.py"
        assert "No active pipeline" in entries[0]["reason"]
        assert "timestamp" in entries[0]

    def test_blocked_log_multiple_entries(self, tmp_path):
        """Multiple blocked writes accumulate."""
        (tmp_path / ".techne" / "loop").mkdir(parents=True)
        for path in ["a.py", "b.py", "c.py"]:
            log_blocked(path, "test", cwd=str(tmp_path))
        entries = get_blocked_log(cwd=str(tmp_path))
        assert len(entries) == 3

    def test_no_techne_no_blocked_log(self, tmp_path):
        """No .techne dir → get_blocked_log returns empty list."""
        entries = get_blocked_log(cwd=str(tmp_path))
        assert entries == []
