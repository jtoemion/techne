"""Tests for scripts/watchdog.py"""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import watchdog


def _create_state(techne_root: Path, phase="RECALL", task_id="test-1", updated_mins_ago=0, timeout_min=30):
    """Create a state.json at .techne/loop/state.json."""
    loop_dir = techne_root / ".techne" / "loop"
    loop_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    if updated_mins_ago > 0:
        from datetime import timedelta
        updated = now - timedelta(minutes=updated_mins_ago)
    else:
        updated = now

    state = {
        "task_id": task_id,
        "phase": phase,
        "created_at": now.isoformat(),
        "updated_at": updated.isoformat(),
        "phase_timeout_min": timeout_min,
        "summary": "",
    }

    state_path = loop_dir / "state.json"
    state_path.write_text(json.dumps(state, indent=2))
    return state


def _create_chain(techne_root: Path, entries: list[dict]):
    """Create a chain.jsonl with the given entries, properly hash-chained."""
    audit_dir = techne_root / ".techne" / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    chain_path = audit_dir / "chain.jsonl"

    prev_hash = "0" * 64
    lines = []
    for i, entry_data in enumerate(entries):
        entry_data["seq"] = i + 1
        entry_data["prev_hash"] = prev_hash
        # Compute entry_hash (exclude entry_hash from the hash)
        d = {k: v for k, v in entry_data.items() if k != "entry_hash"}
        payload = json.dumps(d, sort_keys=True)
        entry_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        entry_data["entry_hash"] = entry_hash
        lines.append(json.dumps(entry_data, sort_keys=True))
        prev_hash = entry_hash

    chain_path.write_text("\n".join(lines) + "\n")


def _make_entry(phase="RECALL", task_id="test-1", summary="test"):
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_id": task_id,
        "phase": phase,
        "gates": [{"name": "exists", "passed": True, "detail": "ok"}],
        "summary": summary,
    }


class TestHealthy:
    def test_no_state_no_techne(self, tmp_path):
        """No .techne directory at all → exit 0."""
        code = watchdog.main(cwd=tmp_path)
        assert code == 0

    def test_no_state_with_techne(self, tmp_path):
        """.techne/ exists but no state.json → exit 0 (nothing running)."""
        (tmp_path / ".techne" / "loop").mkdir(parents=True)
        code = watchdog.main(cwd=tmp_path)
        assert code == 0

    def test_recent_state_healthy(self, tmp_path):
        """State updated 1 min ago → exit 0."""
        _create_state(tmp_path, phase="IMPLEMENT", updated_mins_ago=1, timeout_min=30)
        _create_chain(tmp_path, [_make_entry("RECALL"), _make_entry("IMPLEMENT")])
        code = watchdog.main(cwd=tmp_path)
        assert code == 0

    def test_done_no_stall(self, tmp_path):
        """DONE phase with old timestamp → exit 0 (completed, not stalled)."""
        _create_state(tmp_path, phase="DONE", updated_mins_ago=60, timeout_min=30)
        _create_chain(tmp_path, [_make_entry("RECALL"), _make_entry("IMPLEMENT"), _make_entry("VERIFY"), _make_entry("CONCLUDE"), _make_entry("DONE")])
        code = watchdog.main(cwd=tmp_path)
        assert code == 0


class TestStall:
    def test_stall_detected(self, tmp_path):
        """State updated 120 min ago with 30 min timeout → exit 1."""
        state = _create_state(tmp_path, phase="IMPLEMENT", updated_mins_ago=120, timeout_min=30)
        _create_chain(tmp_path, [_make_entry("RECALL"), _make_entry("IMPLEMENT")])
        code = watchdog.main(cwd=tmp_path)
        assert code == 1

    def test_stall_just_under_timeout(self, tmp_path):
        """State updated 25 min ago with 30 min timeout → exit 0."""
        _create_state(tmp_path, phase="IMPLEMENT", updated_mins_ago=25, timeout_min=30)
        _create_chain(tmp_path, [_make_entry("RECALL"), _make_entry("IMPLEMENT")])
        code = watchdog.main(cwd=tmp_path)
        assert code == 0


class TestTamper:
    def test_tamper_detected(self, tmp_path):
        """Broken hash in chain → exit 2."""
        _create_state(tmp_path, phase="VERIFY", updated_mins_ago=1, timeout_min=30)
        _create_chain(tmp_path, [_make_entry("RECALL"), _make_entry("IMPLEMENT")])
        # Tamper with chain
        chain_path = tmp_path / ".techne" / "audit" / "chain.jsonl"
        content = chain_path.read_text()
        content = content.replace("RECALL", "TAMPERED")
        chain_path.write_text(content)
        code = watchdog.main(cwd=tmp_path)
        assert code == 2


class TestSkip:
    def test_skip_detected(self, tmp_path):
        """State says VERIFY but chain has no VERIFY entry → exit 3."""
        _create_state(tmp_path, phase="VERIFY", updated_mins_ago=1, timeout_min=30)
        _create_chain(tmp_path, [_make_entry("RECALL")])  # only RECALL in chain
        code = watchdog.main(cwd=tmp_path)
        assert code == 3


class TestOrphan:
    def test_orphan_detected(self, tmp_path):
        """No state.json but recent task dirs → exit 4."""
        tasks_dir = tmp_path / ".techne" / "tasks"
        tasks_dir.mkdir(parents=True)
        task_subdir = tasks_dir / "abc123"
        task_subdir.mkdir()
        code = watchdog.main(cwd=tmp_path)
        assert code == 4
