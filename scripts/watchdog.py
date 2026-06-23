"""watchdog.py — External pipeline stall + tamper detector.

Run via cron every 5 minutes:
  */5 * * * * cd /path/to/project && python3 /path/to/techne/scripts/watchdog.py

Checks:
  1. STALL: state.json updated_at older than phase_timeout_min
  2. TAMPER: chain.jsonl hash chain broken
  3. SKIP: phase advanced but no matching audit entry
  4. ORPHAN: no state.json but recent task dirs exist

Exit codes: 0=healthy, 1=stall, 2=tamper, 3=skip, 4=orphan
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Path resolution ──────────────────────────────────────────────────────────

def _find_techne_root(cwd: Path | None = None) -> Path | None:
    """Walk up from cwd to find .techne/ directory."""
    base = cwd or Path.cwd()
    for parent in [base] + list(base.parents):
        if (parent / ".techne").is_dir():
            return parent
    return None


def _read_json(path: Path) -> dict | None:
    """Read a JSON file, return None on any failure."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _read_chain_entries(chain_path: Path) -> list[dict]:
    """Read all entries from chain.jsonl."""
    if not chain_path.exists():
        return []
    entries = []
    try:
        text = chain_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return entries


# ── Checks ───────────────────────────────────────────────────────────────────

def _check_stall(state: dict) -> tuple[int, str]:
    """Check if the pipeline has stalled (no ./next call in timeout window)."""
    phase = state.get("phase", "")
    if phase in ("DONE", "FAILED"):
        return 0, ""  # terminal phases are not stalls

    timeout_min = state.get("phase_timeout_min", 30)
    updated_raw = state.get("updated_at")
    if not updated_raw:
        return 0, ""

    try:
        updated = datetime.fromisoformat(updated_raw)
    except (ValueError, TypeError):
        return 0, ""

    now = datetime.now(timezone.utc)
    elapsed_min = (now - updated).total_seconds() / 60.0

    if elapsed_min > timeout_min:
        return (
            1,
            f"⚠️ PIPELINE STALL: Task {state.get('task_id', '?')} in phase "
            f"{state.get('phase', '?')}, last seen "
            f"{int(elapsed_min)} min ago (timeout: {timeout_min} min)",
        )
    return 0, ""


def _compute_hash(entry: dict) -> str:
    """Recompute the SHA-256 hash for an audit entry (excluding entry_hash)."""
    import hashlib

    d = {k: v for k, v in entry.items() if k != "entry_hash"}
    payload = json.dumps(d, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _check_tamper(chain_path: Path) -> tuple[int, str]:
    """Verify the hash chain integrity."""
    entries = _read_chain_entries(chain_path)
    if not entries:
        return 0, ""

    prev_hash = "0" * 64
    for idx, entry in enumerate(entries):
        expected_seq = idx + 1

        if entry.get("seq") != expected_seq:
            return 2, f"🚨 AUDIT TAMPER: entry {expected_seq}: seq mismatch (got {entry.get('seq')})"

        if entry.get("prev_hash") != prev_hash:
            return 2, f"🚨 AUDIT TAMPER: entry {expected_seq}: prev_hash mismatch"

        computed = _compute_hash(entry)
        stored = entry.get("entry_hash", "")
        if computed != stored:
            return (
                2,
                f"🚨 AUDIT TAMPER: entry {expected_seq}: hash mismatch\n"
                f"  Expected: {stored}\n"
                f"  Actual:   {computed}",
            )

        prev_hash = stored

    return 0, ""


def _check_skip(state: dict, chain_path: Path) -> tuple[int, str]:
    """Check if state phase advanced without an audit entry for that phase."""
    phase = state.get("phase", "")
    if not phase or phase == "DONE":
        return 0, ""

    entries = _read_chain_entries(chain_path)
    if not entries:
        return 3, f"⚠️ PHASE SKIP: state says {phase} but audit chain is empty"

    # Check if any entry matches the current phase
    phase_in_chain = any(e.get("phase") == phase for e in entries)
    if not phase_in_chain:
        last_phase = entries[-1].get("phase", "none") if entries else "none"
        return (
            3,
            f"⚠️ PHASE SKIP: state says {phase} but no audit entry for it. "
            f"Last audit entry phase: {last_phase}",
        )
    return 0, ""


def _check_orphan(techne_root: Path) -> tuple[int, str]:
    """Check for recent task dirs without active state."""
    tasks_dir = techne_root / ".techne" / "tasks"
    if not tasks_dir.is_dir():
        return 0, ""

    now = datetime.now(timezone.utc)
    recent = []
    try:
        for d in tasks_dir.iterdir():
            if d.is_dir():
                mtime = datetime.fromtimestamp(d.stat().st_mtime, tz=timezone.utc)
                elapsed = (now - mtime).total_seconds() / 60.0
                if elapsed < 5:  # modified in last 5 minutes
                    recent.append(d.name)
    except OSError:
        pass

    if recent:
        return (
            4,
            f"⚠️ ORPHANED WORK: {len(recent)} task dirs modified in last 5 min "
            f"without active loop state",
        )
    return 0, ""


# ── Main ─────────────────────────────────────────────────────────────────────

def main(cwd: Path | None = None) -> int:
    """Run all checks. Returns exit code (0 = healthy)."""
    root = _find_techne_root(cwd)
    if root is None:
        # No .techne dir means nothing is running — healthy
        return 0

    state_path = root / ".techne" / "loop" / "state.json"
    chain_path = root / ".techne" / "audit" / "chain.jsonl"

    state = _read_json(state_path)

    if state is None:
        # No active state — check for orphan work
        code, msg = _check_orphan(root)
        if code:
            print(msg)
        return code

    # Run all checks against active state
    checks = [
        _check_stall(state),
        _check_tamper(chain_path),
        _check_skip(state, chain_path),
    ]

    for code, msg in checks:
        if code:
            print(msg)
            return code

    return 0


if __name__ == "__main__":
    sys.exit(main())
