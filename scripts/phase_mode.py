#!/usr/bin/env python3
"""phase_mode.py — W9 Edition Tiers (GRAND-PLAN-FINAL §9.13).

Tiers the gate rigor by task risk. A typo fix does not need the mutation gate
+ canary; a security change needs everything. This is the economic-viability
answer to §9.13: cache aggressively, tier by risk, fail fast on cheap gates.

Three tiers:

  FULL     — all gates: PBT + mutation + static + real tests + Runtime Ring canary
             Use for: security changes, auth, data migrations, public API
  STANDARD — standard gates: static + real tests, no mutation gate
             Use for: feature additions, bug fixes, refactors
  LITE     — minimal: artifact existence + real tests only
             Use for: typo fixes, doc changes, cosmetic refactors

Configured via .techne/config.yaml:
  phase_mode: FULL | STANDARD | LITE   (default: STANDARD)

Override per-invocation:
  techne next --phase-mode FULL

Gate inclusion matrix:
  Gate name               FULL  STANDARD  LITE
  ─────────────────────── ────  ────────  ────
  artifact_exists           ✓      ✓       ✓
  real tests (no_failures)  ✓      ✓       ✓
  pass_indicator            ✓      ✓       ✓
  non_empty_suite           ✓      ✓       ✓
  explicit_test_count       ✓      ✓       ✗
  no_forbidden_patterns     ✓      ✓       ✗
  scope_limit               ✓      ✓       ✗
  hashline                  ✓      ✓       ✗
  context_coverage          ✓      ✓       ✗
  static analysis / types   ✓      ✓       ✗
  mutation_strength (PBT)   ✓      ✗       ✗
  Runtime Ring canary       ✓      ✗       ✗
  separate-model verifier   ✓      ✗       ✗

Usage:
    from phase_mode import get_phase_mode, gate_enabled, PhaseMode
    mode = get_phase_mode()  # reads .techne/config.yaml
    if gate_enabled("mutation_strength", mode):
        run_mutation_gate()
"""
from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_CONFIG_PATH = _ROOT / ".techne" / "config.yaml"


class PhaseMode(str, Enum):
    FULL = "FULL"
    STANDARD = "STANDARD"
    LITE = "LITE"


# Gate inclusion matrix — True = gate runs in this mode
_GATE_MATRIX: dict[str, dict[str, bool]] = {
    # Core (always run)
    "artifact_exists":          {"FULL": True,  "STANDARD": True,  "LITE": True},
    "no_test_failures":         {"FULL": True,  "STANDARD": True,  "LITE": True},
    "pass_indicator":           {"FULL": True,  "STANDARD": True,  "LITE": True},
    "non_empty_suite":          {"FULL": True,  "STANDARD": True,  "LITE": True},
    # Standard tier
    "explicit_test_count":      {"FULL": True,  "STANDARD": True,  "LITE": False},
    "no_forbidden_patterns":    {"FULL": True,  "STANDARD": True,  "LITE": False},
    "scope_limit":              {"FULL": True,  "STANDARD": True,  "LITE": False},
    "hashline":                 {"FULL": True,  "STANDARD": True,  "LITE": False},
    "context_coverage":         {"FULL": True,  "STANDARD": True,  "LITE": False},
    "context_reference":        {"FULL": True,  "STANDARD": True,  "LITE": False},
    "file_scope_declared":      {"FULL": True,  "STANDARD": True,  "LITE": False},
    "context_recall_evidence":  {"FULL": True,  "STANDARD": True,  "LITE": False},
    "knowledge_graph_consulted":{"FULL": True,  "STANDARD": True,  "LITE": False},
    "node_discipline":          {"FULL": True,  "STANDARD": True,  "LITE": False},
    "retro_markers":            {"FULL": True,  "STANDARD": True,  "LITE": False},
    "verify_reference":         {"FULL": True,  "STANDARD": True,  "LITE": False},
    "honcho_reference":         {"FULL": True,  "STANDARD": True,  "LITE": False},
    # Full tier only (model-independent proof floor + ring)
    "mutation_strength":        {"FULL": True,  "STANDARD": False, "LITE": False},
    "runtime_ring_canary":      {"FULL": True,  "STANDARD": False, "LITE": False},
    "separate_model_verifier":  {"FULL": True,  "STANDARD": False, "LITE": False},
    "network_egress":           {"FULL": True,  "STANDARD": True,  "LITE": False},
    "filesystem_scope":         {"FULL": True,  "STANDARD": True,  "LITE": False},
    "secret_scan":              {"FULL": True,  "STANDARD": True,  "LITE": False},
    "config_protection":        {"FULL": True,  "STANDARD": True,  "LITE": False},
}

