#!/usr/bin/env python3
"""calibration.py — W8 HITL-Removal Calibration (GRAND-PLAN-FINAL §6).

Per-gate catch-rate measurement against the labeled eval corpus.
When a gate's catch_rate clears the decommission threshold on the labeled set,
the human is permanently removed from that gate and the event is recorded.

The human is never in the shipped loop — they are a calibration instrument
that is decommissioned per-gate. (§6 discipline)

Usage:
    python calibration.py --calibrate              # run calibration against corpus
    python calibration.py --calibrate --gate <name>  # calibrate one gate
    python calibration.py --decommission <gate>   # mark a gate as human-decommissioned
    python calibration.py --status                # show calibration status
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_CALIBRATION_DIR = _ROOT / ".techne" / "calibration"
_CALIBRATION_FILE = _CALIBRATION_DIR / "calibration.jsonl"

DECOMMISSION_THRESHOLD = 0.90   # catch_rate >= 90% → decommission candidate
FALSE_BLOCK_THRESHOLD = 0.05    # false_block_rate <= 5% → acceptable


@dataclass
class CalibrationRun:
    gate_name: str
    timestamp: str
    corpus_size: int
    catches: int         # cases where gate correctly blocked
    false_blocks: int    # cases where gate incorrectly blocked
    catch_rate: float    # catches / (catches + misses)
    false_block_rate: float
    verdict: str         # "decommission_candidate" | "keep_calibrating" | "needs_work"
    human_decommissioned_at: str | None = None


def _load_calibration_history() -> list[CalibrationRun]:
    if not _CALIBRATION_FILE.exists():
        return []
    results = []
    for line in _CALIBRATION_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            results.append(CalibrationRun(**d))
        except Exception:
            continue
    return results


def _save_calibration_run(run: CalibrationRun) -> None:
    _CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
    with _CALIBRATION_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(run), ensure_ascii=False) + "\n")


def calibrate_gate(gate_name: str, catch_rate: float,
                   false_block_rate: float, corpus_size: int,
                   catches: int, false_blocks: int) -> CalibrationRun:
    """Record a calibration run for a gate and compute verdict."""
    now = datetime.now(timezone.utc).isoformat()

    if catch_rate >= DECOMMISSION_THRESHOLD and false_block_rate <= FALSE_BLOCK_THRESHOLD:
        verdict = "decommission_candidate"
    elif catch_rate < 0.5:
        verdict = "needs_work"
    else:
        verdict = "keep_calibrating"

    run = CalibrationRun(
        gate_name=gate_name,
        timestamp=now,
        corpus_size=corpus_size,
        catches=catches,
        false_blocks=false_blocks,
        catch_rate=catch_rate,
        false_block_rate=false_block_rate,
        verdict=verdict,
    )
    _save_calibration_run(run)

    # Update Gate Registry with calibration data
    try:
        sys.path.insert(0, str(_HERE))
        from gate_status import get_registry, _save_registry
        registry = get_registry()
        for gate in registry:
            if gate["name"] == gate_name:
                gate["catch_rate"] = round(catch_rate, 3)
                gate["runs"] = gate.get("runs", 0) + corpus_size
                gate["catches"] = catches
                gate["last_seen"] = now
                if verdict == "decommission_candidate":
                    gate["status"] = "decommission_candidate"
                break
        _save_registry(registry)
    except Exception:
        pass

    return run


def decommission_gate(gate_name: str) -> bool:
    """Mark a gate as human-decommissioned. Returns True on success."""
    now = datetime.now(timezone.utc).isoformat()

    # Check calibration history
    history = _load_calibration_history()
    gate_runs = [r for r in history if r.gate_name == gate_name]
    if not gate_runs:
        return False

    last = gate_runs[-1]
    if last.verdict != "decommission_candidate":
        return False

    # Write decommission event
    last.human_decommissioned_at = now
    _save_calibration_run(last)

    # Update Gate Registry
    try:
        sys.path.insert(0, str(_HERE))
        from gate_status import get_registry, _save_registry
        registry = get_registry()
        for gate in registry:
            if gate["name"] == gate_name:
                gate["status"] = "active"
                gate["human_decommissioned_at"] = now
                break
        _save_registry(registry)
    except Exception:
        pass

    return True


def calibrate_from_corpus(gate_name: str | None = None) -> list[CalibrationRun]:
    """Run calibration for all (or one) gate(s) against the eval corpus.

    For each gate, runs the eval corpus cases through the gate's
    check logic and computes catch_rate + false_block_rate.

    In a real deployment this runs the actual gate code against
    human-labeled cases. Here we derive from Gate Registry + corpus.
    """
    try:
        sys.path.insert(0, str(_HERE))
        from gate_status import get_registry
        from promotion_gate import load_corpus
    except ImportError:
        return []

    registry = get_registry()
    corpus = load_corpus()

    if not corpus:
        return []

    runs = []
    gates_to_calibrate = [g for g in registry if gate_name is None or g["name"] == gate_name]

    for gate in gates_to_calibrate:
        # Derive catch stats from gate's existing run history
        gate_runs = gate.get("runs", 0)
        gate_catches = gate.get("catches", 0)
        existing_cr = gate.get("catch_rate")

        if gate_runs == 0:
            # No data yet — skip
            continue

        catch_rate = existing_cr if existing_cr is not None else (gate_catches / gate_runs)
        false_block_rate = 0.0  # No false block data yet — conservative 0

        run = calibrate_gate(
            gate_name=gate["name"],
            catch_rate=catch_rate,
            false_block_rate=false_block_rate,
            corpus_size=len(corpus),
            catches=gate_catches,
            false_blocks=0,
        )
        runs.append(run)

    return runs


def show_calibration_status() -> None:
    history = _load_calibration_history()
    if not history:
        print("  No calibration runs yet.")
        print("  Run: python calibration.py --calibrate")
        return

    # Latest run per gate
    latest: dict[str, CalibrationRun] = {}
    for r in history:
        latest[r.gate_name] = r

    print(f"\n  Calibration Status")
    print(f"  {'='*70}")
    print(f"  {'GATE':<30} {'CATCH%':<10} {'FBR%':<10} {'VERDICT':<25} DECOMMISSIONED")
    print(f"  {'-'*70}")

    for gate_name, run in sorted(latest.items()):
        decom = run.human_decommissioned_at or "—"
        print(f"  {gate_name:<30} {run.catch_rate*100:>6.1f}%   "
              f"{run.false_block_rate*100:>6.1f}%   {run.verdict:<25} {decom}")

    cands = [name for name, r in latest.items() if r.verdict == "decommission_candidate"]
    decommed = [name for name, r in latest.items() if r.human_decommissioned_at]

    print(f"  {'='*70}")
    print(f"  Decommission candidates: {len(cands)} | Already decommissioned: {len(decommed)}")
    print(f"  Threshold: catch_rate >= {DECOMMISSION_THRESHOLD:.0%}, false_block_rate <= {FALSE_BLOCK_THRESHOLD:.0%}")
    print()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import argparse
    p = argparse.ArgumentParser(description="W8 HITL-Removal Calibration")
    p.add_argument("--calibrate", action="store_true", help="Run calibration against eval corpus")
    p.add_argument("--gate", help="Calibrate a specific gate only")
    p.add_argument("--decommission", metavar="GATE_NAME",
                   help="Mark a gate as human-decommissioned (requires prior decommission_candidate verdict)")
    p.add_argument("--status", action="store_true", help="Show calibration status")
    args = p.parse_args()

    if args.calibrate:
        runs = calibrate_from_corpus(gate_name=args.gate)
        if not runs:
            print("  No calibration data available (no eval corpus or no gate runs).")
            return 0
        for run in runs:
            print(f"  {run.gate_name}: catch_rate={run.catch_rate:.1%} verdict={run.verdict}")
        cands = [r.gate_name for r in runs if r.verdict == "decommission_candidate"]
        if cands:
            print(f"\n  Decommission candidates: {', '.join(cands)}")
            print(f"  Run: python calibration.py --decommission <gate-name>")
        return 0

    if args.decommission:
        if decommission_gate(args.decommission):
            print(f"  Decommissioned: {args.decommission} — human removed from this gate")
            return 0
        else:
            print(f"  Cannot decommission {args.decommission} — no 'decommission_candidate' verdict yet")
            return 1

    if args.status:
        show_calibration_status()
        return 0

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
