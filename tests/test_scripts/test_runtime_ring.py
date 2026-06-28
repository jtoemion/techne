"""Tests for scripts/runtime_ring.py — W6 Runtime Ring."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import runtime_ring


def _patch_paths(d: Path):
    """Context manager: redirect runtime_ring paths to a temp dir."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        old_ring_dir = runtime_ring._RING_DIR
        old_state = runtime_ring._STATE_FILE
        old_incidents = runtime_ring._INCIDENTS_FILE
        old_context = runtime_ring._CONTEXT_DIR
        old_root = runtime_ring._ROOT
        runtime_ring._RING_DIR = d / ".techne" / "runtime_ring"
        runtime_ring._STATE_FILE = runtime_ring._RING_DIR / "state.json"
        runtime_ring._INCIDENTS_FILE = runtime_ring._RING_DIR / "incidents.jsonl"
        runtime_ring._CONTEXT_DIR = d / ".techne" / "context"
        runtime_ring._ROOT = d
        try:
            yield
        finally:
            runtime_ring._RING_DIR = old_ring_dir
            runtime_ring._STATE_FILE = old_state
            runtime_ring._INCIDENTS_FILE = old_incidents
            runtime_ring._CONTEXT_DIR = old_context
            runtime_ring._ROOT = old_root

    return _ctx()


# ── Snapshot ──────────────────────────────────────────────────────────────────

def test_snapshot_parses_pytest_output() -> None:
    output = "5 passed in 0.12s"
    total, passed, failed = runtime_ring._parse_test_output(output)
    assert total == 5
    assert passed == 5
    assert failed == 0


def test_snapshot_parses_failure() -> None:
    output = "3 passed, 2 failed in 0.20s"
    total, passed, failed = runtime_ring._parse_test_output(output)
    assert total == 5
    assert passed == 3
    assert failed == 2


def test_snapshot_save_and_load() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        with _patch_paths(d):
            snap = runtime_ring.HealthSnapshot(
                tag="v1.0",
                timestamp="2026-06-29T00:00:00Z",
                test_count=10,
                pass_count=10,
                fail_count=0,
                error_count=0,
                pass_rate=1.0,
                raw_output_sha="abc",
                test_cmd="pytest -q",
            )
            runtime_ring.save_snapshot(snap)
            loaded = runtime_ring.load_last_snapshot()

        assert loaded is not None
        assert loaded.tag == "v1.0"
        assert loaded.pass_rate == 1.0
        assert loaded.test_count == 10


def test_load_returns_none_when_no_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with _patch_paths(Path(tmp)):
            result = runtime_ring.load_last_snapshot()
    assert result is None


# ── Monitor ───────────────────────────────────────────────────────────────────

def test_monitor_healthy() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        with _patch_paths(d):
            # Save baseline: 10/10
            snap = runtime_ring.HealthSnapshot(
                tag="v1", timestamp="2026-06-29T00:00:00Z",
                test_count=10, pass_count=10, fail_count=0, error_count=0,
                pass_rate=1.0, raw_output_sha="x", test_cmd="pytest -q",
            )
            runtime_ring.save_snapshot(snap)

            # Simulate current: 10/10 still
            with patch.object(runtime_ring, "_run_tests",
                              return_value=("10 passed in 0.1s", 0)):
                result = runtime_ring.monitor("pytest -q", threshold=0.05)

        assert result.passed
        assert not result.requires_rollback
        assert result.delta >= 0


def test_monitor_regression_triggers_rollback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        with _patch_paths(d):
            # Baseline: 10/10 = 100%
            snap = runtime_ring.HealthSnapshot(
                tag="v1", timestamp="2026-06-29T00:00:00Z",
                test_count=10, pass_count=10, fail_count=0, error_count=0,
                pass_rate=1.0, raw_output_sha="x", test_cmd="pytest -q",
            )
            runtime_ring.save_snapshot(snap)

            # Current: 8/10 = 80% — delta = -0.20, threshold = 0.05 → rollback
            with patch.object(runtime_ring, "_run_tests",
                              return_value=("8 passed, 2 failed in 0.1s", 1)):
                result = runtime_ring.monitor("pytest -q", threshold=0.05)

        assert not result.passed
        assert result.requires_rollback
        assert result.delta < -0.05


def test_monitor_within_threshold_no_rollback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        with _patch_paths(d):
            # Baseline: 10/10 = 100%
            snap = runtime_ring.HealthSnapshot(
                tag="v1", timestamp="2026-06-29T00:00:00Z",
                test_count=10, pass_count=10, fail_count=0, error_count=0,
                pass_rate=1.0, raw_output_sha="x", test_cmd="pytest -q",
            )
            runtime_ring.save_snapshot(snap)

            # Current: 9/10 = 90% — delta = -0.10, but threshold = 0.15
            with patch.object(runtime_ring, "_run_tests",
                              return_value=("9 passed, 1 failed in 0.1s", 1)):
                result = runtime_ring.monitor("pytest -q", threshold=0.15)

        assert result.passed  # within threshold, no rollback
        assert not result.requires_rollback


def test_monitor_no_baseline_is_soft_pass() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with _patch_paths(Path(tmp)):
            result = runtime_ring.monitor("pytest -q")
        assert result.passed  # no baseline = soft pass with warning


# ── Incident log ─────────────────────────────────────────────────────────────

def test_incident_creates_okf_risk_note() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        with _patch_paths(d):
            risk_note = runtime_ring.log_incident(
                reason="pass_rate dropped 20%",
                current_pass_rate=0.80,
                baseline_pass_rate=1.00,
                baseline_tag="v1",
                rollback_target="v1",
            )

        assert risk_note.exists()
        content = risk_note.read_text(encoding="utf-8")
        assert "type: risk" in content
        assert "Runtime Ring Incident" in content
        assert "pass_rate dropped 20%" in content


def test_incident_appends_to_jsonl() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        with _patch_paths(d):
            runtime_ring.log_incident("r1", 0.8, 1.0, "v1")
            runtime_ring.log_incident("r2", 0.7, 1.0, "v1")
            lines = runtime_ring._INCIDENTS_FILE.read_text(encoding="utf-8").strip().splitlines()

        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["reason"] == "r1"
