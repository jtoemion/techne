"""Tests for scripts/failure_disposition.py — W8b Autonomous Failure Disposition."""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import failure_disposition


def _make_state(d: Path, phase: str, minutes_stale: float,
                timeout_min: float = 60, retry_count: int = 0) -> Path:
    """Write a .techne/loop/state.json for testing."""
    loop_dir = d / ".techne" / "loop"
    loop_dir.mkdir(parents=True, exist_ok=True)
    state_file = loop_dir / "state.json"
    updated = datetime.now(timezone.utc) - timedelta(minutes=minutes_stale)
    state = {
        "task_id": "test-task-001",
        "phase": phase,
        "updated_at": updated.isoformat(),
        "phase_timeout_min": timeout_min,
        "retry_count": retry_count,
    }
    state_file.write_text(json.dumps(state), encoding="utf-8")
    return state_file


def _patch_log(d: Path):
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        old = failure_disposition._DISPOSITION_LOG
        failure_disposition._DISPOSITION_LOG = d / ".techne" / "events" / "dispositions.jsonl"
        try:
            yield
        finally:
            failure_disposition._DISPOSITION_LOG = old

    return _ctx()


# ── StallCheck ────────────────────────────────────────────────────────────────

def test_no_stall_when_fresh() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _make_state(d, "VERIFY", minutes_stale=5, timeout_min=60)
        stall = failure_disposition.check_stall(d)
    assert stall is not None
    assert not stall.is_stalled


def test_stall_detected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _make_state(d, "VERIFY", minutes_stale=90, timeout_min=60)
        stall = failure_disposition.check_stall(d)
    assert stall is not None
    assert stall.is_stalled


def test_no_pipeline_returns_none() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        stall = failure_disposition.check_stall(Path(tmp))
    assert stall is None


def test_done_phase_returns_none() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _make_state(d, "DONE", minutes_stale=90)
        stall = failure_disposition.check_stall(d)
    assert stall is None


# ── Disposition actions ───────────────────────────────────────────────────────

def test_retry_recommended_when_few_retries() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _make_state(d, "IMPLEMENT", minutes_stale=90, timeout_min=60, retry_count=0)
        stall = failure_disposition.check_stall(d)
    assert stall is not None
    assert stall.recommended_disposition == "RETRY"


def test_decompose_after_max_retries_in_implement() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _make_state(d, "IMPLEMENT", minutes_stale=90, timeout_min=60, retry_count=2)
        stall = failure_disposition.check_stall(d)
    assert stall is not None
    assert stall.recommended_disposition == "DECOMPOSE"


def test_partial_after_max_retries_in_verify() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _make_state(d, "VERIFY", minutes_stale=90, timeout_min=60, retry_count=2)
        stall = failure_disposition.check_stall(d)
    assert stall is not None
    assert stall.recommended_disposition == "PARTIAL"


def test_incident_after_max_retries_in_conclude() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _make_state(d, "CONCLUDE", minutes_stale=90, timeout_min=60, retry_count=2)
        stall = failure_disposition.check_stall(d)
    assert stall is not None
    assert stall.recommended_disposition == "INCIDENT"


# ── Disposition execution ─────────────────────────────────────────────────────

def test_dispose_retry_bumps_count() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _make_state(d, "RECALL", minutes_stale=90, timeout_min=60, retry_count=0)
        stall = failure_disposition.check_stall(d)
        assert stall is not None
        with _patch_log(d):
            event = failure_disposition.dispose(stall, d)
        assert event.action == "RETRY"
        # retry_count bumped in state
        state = json.loads((d / ".techne" / "loop" / "state.json").read_text())
        assert state["retry_count"] == 1


def test_dispose_incident_writes_okf_note() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _make_state(d, "CONCLUDE", minutes_stale=90, timeout_min=60, retry_count=2)
        stall = failure_disposition.check_stall(d)
        assert stall is not None
        with _patch_log(d):
            event = failure_disposition.dispose(stall, d)
        assert event.action == "INCIDENT"
        if event.okf_risk_note:
            assert Path(event.okf_risk_note).exists()


def test_disposition_logged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _make_state(d, "RECALL", minutes_stale=90, timeout_min=60, retry_count=0)
        stall = failure_disposition.check_stall(d)
        with _patch_log(d):
            failure_disposition.dispose(stall, d)
            events = failure_disposition.load_disposition_log(d)
        assert len(events) == 1
        assert events[0].action == "RETRY"
