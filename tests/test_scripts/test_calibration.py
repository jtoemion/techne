"""Tests for scripts/calibration.py — W8 HITL-Removal Calibration."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import calibration


def _patch_paths(d: Path):
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        old_dir = calibration._CALIBRATION_DIR
        old_file = calibration._CALIBRATION_FILE
        old_root = calibration._ROOT
        calibration._CALIBRATION_DIR = d / ".techne" / "calibration"
        calibration._CALIBRATION_FILE = calibration._CALIBRATION_DIR / "calibration.jsonl"
        calibration._ROOT = d
        try:
            yield
        finally:
            calibration._CALIBRATION_DIR = old_dir
            calibration._CALIBRATION_FILE = old_file
            calibration._ROOT = old_root

    return _ctx()


def test_calibrate_gate_high_catch_rate_is_candidate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with _patch_paths(Path(tmp)):
            run = calibration.calibrate_gate(
                gate_name="test-gate",
                catch_rate=0.95,
                false_block_rate=0.02,
                corpus_size=100,
                catches=95,
                false_blocks=2,
            )
        assert run.verdict == "decommission_candidate"
        assert run.catch_rate == 0.95


def test_calibrate_gate_low_catch_rate_needs_work() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with _patch_paths(Path(tmp)):
            run = calibration.calibrate_gate(
                gate_name="weak-gate",
                catch_rate=0.40,
                false_block_rate=0.10,
                corpus_size=50,
                catches=20,
                false_blocks=5,
            )
        assert run.verdict == "needs_work"


def test_calibrate_gate_medium_keeps_calibrating() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with _patch_paths(Path(tmp)):
            run = calibration.calibrate_gate(
                gate_name="medium-gate",
                catch_rate=0.75,
                false_block_rate=0.03,
                corpus_size=100,
                catches=75,
                false_blocks=3,
            )
        assert run.verdict == "keep_calibrating"


def test_calibrate_gate_high_false_block_keeps_calibrating() -> None:
    """High catch_rate but high FBR → not yet decommissioned."""
    with tempfile.TemporaryDirectory() as tmp:
        with _patch_paths(Path(tmp)):
            run = calibration.calibrate_gate(
                gate_name="strict-gate",
                catch_rate=0.95,
                false_block_rate=0.10,   # too many false blocks
                corpus_size=100,
                catches=95,
                false_blocks=10,
            )
        assert run.verdict == "keep_calibrating"


def test_history_saves_and_loads() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with _patch_paths(Path(tmp)):
            calibration.calibrate_gate("g1", 0.92, 0.03, 50, 46, 1)
            calibration.calibrate_gate("g2", 0.60, 0.05, 50, 30, 2)
            history = calibration._load_calibration_history()
        assert len(history) == 2


def test_decommission_requires_candidate_verdict() -> None:
    """decommission_gate returns False if the last verdict is not 'decommission_candidate'."""
    with tempfile.TemporaryDirectory() as tmp:
        with _patch_paths(Path(tmp)):
            calibration.calibrate_gate("bad-gate", 0.60, 0.05, 50, 30, 2)
            result = calibration.decommission_gate("bad-gate")
        assert result is False


def test_decommission_succeeds_when_candidate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with _patch_paths(Path(tmp)):
            calibration.calibrate_gate("good-gate", 0.93, 0.02, 100, 93, 2)
            result = calibration.decommission_gate("good-gate")
        assert result is True