_MODE_DESCRIPTIONS = {
    PhaseMode.FULL: (
        "Full rigor: PBT + mutation gate + static analysis + real tests + Runtime Ring canary. "
        "Use for security changes, auth, data migrations, public API surface."
    ),
    PhaseMode.STANDARD: (
        "Standard rigor: static analysis + real tests + all phase gates. "
        "Use for feature additions, bug fixes, refactors. Default."
    ),
    PhaseMode.LITE: (
        "Minimal rigor: artifact existence + real tests only. "
        "Use for typo fixes, doc changes, cosmetic refactors."
    ),
}


def get_phase_mode(config_path: Path | None = None, override: str | None = None) -> PhaseMode:
    """Read the phase mode from config, CLI override, or default to STANDARD."""
    if override:
        try:
            return PhaseMode(override.upper())
        except ValueError:
            pass

    cfg = config_path or _CONFIG_PATH
    if cfg.exists():
        try:
            import yaml
            data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            mode_str = data.get("phase_mode", "STANDARD").upper()
            return PhaseMode(mode_str)
        except Exception:
            pass

    return PhaseMode.STANDARD


def gate_enabled(gate_name: str, mode: PhaseMode) -> bool:
    """Return True if a gate should run in the given mode."""
    row = _GATE_MATRIX.get(gate_name)
    if row is None:
        return True  # Unknown gates run by default (fail-closed principle)
    return row.get(mode.value, True)


def gates_for_mode(mode: PhaseMode) -> set[str]:
    """Return all gate names that run in the given mode."""
    return {name for name, row in _GATE_MATRIX.items() if row.get(mode.value, True)}


def skipped_gates(mode: PhaseMode) -> set[str]:
    """Return gates that are SKIPPED in the given mode."""
    return {name for name, row in _GATE_MATRIX.items() if not row.get(mode.value, True)}


def format_edition_table() -> str:
    """Format the edition-tier matrix for display."""
    lines = [
        "",
        "  Techne Editions — Gate Rigor Tiers",
        "  " + "=" * 70,
        f"  {'GATE':<32} {'FULL':<8} {'STANDARD':<10} {'LITE'}",
        "  " + "-" * 70,
    ]

    tier_order = [("Core", ["artifact_exists", "no_test_failures", "pass_indicator", "non_empty_suite"]),
                  ("Standard", ["explicit_test_count", "no_forbidden_patterns", "scope_limit",
                                "hashline", "context_coverage", "node_discipline",
                                "retro_markers", "verify_reference", "network_egress",
                                "filesystem_scope", "secret_scan", "config_protection"]),
                  ("Full (proof floor)", ["mutation_strength", "runtime_ring_canary",
                                          "separate_model_verifier"])]

    for tier_label, gate_names in tier_order:
        lines.append(f"  [{tier_label}]")
        for name in gate_names:
            row = _GATE_MATRIX.get(name, {"FULL": True, "STANDARD": True, "LITE": True})
            full = "✓" if row.get("FULL") else "—"
            std = "✓" if row.get("STANDARD") else "—"
            lite = "✓" if row.get("LITE") else "—"
            lines.append(f"  {name:<32} {full:<8} {std:<10} {lite}")

    lines += [
        "  " + "=" * 70,
        "",
        "  Set via .techne/config.yaml:  phase_mode: FULL | STANDARD | LITE",
        "  Override:  techne next --phase-mode FULL",
        "",
    ]

    for mode, desc in _MODE_DESCRIPTIONS.items():
        lines.append(f"  {mode.value}: {desc}")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import argparse
    p = argparse.ArgumentParser(description="Phase Mode Tiers — W9 Editions")
    p.add_argument("--show", action="store_true", help="Show the edition table")
    p.add_argument("--current", action="store_true", help="Show the current configured mode")
    p.add_argument("--check-gate", metavar="GATE", help="Check if a gate runs in the current mode")
    p.add_argument("--mode", default=None, help="Override mode for --check-gate")
    args = p.parse_args()

    mode = get_phase_mode(override=args.mode)

    if args.show:
        print(format_edition_table())
        return 0

    if args.current:
        print(f"  Current phase mode: {mode.value}")
        print(f"  {_MODE_DESCRIPTIONS[mode]}")
        skipped = skipped_gates(mode)
        if skipped:
            print(f"  Skipped gates ({len(skipped)}): {', '.join(sorted(skipped))}")
        return 0

    if args.check_gate:
        enabled = gate_enabled(args.check_gate, mode)
        print(f"  {args.check_gate}: {'ENABLED' if enabled else 'SKIPPED'} in {mode.value}")
        return 0 if enabled else 1

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
