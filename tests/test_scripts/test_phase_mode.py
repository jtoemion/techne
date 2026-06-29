"""Tests for scripts/phase_mode.py — W9 Edition Tiers."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from phase_mode import PhaseMode, gate_enabled, gates_for_mode, skipped_gates, get_phase_mode


# ── PhaseMode enum ────────────────────────────────────────────────────────────

def test_phase_mode_values() -> None:
    assert PhaseMode.FULL == "FULL"
    assert PhaseMode.STANDARD == "STANDARD"
    assert PhaseMode.LITE == "LITE"


# ── gate_enabled matrix ───────────────────────────────────────────────────────

def test_core_gates_always_enabled() -> None:
    for gate in ("artifact_exists", "no_test_failures", "pass_indicator", "non_empty_suite"):
        assert gate_enabled(gate, PhaseMode.FULL)
        assert gate_enabled(gate, PhaseMode.STANDARD)
        assert gate_enabled(gate, PhaseMode.LITE)


def test_mutation_only_in_full() -> None:
    assert gate_enabled("mutation_strength", PhaseMode.FULL)
    assert not gate_enabled("mutation_strength", PhaseMode.STANDARD)
    assert not gate_enabled("mutation_strength", PhaseMode.LITE)


def test_runtime_ring_canary_only_in_full() -> None:
    assert gate_enabled("runtime_ring_canary", PhaseMode.FULL)
    assert not gate_enabled("runtime_ring_canary", PhaseMode.STANDARD)
    assert not gate_enabled("runtime_ring_canary", PhaseMode.LITE)


def test_hashline_in_full_and_standard() -> None:
    assert gate_enabled("hashline", PhaseMode.FULL)
    assert gate_enabled("hashline", PhaseMode.STANDARD)
    assert not gate_enabled("hashline", PhaseMode.LITE)


def test_secret_scan_in_full_and_standard() -> None:
    assert gate_enabled("secret_scan", PhaseMode.FULL)
    assert gate_enabled("secret_scan", PhaseMode.STANDARD)
    assert not gate_enabled("secret_scan", PhaseMode.LITE)


def test_unknown_gate_is_enabled_by_default() -> None:
    """Fail-closed: an unknown gate name always runs."""
    assert gate_enabled("some_new_gate_we_havent_named", PhaseMode.LITE)
    assert gate_enabled("some_new_gate_we_havent_named", PhaseMode.STANDARD)


# ── gates_for_mode / skipped_gates ───────────────────────────────────────────

def test_full_has_more_gates_than_standard() -> None:
    full_gates = gates_for_mode(PhaseMode.FULL)
    std_gates = gates_for_mode(PhaseMode.STANDARD)
    assert len(full_gates) > len(std_gates)


def test_standard_has_more_gates_than_lite() -> None:
    std_gates = gates_for_mode(PhaseMode.STANDARD)
    lite_gates = gates_for_mode(PhaseMode.LITE)
    assert len(std_gates) > len(lite_gates)


def test_skipped_is_inverse_of_enabled() -> None:
    for mode in (PhaseMode.FULL, PhaseMode.STANDARD, PhaseMode.LITE):
        enabled = gates_for_mode(mode)
        skipped = skipped_gates(mode)
        assert enabled.isdisjoint(skipped)


def test_full_skips_nothing() -> None:
    assert len(skipped_gates(PhaseMode.FULL)) == 0


# ── get_phase_mode ────────────────────────────────────────────────────────────

def test_get_phase_mode_override() -> None:
    mode = get_phase_mode(override="FULL")
    assert mode == PhaseMode.FULL


def test_get_phase_mode_override_case_insensitive() -> None:
    mode = get_phase_mode(override="lite")
    assert mode == PhaseMode.LITE


def test_get_phase_mode_invalid_override_defaults_standard() -> None:
    mode = get_phase_mode(override="INVALID")
    assert mode == PhaseMode.STANDARD


def test_get_phase_mode_from_config_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.yaml"
        cfg.write_text("phase_mode: LITE\n", encoding="utf-8")
        mode = get_phase_mode(config_path=cfg)
    assert mode == PhaseMode.LITE


def test_get_phase_mode_defaults_to_standard_when_no_config() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        nonexistent = Path(tmp) / "missing.yaml"
        mode = get_phase_mode(config_path=nonexistent)
    assert mode == PhaseMode.STANDARD
