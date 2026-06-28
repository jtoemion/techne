#!/usr/bin/env python3
"""failure_disposition.py — W8b Autonomous Failure Disposition (GRAND-PLAN-FINAL §3b).

When a task exhausts its budget or can't clear the gates, this module decides
what to do autonomously — no human ticket, no silent failure.

Disposition policy (in order):
  1. RETRY        — retry with more grounding (up to max_retries)
  2. PARTIAL      — commit the subtasks that passed; re-spec the rest
  3. DECOMPOSE    — split the SPEC into smaller verifiable units
  4. INCIDENT     — failed task → OKF risk note + held-out eval case + candidate gate

Rule: NEVER weaken a gate to pass (reward-hacking prevention).
Rule: NEVER fake success (one of the named failure modes).

Usage:
    python failure_disposition.py --check          # check if current task is stalled
    python failure_disposition.py --dispose        # run disposition on a stalled task
    python failure_disposition.py --status         # show stall + disposition status
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
_DISPOSITION_LOG = _ROOT / ".techne" / "events" / "dispositions.jsonl"

STALL_MINUTES_DEFAULT = 60
MAX_RETRIES_DEFAULT = 2

DISPOSITIONS = ["RETRY", "PARTIAL", "DECOMPOSE", "INCIDENT"]


@dataclass
class StallCheck:
    task_id: str
    phase: str
    minutes_in_phase: float
    timeout_minutes: float
    is_stalled: bool
    retry_count: int
    recommended_disposition: str
    reason: str


@dataclass
class DispositionEvent:
    task_id: str
    phase: str
    timestamp: str
    action: str          # RETRY | PARTIAL | DECOMPOSE | INCIDENT
    reason: str
    okf_risk_note: str | None = None
    eval_case_id: str | None = None


def check_stall(cwd: Path | None = None, stall_minutes: float = STALL_MINUTES_DEFAULT) -> StallCheck | None:
    """Check if the current task is stalled. Returns None if no active pipeline."""
    cwd = cwd or Path.cwd()
    state_file = cwd / ".techne" / "loop" / "state.json"
    if not state_file.exists():
        return None

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return None

    task_id = state.get("task_id", "unknown")
    phase = state.get("phase", "UNKNOWN")
    updated_at = state.get("updated_at", "")
    timeout = state.get("phase_timeout_min", stall_minutes)
    retry_count = state.get("retry_count", 0)

    if phase == "DONE":
        return None

    # Compute minutes in phase
    try:
        from datetime import datetime as dt
        updated = dt.fromisoformat(updated_at)
        now = dt.now(timezone.utc)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        minutes_in_phase = (now - updated).total_seconds() / 60
    except Exception:
        minutes_in_phase = 0.0

    is_stalled = minutes_in_phase > timeout

    # Choose disposition
    if not is_stalled:
        return StallCheck(
            task_id=task_id, phase=phase,
            minutes_in_phase=minutes_in_phase, timeout_minutes=timeout,
            is_stalled=False, retry_count=retry_count,
            recommended_disposition="NONE", reason="Not stalled",
        )

    if retry_count < MAX_RETRIES_DEFAULT:
        action = "RETRY"
        reason = f"Stalled {minutes_in_phase:.0f}m in {phase} (timeout={timeout}m) — retry {retry_count+1}/{MAX_RETRIES_DEFAULT}"
    elif phase == "VERIFY":
        action = "PARTIAL"
        reason = "VERIFY stall after max retries — commit passing subtasks, re-spec failures"
    elif phase in ("IMPLEMENT", "RECALL", "GROUND"):
        action = "DECOMPOSE"
        reason = f"{phase} stall after max retries — split SPEC into smaller verifiable units"
    else:
        action = "INCIDENT"
        reason = f"{phase} stall after max retries — log as incident + seed eval case"

    return StallCheck(
        task_id=task_id, phase=phase,
        minutes_in_phase=minutes_in_phase, timeout_minutes=timeout,
        is_stalled=True, retry_count=retry_count,
        recommended_disposition=action, reason=reason,
    )


def dispose(stall: StallCheck, cwd: Path | None = None) -> DispositionEvent:
    """Execute the recommended disposition for a stalled task."""
    cwd = cwd or Path.cwd()
    now = datetime.now(timezone.utc).isoformat()
    action = stall.recommended_disposition

    okf_path = None
    eval_case_id = None

    if action == "RETRY":
        # Bump retry_count in state.json and clear phase timer
        _bump_retry_count(cwd)

    elif action == "PARTIAL":
        # Write a partial-completion handoff note
        _write_partial_handoff(stall, cwd)

    elif action == "DECOMPOSE":
        # Write a decomposition prompt (re-spec into smaller units)
        _write_decompose_prompt(stall, cwd)

    elif action == "INCIDENT":
        # Write OKF risk note + seed eval case
        okf_path, eval_case_id = _write_incident(stall, cwd)

    event = DispositionEvent(
        task_id=stall.task_id,
        phase=stall.phase,
        timestamp=now,
        action=action,
        reason=stall.reason,
        okf_risk_note=str(okf_path) if okf_path else None,
        eval_case_id=eval_case_id,
    )
    _log_disposition(event)
    return event


def _bump_retry_count(cwd: Path) -> None:
    state_file = cwd / ".techne" / "loop" / "state.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        state["retry_count"] = state.get("retry_count", 0) + 1
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _write_partial_handoff(stall: StallCheck, cwd: Path) -> None:
    partial_path = cwd / ".techne" / "loop" / "partial_handoff.md"
    partial_path.write_text(
        f"# Partial Completion Handoff — {stall.task_id}\n\n"
        f"**Phase stalled:** {stall.phase}\n"
        f"**Minutes in phase:** {stall.minutes_in_phase:.0f}\n"
        f"**Disposition:** PARTIAL — commit passing subtasks, re-spec failures\n\n"
        f"## Action Required\n\n"
        f"1. Identify which subtasks passed VERIFY gates\n"
        f"2. Commit those subtasks separately\n"
        f"3. Re-spec the remaining failures into smaller tasks\n"
        f"4. Run `techne init <new-task-id>` for each decomposed piece\n\n"
        f"## Why\n\n"
        f"{stall.reason}\n",
        encoding="utf-8",
    )


def _write_decompose_prompt(stall: StallCheck, cwd: Path) -> None:
    decompose_path = cwd / ".techne" / "loop" / "decompose_prompt.md"
    spec_file = cwd / ".techne" / "loop" / "spec.md"
    spec_hint = spec_file.read_text(encoding="utf-8")[:500] if spec_file.exists() else "(no spec found)"

    decompose_path.write_text(
        f"# Decomposition Required — {stall.task_id}\n\n"
        f"**Phase stalled:** {stall.phase} for {stall.minutes_in_phase:.0f}m\n"
        f"**Disposition:** DECOMPOSE — split SPEC into smaller verifiable units\n\n"
        f"## Original Spec (excerpt)\n\n"
        f"```\n{spec_hint}\n```\n\n"
        f"## Decomposition Instructions\n\n"
        f"1. Identify the smallest independently-verifiable unit in this spec\n"
        f"2. Create a new task: `techne init {stall.task_id}-part-1`\n"
        f"3. Write a tighter SPECIFY for that unit (< 5 acceptance criteria)\n"
        f"4. Repeat for remaining parts\n"
        f"5. Each part must pass VERIFY independently before the next starts\n",
        encoding="utf-8",
    )


def _write_incident(stall: StallCheck, cwd: Path) -> tuple[Path | None, str | None]:
    """Write OKF risk note + seed eval corpus case."""
    context_dir = cwd / ".techne" / "context"
    context_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    slug = f"disposition-incident-{now.strftime('%Y%m%dT%H%M%S')}"
    risk_note = context_dir / f"{slug}.md"

    risk_note.write_text(
        f"---\n"
        f"name: {slug}\n"
        f"type: risk\n"
        f"title: Failure Disposition Incident — {stall.task_id}\n"
        f"description: Task failed all disposition layers\n"
        f"timestamp: {now.isoformat()}\n"
        f"tags: [failure-disposition, incident, {stall.phase.lower()}]\n"
        f"---\n\n"
        f"# Failure Disposition Incident\n\n"
        f"**Task:** {stall.task_id}\n"
        f"**Phase:** {stall.phase}\n"
        f"**Stalled:** {stall.minutes_in_phase:.0f} minutes\n"
        f"**Reason:** {stall.reason}\n\n"
        f"## Why This Is Structured Data, Not a Ticket\n\n"
        f"Per GRAND-PLAN-FINAL §3b: failed tasks become:\n"
        f"1. An OKF risk note (this file) → feeds the learning loop\n"
        f"2. A held-out eval case → seeds the calibration corpus (W8)\n"
        f"3. A candidate gate → if this failure pattern is recurring\n\n"
        f"Never fake success. Never weaken a gate.\n",
        encoding="utf-8",
    )

    # Seed the eval corpus
    eval_case_id = None
    try:
        sys.path.insert(0, str(_HERE))
        from promotion_gate import ingest_failure
        case = ingest_failure(
            source="grpo_failure",
            description=f"Task stall at {stall.phase}: {stall.reason[:120]}",
            skill_target="skills/implementer.md",
        )
        eval_case_id = case.id
    except Exception:
        pass

    return risk_note, eval_case_id


def _log_disposition(event: DispositionEvent) -> None:
    _DISPOSITION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DISPOSITION_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")


def load_disposition_log(cwd: Path | None = None) -> list[DispositionEvent]:
    log_file = _DISPOSITION_LOG
    if not log_file.exists():
        return []
    results = []
    for line in log_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            results.append(DispositionEvent(**json.loads(line)))
        except Exception:
            continue
    return results


def show_status(cwd: Path | None = None) -> None:
    cwd = cwd or Path.cwd()
    stall = check_stall(cwd)
    events = load_disposition_log(cwd)

    print(f"\n  Failure Disposition Status")
    print(f"  {'='*50}")

    if stall is None:
        print(f"  No active pipeline.")
    elif stall.is_stalled:
        print(f"  STALLED: task={stall.task_id} phase={stall.phase}")
        print(f"  Time in phase: {stall.minutes_in_phase:.0f}m (timeout={stall.timeout_minutes}m)")
        print(f"  Recommended: {stall.recommended_disposition}")
        print(f"  Reason: {stall.reason}")
    else:
        print(f"  Active: task={stall.task_id} phase={stall.phase} "
              f"({stall.minutes_in_phase:.0f}m / {stall.timeout_minutes}m)")

    print(f"\n  Disposition history: {len(events)} event(s)")
    if events:
        by_action: dict[str, int] = {}
        for e in events:
            by_action[e.action] = by_action.get(e.action, 0) + 1
        for action, count in sorted(by_action.items()):
            print(f"    {action}: {count}")
    print()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import argparse
    p = argparse.ArgumentParser(description="W8b — Autonomous Failure Disposition")
    p.add_argument("--check", action="store_true", help="Check if current task is stalled")
    p.add_argument("--dispose", action="store_true", help="Run disposition on a stalled task")
    p.add_argument("--stall-minutes", type=float, default=STALL_MINUTES_DEFAULT)
    p.add_argument("--status", action="store_true", help="Show stall + disposition status")
    args = p.parse_args()

    cwd = Path.cwd()

    if args.check or args.dispose:
        stall = check_stall(cwd, args.stall_minutes)
        if stall is None:
            print("  No active pipeline.")
            return 0
        if not stall.is_stalled:
            print(f"  Not stalled: {stall.task_id} in {stall.phase} "
                  f"({stall.minutes_in_phase:.0f}m / {stall.timeout_minutes}m)")
            return 0
        print(f"  STALLED: {stall.task_id} in {stall.phase} — {stall.reason}")
        print(f"  Recommended: {stall.recommended_disposition}")
        if args.dispose:
            event = dispose(stall, cwd)
            print(f"  Disposed: action={event.action}")
            if event.okf_risk_note:
                print(f"  OKF risk note: {event.okf_risk_note}")
            if event.eval_case_id:
                print(f"  Eval case: {event.eval_case_id}")
        return 0

    if args.status:
        show_status(cwd)
        return 0

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
