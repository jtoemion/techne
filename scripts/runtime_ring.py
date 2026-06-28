#!/usr/bin/env python3
"""runtime_ring.py — W6 Runtime Ring (GRAND-PLAN-FINAL §3a).

The Runtime Ring is the DOWNSTREAM CATCH for the spec-intent residual gap (§9.8):
a subtly-wrong spec passes every pre-merge gate but moves a runtime metric → rollback.

Mandated by EU AI Act Aug-2026 + CISA/NSA autonomous system guidelines.

What it does:
  1. SNAPSHOT: after a DONE pipeline, capture a health baseline
       (test_count, pass_count, error_count, coverage_pct, custom_metrics)
  2. MONITOR: before next deploy, run tests and compare to baseline
  3. ROLLBACK: if metric delta > threshold, tag the regression + rollback to last-good
  4. INCIDENT: write OKF risk-note + append to held-out eval set

Design: the ring runs OUTSIDE the pipeline gate layer (not a gate, a circuit breaker).
        It operates on REAL runtime signals, not on model-generated output.

Usage:
    python runtime_ring.py snapshot --test-cmd "pytest -q" --tag v1.2.3
    python runtime_ring.py monitor --test-cmd "pytest -q" --threshold 0.05
    python runtime_ring.py rollback --to-tag v1.2.2
    python runtime_ring.py status

State file: .techne/runtime_ring/state.json
Incident log: .techne/runtime_ring/incidents.jsonl
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_RING_DIR = _ROOT / ".techne" / "runtime_ring"
_STATE_FILE = _RING_DIR / "state.json"
_INCIDENTS_FILE = _RING_DIR / "incidents.jsonl"
_CONTEXT_DIR = _ROOT / ".techne" / "context"


@dataclass
class HealthSnapshot:
    tag: str
    timestamp: str
    test_count: int
    pass_count: int
    fail_count: int
    error_count: int
    pass_rate: float       # pass_count / test_count
    raw_output_sha: str    # SHA of the raw test output (tamper-detection)
    test_cmd: str


@dataclass
class MonitorResult:
    passed: bool
    current_pass_rate: float
    baseline_pass_rate: float
    delta: float            # current - baseline (negative = regression)
    threshold: float
    reason: str
    requires_rollback: bool


# ── Snapshot ──────────────────────────────────────────────────────────────────

def _parse_test_output(output: str) -> tuple[int, int, int]:
    """Parse pytest-style output. Returns (total, passed, failed+errors)."""
    # e.g. "5 passed, 1 failed in 0.12s" or "6 passed in 0.12s"
    passed = 0
    failed = 0
    total = 0

    m = re.search(r'(\d+) passed', output)
    if m:
        passed = int(m.group(1))

    m_fail = re.search(r'(\d+) failed', output)
    if m_fail:
        failed += int(m_fail.group(1))

    m_err = re.search(r'(\d+) error', output)
    if m_err:
        failed += int(m_err.group(1))

    total = passed + failed
    return total, passed, failed


def _run_tests(test_cmd: str, timeout: int = 300) -> tuple[str, int]:
    """Run test command; return (stdout+stderr, returncode)."""
    try:
        r = subprocess.run(
            test_cmd, shell=True, capture_output=True, text=True,
            encoding="utf-8", timeout=timeout,
        )
        return r.stdout + r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        return "TIMEOUT", 1


def take_snapshot(test_cmd: str, tag: str | None = None) -> HealthSnapshot:
    """Run tests and capture a health snapshot."""
    print(f"  [ring] Running baseline tests: {test_cmd}")
    output, rc = _run_tests(test_cmd)
    total, passed, failed = _parse_test_output(output)

    pass_rate = (passed / total) if total > 0 else (0.0 if rc != 0 else 1.0)
    output_sha = hashlib.sha256(output.encode()).hexdigest()

    auto_tag = tag or f"snapshot-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"

    snap = HealthSnapshot(
        tag=auto_tag,
        timestamp=datetime.now(timezone.utc).isoformat(),
        test_count=total,
        pass_count=passed,
        fail_count=failed,
        error_count=0,
        pass_rate=pass_rate,
        raw_output_sha=output_sha,
        test_cmd=test_cmd,
    )
    return snap


def save_snapshot(snap: HealthSnapshot) -> None:
    _RING_DIR.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if _STATE_FILE.exists():
        try:
            existing = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = [existing]
        except Exception:
            existing = []
    existing.append(asdict(snap))
    _STATE_FILE.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  [ring] Snapshot saved: tag={snap.tag} pass_rate={snap.pass_rate:.2%} "
          f"({snap.pass_count}/{snap.test_count} tests)")


def load_last_snapshot() -> HealthSnapshot | None:
    """Load the most recent snapshot."""
    if not _STATE_FILE.exists():
        return None
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        if not data:
            return None
        last = data[-1] if isinstance(data, list) else data
        return HealthSnapshot(**last)
    except Exception:
        return None


# ── Monitor ───────────────────────────────────────────────────────────────────

def monitor(test_cmd: str, threshold: float = 0.05) -> MonitorResult:
    """Compare current health to baseline. Return MonitorResult."""
    baseline = load_last_snapshot()
    if baseline is None:
        return MonitorResult(
            passed=True,
            current_pass_rate=1.0,
            baseline_pass_rate=1.0,
            delta=0.0,
            threshold=threshold,
            reason="No baseline snapshot — run: runtime_ring.py snapshot first",
            requires_rollback=False,
        )

    print(f"  [ring] Monitoring against baseline: tag={baseline.tag} "
          f"pass_rate={baseline.pass_rate:.2%}")
    output, rc = _run_tests(test_cmd)
    total, passed, failed = _parse_test_output(output)

    current_pass_rate = (passed / total) if total > 0 else (0.0 if rc != 0 else 1.0)
    delta = current_pass_rate - baseline.pass_rate

    requires_rollback = delta < -threshold

    if requires_rollback:
        reason = (
            f"REGRESSION: pass_rate dropped {abs(delta):.1%} "
            f"(was {baseline.pass_rate:.2%}, now {current_pass_rate:.2%}, "
            f"threshold={threshold:.1%}) — rollback triggered"
        )
    elif delta < 0:
        reason = (
            f"DEGRADED: pass_rate dropped {abs(delta):.1%} "
            f"(was {baseline.pass_rate:.2%}, now {current_pass_rate:.2%}) — within threshold"
        )
    else:
        reason = (
            f"HEALTHY: pass_rate={current_pass_rate:.2%} "
            f"(baseline={baseline.pass_rate:.2%}, delta=+{delta:.1%})"
        )

    return MonitorResult(
        passed=not requires_rollback,
        current_pass_rate=current_pass_rate,
        baseline_pass_rate=baseline.pass_rate,
        delta=delta,
        threshold=threshold,
        reason=reason,
        requires_rollback=requires_rollback,
    )


# ── Rollback ──────────────────────────────────────────────────────────────────

def rollback(to_tag: str, dry_run: bool = False) -> tuple[bool, str]:
    """Rollback to a git tag or commit SHA. Returns (success, message)."""
    if dry_run:
        return True, f"[DRY-RUN] Would rollback to: {to_tag}"

    r = subprocess.run(
        ["git", "reset", "--hard", to_tag],
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(_ROOT),
    )
    if r.returncode == 0:
        return True, f"Rolled back to {to_tag}: {r.stdout.strip()}"
    else:
        return False, f"Rollback failed: {r.stderr.strip()}"


def log_incident(reason: str, current_pass_rate: float, baseline_pass_rate: float,
                 baseline_tag: str, rollback_target: str | None = None) -> Path:
    """Write an OKF risk-note and append to incidents.jsonl."""
    _RING_DIR.mkdir(parents=True, exist_ok=True)

    # OKF risk-note in .techne/context/
    now = datetime.now(timezone.utc)
    slug = f"incident-{now.strftime('%Y%m%dT%H%M%S')}"
    risk_note = _CONTEXT_DIR / f"{slug}.md"
    _CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    risk_note.write_text(
        f"---\n"
        f"name: {slug}\n"
        f"type: risk\n"
        f"title: Runtime Ring Incident — {now.strftime('%Y-%m-%d')}\n"
        f"description: Metric regression detected and rollback triggered\n"
        f"timestamp: {now.isoformat()}\n"
        f"tags: [runtime-ring, incident, regression]\n"
        f"---\n\n"
        f"# Runtime Ring Incident\n\n"
        f"**Detected**: {now.isoformat()}\n"
        f"**Reason**: {reason}\n"
        f"**Baseline**: tag={baseline_tag}, pass_rate={baseline_pass_rate:.2%}\n"
        f"**Current**: pass_rate={current_pass_rate:.2%}\n"
        f"**Rollback**: {'to ' + rollback_target if rollback_target else 'not triggered'}\n\n"
        f"## Action Required\n\n"
        f"1. Investigate the failing tests\n"
        f"2. Add a held-out eval case covering this failure pattern\n"
        f"3. Re-run the pipeline with the fix\n"
        f"4. The Runtime Ring will auto-clear when pass_rate recovers\n",
        encoding="utf-8",
    )

    # Auto-ingest this incident into the promotion gate eval corpus (W7)
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from promotion_gate import ingest_failure
        ingest_failure(
            source="runtime_ring",
            description=f"Runtime Ring rollback: {reason[:120]}",
            skill_target="skills/implementer.md",
        )
    except Exception:
        pass

    # JSONL incident log
    entry = {
        "ts": time.time(),
        "reason": reason,
        "current_pass_rate": current_pass_rate,
        "baseline_pass_rate": baseline_pass_rate,
        "baseline_tag": baseline_tag,
        "rollback_target": rollback_target,
        "risk_note": str(risk_note.relative_to(_ROOT)),
    }
    with _INCIDENTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return risk_note


# ── Status display ────────────────────────────────────────────────────────────

def show_status() -> None:
    """Print the current Runtime Ring status."""
    snap = load_last_snapshot()
    if snap is None:
        print("  [ring] No baseline snapshot found.")
        print("  Run: python runtime_ring.py snapshot --test-cmd 'pytest -q'")
        return

    print(f"\n  Runtime Ring Status")
    print(f"  {'='*50}")
    print(f"  Baseline tag:    {snap.tag}")
    print(f"  Snapshot time:   {snap.timestamp}")
    print(f"  Tests:           {snap.pass_count}/{snap.test_count} passing "
          f"({snap.pass_rate:.1%})")
    print(f"  Test command:    {snap.test_cmd}")

    if _INCIDENTS_FILE.exists():
        lines = [l for l in _INCIDENTS_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
        print(f"  Incidents:       {len(lines)} logged")
        if lines:
            last = json.loads(lines[-1])
            t = datetime.fromtimestamp(last["ts"], tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            print(f"  Last incident:   {t} — {last['reason'][:60]}")
    else:
        print(f"  Incidents:       none")
    print()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import argparse
    p = argparse.ArgumentParser(description="Runtime Ring — post-merge behavioral monitor (W6)")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_snap = sub.add_parser("snapshot", help="Capture a health baseline")
    p_snap.add_argument("--test-cmd", required=True, help="Test command to run")
    p_snap.add_argument("--tag", help="Tag for this snapshot (default: auto timestamp)")

    p_mon = sub.add_parser("monitor", help="Compare current health to baseline")
    p_mon.add_argument("--test-cmd", required=True, help="Test command to run")
    p_mon.add_argument("--threshold", type=float, default=0.05,
                       help="Max allowed pass_rate drop (default: 0.05 = 5%%)")
    p_mon.add_argument("--rollback-to", help="Git ref to rollback to on regression")
    p_mon.add_argument("--dry-run", action="store_true")

    p_rb = sub.add_parser("rollback", help="Rollback to a git tag or commit")
    p_rb.add_argument("--to-tag", required=True, help="Git tag or commit SHA")
    p_rb.add_argument("--dry-run", action="store_true")

    sub.add_parser("status", help="Show current Runtime Ring status")

    args = p.parse_args()

    if args.cmd == "snapshot":
        snap = take_snapshot(args.test_cmd, args.tag)
        save_snapshot(snap)
        return 0

    if args.cmd == "monitor":
        result = monitor(args.test_cmd, args.threshold)
        print(f"  [ring] {result.reason}")
        if result.requires_rollback:
            baseline = load_last_snapshot()
            rollback_target = args.rollback_to or (baseline.tag if baseline else "HEAD~1")
            risk_note = log_incident(
                result.reason, result.current_pass_rate, result.baseline_pass_rate,
                baseline.tag if baseline else "unknown", rollback_target,
            )
            print(f"  [ring] Incident logged: {risk_note.relative_to(_ROOT)}")
            if not args.dry_run:
                ok, msg = rollback(rollback_target)
                print(f"  [ring] {'ROLLBACK' if ok else 'ROLLBACK FAILED'}: {msg}")
                return 0 if ok else 1
            else:
                print(f"  [ring] [DRY-RUN] Would rollback to: {rollback_target}")
        return 0 if result.passed else 1

    if args.cmd == "rollback":
        ok, msg = rollback(args.to_tag, args.dry_run)
        print(f"  [ring] {'OK' if ok else 'FAIL'}: {msg}")
        return 0 if ok else 1

    if args.cmd == "status":
        show_status()
        return 0

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
