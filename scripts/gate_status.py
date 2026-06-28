#!/usr/bin/env python3
"""gate_status.py — Gate Registry persistence and display (GRAND-PLAN-FINAL).

Maintains .techne/gates/registry.json — the audit-visible record of every gate:
  name, kind, provenance, status, catch_rate, last_seen

Kind taxonomy (from GRAND-PLAN-FINAL trust hierarchy):
  pbt        — property-based test or static analysis (model-independent floor)
  mechanical  — SHA gate, mutation gate, secret scan, forbidden patterns
  llm_judge  — LLM-evaluated gate (last resort)

Usage:
    python gate_status.py                       # list all gates
    python gate_status.py --json                # JSON output
    python gate_status.py --record <name> <caught|passed>
                                                # record a gate outcome
    python gate_status.py --register <name> --kind mechanical --provenance builtin
                                                # register a new gate
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_REGISTRY_PATH = _ROOT / ".techne" / "gates" / "registry.json"

# ── Built-in gate catalogue ───────────────────────────────────────────────────
# These are always registered; custom gates can be added via --register.
_BUILTIN_GATES: list[dict] = [
    # Phase gates (mechanical — run on phase artifacts)
    {"name": "artifact_exists",      "kind": "mechanical", "phase": "all",       "description": "phase artifact file exists and is non-empty"},
    {"name": "no_forbidden_patterns","kind": "mechanical", "phase": "IMPLEMENT",  "description": "no TODO/console.log/debugger in added lines"},
    {"name": "scope_limit",          "kind": "mechanical", "phase": "IMPLEMENT",  "description": "diff touches <= scope_limit files"},
    {"name": "hashline",             "kind": "mechanical", "phase": "IMPLEMENT",  "description": "diff context lines match real file bytes"},
    {"name": "no_test_failures",     "kind": "mechanical", "phase": "VERIFY",     "description": "test output has no FAILED/ERROR lines"},
    {"name": "pass_indicator",       "kind": "mechanical", "phase": "VERIFY",     "description": "test output has a pass signal"},
    {"name": "non_empty_suite",      "kind": "mechanical", "phase": "VERIFY",     "description": "at least one test ran (0 tests = soft gate)"},
    {"name": "explicit_test_count",  "kind": "mechanical", "phase": "VERIFY",     "description": "test output shows N passed"},
    {"name": "retro_markers",        "kind": "mechanical", "phase": "CONCLUDE",   "description": "conclude.txt has DECISION/LESSON/DISCIPLINE markers"},
    {"name": "verify_reference",     "kind": "mechanical", "phase": "CONCLUDE",   "description": "conclude.txt references test results"},
    {"name": "honcho_reference",     "kind": "mechanical", "phase": "CONCLUDE",   "description": "conclude.txt has HONCHO: line"},
    # Proof Spine gates (model-independent)
    {"name": "mutation_strength",    "kind": "pbt",        "phase": "VERIFY",     "description": "mutation gate: tests kill every mutant (W3 Proof Spine)"},
    {"name": "node_discipline",      "kind": "pbt",        "phase": "VERIFY",     "description": "module boundary discipline check"},
    # Boundary gates (W1)
    {"name": "network_egress",       "kind": "mechanical", "phase": "tool_call",  "description": "L1: blocks outbound network in bash commands"},
    {"name": "filesystem_scope",     "kind": "mechanical", "phase": "tool_call",  "description": "L2: blocks writes outside project root"},
    {"name": "secret_scan",          "kind": "mechanical", "phase": "tool_call",  "description": "L3: blocks credential patterns in written content"},
    {"name": "config_protection",    "kind": "mechanical", "phase": "tool_call",  "description": "L4: blocks writes to boundary-critical config files"},
    # Context gates (W2)
    {"name": "context_coverage",     "kind": "pbt",        "phase": "RECALL",     "description": "changed files have .techne/context/ coverage"},
    # RECALL evidence gates
    {"name": "context_reference",    "kind": "mechanical", "phase": "RECALL",     "description": "recall.txt references .techne/context/"},
    {"name": "file_scope_declared",  "kind": "mechanical", "phase": "RECALL",     "description": "recall.txt has FILE_SCOPE: line"},
    {"name": "context_recall_evidence","kind": "mechanical","phase": "RECALL",    "description": "recall.txt has HONCHO_CONTEXT: or WORKSHOP_CONTEXT: line"},
    {"name": "knowledge_graph_consulted","kind":"mechanical","phase": "RECALL",   "description": "recall.txt references knowledge graph"},
]


def _load_registry() -> list[dict]:
    """Load current registry from disk, or return empty list."""
    if not _REGISTRY_PATH.exists():
        return []
    try:
        return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_registry(gates: list[dict]) -> None:
    _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REGISTRY_PATH.write_text(
        json.dumps(gates, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _ensure_builtins(registry: list[dict]) -> list[dict]:
    """Merge builtin gates into registry without overwriting runtime state."""
    names = {g["name"] for g in registry}
    for builtin in _BUILTIN_GATES:
        if builtin["name"] not in names:
            registry.append({
                **builtin,
                "status": "active",
                "provenance": "builtin",
                "catch_rate": None,   # null until we have data
                "runs": 0,
                "catches": 0,
                "last_seen": None,
            })
    return registry


def get_registry() -> list[dict]:
    """Load registry, merge builtins, save if updated, return all gates."""
    current = _load_registry()
    merged = _ensure_builtins(current)
    _save_registry(merged)
    return merged


def record_outcome(gate_name: str, caught: bool) -> None:
    """Record a gate run outcome (caught = gate fired / caught a violation)."""
    registry = get_registry()
    for gate in registry:
        if gate["name"] == gate_name:
            gate["runs"] = gate.get("runs", 0) + 1
            if caught:
                gate["catches"] = gate.get("catches", 0) + 1
            runs = gate["runs"]
            catches = gate.get("catches", 0)
            gate["catch_rate"] = round(catches / runs, 3) if runs else None
            gate["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            break
    _save_registry(registry)


def register_gate(name: str, kind: str, provenance: str = "custom",
                  phase: str = "unknown", description: str = "") -> None:
    """Add or update a gate in the registry."""
    registry = _load_registry()
    names = {g["name"] for g in registry}
    if name not in names:
        registry.append({
            "name": name,
            "kind": kind,
            "provenance": provenance,
            "phase": phase,
            "description": description,
            "status": "active",
            "catch_rate": None,
            "runs": 0,
            "catches": 0,
            "last_seen": None,
        })
    else:
        for gate in registry:
            if gate["name"] == name:
                gate.update({"kind": kind, "provenance": provenance,
                             "phase": phase, "description": description})
    _save_registry(registry)


def format_registry(gates: list[dict], json_output: bool = False) -> str:
    """Format the registry for display."""
    if json_output:
        return json.dumps(gates, indent=2, ensure_ascii=False)

    if not gates:
        return "  No gates registered. Run `techne gates` after a pipeline run."

    lines = [
        "",
        "  Gate Registry",
        "  " + "=" * 70,
        f"  {'NAME':<30} {'KIND':<12} {'PHASE':<12} {'STATUS':<12} {'CATCH%'}",
        "  " + "-" * 70,
    ]

    kind_order = {"pbt": 0, "mechanical": 1, "llm_judge": 2}
    for g in sorted(gates, key=lambda x: (kind_order.get(x.get("kind", ""), 3), x["name"])):
        name = g["name"][:28]
        kind = g.get("kind", "?")[:10]
        phase = g.get("phase", "?")[:10]
        status = g.get("status", "?")[:10]
        cr = g.get("catch_rate")
        cr_str = f"{cr*100:.0f}%" if cr is not None else "n/a"
        lines.append(f"  {name:<30} {kind:<12} {phase:<12} {status:<12} {cr_str}")

    lines += [
        "  " + "=" * 70,
        f"  {len(gates)} gate(s) registered",
        "",
        "  Kind legend: pbt=model-independent floor | mechanical=execution proof | llm_judge=last resort",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import argparse
    p = argparse.ArgumentParser(description="Gate Registry (GRAND-PLAN-FINAL)")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--record", nargs=2, metavar=("NAME", "OUTCOME"),
                   help="Record a gate outcome: caught|passed")
    p.add_argument("--register", metavar="NAME", help="Register a new gate")
    p.add_argument("--kind", default="mechanical",
                   choices=["pbt", "mechanical", "llm_judge"])
    p.add_argument("--provenance", default="custom")
    p.add_argument("--phase", default="unknown")
    p.add_argument("--description", default="")
    args = p.parse_args()

    if args.record:
        name, outcome = args.record
        if outcome not in ("caught", "passed"):
            print(f"outcome must be 'caught' or 'passed', got: {outcome}")
            return 1
        record_outcome(name, caught=(outcome == "caught"))
        print(f"  Recorded: {name} -> {outcome}")
        return 0

    if args.register:
        register_gate(args.register, args.kind, args.provenance,
                      args.phase, args.description)
        print(f"  Registered: {args.register} ({args.kind})")
        return 0

    registry = get_registry()
    print(format_registry(registry, args.json))
    return 0


if __name__ == "__main__":
    sys.exit(main())
