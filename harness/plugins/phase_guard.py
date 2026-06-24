"""
phase_guard.py — Pre_tool_call-style enforcement plugin.

Enforces write discipline based on the current phase of the loop.
This module can be called from the techne Hermes plugin or used independently.

Functions:
  check_write_allowed(path_str, cwd) -> tuple[bool, str]
  get_blocked_log(cwd) -> list[dict]
  log_blocked(path, reason, cwd) -> None
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Phase artifact mapping (mirrors next_state.artifact_path_for)
# None = any path allowed (normal dev work) or no artifact needed
_PHASE_ARTIFACT_MAP = {
    "RECALL":     "recall.txt",
    "IMPLEMENT":  "diff.txt",
    "VERIFY":     "test_output.txt",
    "CONCLUDE":   "conclude.txt",
    "DONE":       None,       # None = terminal phase, no artifact needed
}

_TECHNE_DIR = Path(".techne")
_LOOP_DIR = _TECHNE_DIR / "loop"
_AUDIT_DIR = _TECHNE_DIR / "audit"
_STATE_FILE = _LOOP_DIR / "state.json"
_BLOCKED_LOG = _AUDIT_DIR / "blocked.log"


def _find_techne_root(cwd: Path | None = None) -> Path | None:
    """Walk up from cwd to find .techne/ directory."""
    base = cwd or Path.cwd()
    for parent in [base] + list(base.parents):
        if (parent / _TECHNE_DIR).is_dir():
            return parent
    return None


def check_write_allowed(path_str: str, cwd: str | None = None) -> tuple[bool, str]:
    """
    Check whether a write to `path_str` is allowed in the current phase.

    Returns (True, '') if write is allowed, (False, 'reason') if blocked.

    Logic:
      1. Resolve .techne/ by walking up from cwd
      2. Read .techne/loop/state.json
      3. If no state.json:
         - Block ALL writes to project source files (anything not under .techne/)
         - Allow writes to .techne/ directory
         - Return (False, 'No active pipeline. Call ./next to start the loop.')
      4. If state.json exists:
         - Block writes to .techne/audit/ (agent must NOT touch audit trail)
         - Get current phase from state
         - Allow writes to .techne/ (except .techne/audit/)
         - Allow writes to project source files (the agent is implementing)
         - Allow writes to current phase's artifact path in .techne/loop/
         - Block writes to OTHER phase artifact paths
         - Return result with specific reason
    """
    root = _find_techne_root(Path(cwd) if cwd else None)
    if root is None:
        # No .techne found — allow nothing meaningful
        return (False, "No .techne directory found.")

    techne_path = root / _TECHNE_DIR
    audit_path = root / _AUDIT_DIR
    loop_path = root / _LOOP_DIR
    state_path = root / _STATE_FILE

    # Resolve the requested write path relative to root
    requested = (root / path_str).resolve()

    # Determine what kind of path this is
    try:
        requested.relative_to(root)
        is_under_root = True
    except ValueError:
        is_under_root = False

    # Check if it's under .techne/
    try:
        requested.relative_to(techne_path)
        is_under_techne = True
    except ValueError:
        is_under_techne = False

    # Check if it's under .techne/audit/
    try:
        requested.relative_to(audit_path)
        is_under_audit = True
    except ValueError:
        is_under_audit = False

    # ── Case 3: No state.json ─────────────────────────────────────────────────
    if not state_path.exists():
        if is_under_techne:
            # Writes to .techne/ itself are allowed when no state
            return (True, "")
        else:
            # Block all project source file writes when no active pipeline
            return (
                False,
                "No active pipeline. Call ./next to start the loop.",
            )

    # ── Case 4: state.json exists ─────────────────────────────────────────────
    try:
        state_data = json.loads(state_path.read_text(encoding="utf-8"))
        current_phase = state_data.get("phase", "")
    except (json.JSONDecodeError, OSError):
        # Corrupt state — block everything
        return (False, "Corrupt state.json. Cannot determine phase.")

    # Block writes to audit directory regardless of phase
    if is_under_audit:
        return (False, "Write to audit trail is forbidden.")

    # Allow writes to .techne/ (except audit)
    if is_under_techne:
        # Check if it's the current phase's artifact
        artifact_name = _PHASE_ARTIFACT_MAP.get(current_phase)
        if artifact_name is None:
            # IMPLEMENT or DONE — any artifact path under .techne/ is allowed
            return (True, "")
        if artifact_name:
            current_artifact = loop_path / artifact_name
            if requested.resolve() == current_artifact.resolve():
                return (True, "")
        # Not the current artifact — block
        return (
            False,
            f"Cannot write to {path_str}: not the current phase artifact "
            f"({current_phase} phase, expected {artifact_name}).",
        )

    # Allow writes to project source files
    return (True, "")


def get_blocked_log(cwd: str | None = None) -> list[dict]:
    """
    Read .techne/audit/blocked.log (JSONL).

    Each line is a JSON object with keys: timestamp, path, reason
    Returns an empty list if the log doesn't exist.
    """
    root = _find_techne_root(Path(cwd) if cwd else None)
    if root is None:
        return []

    log_path = root / _BLOCKED_LOG
    if not log_path.exists():
        return []

    entries = []
    try:
        text = log_path.read_text(encoding="utf-8")
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


def log_blocked(path: str, reason: str, cwd: str | None = None) -> None:
    """
    Append a JSON line to .techne/audit/blocked.log.

    Record: {timestamp, path, reason}
    """
    root = _find_techne_root(Path(cwd) if cwd else None)
    if root is None:
        return

    log_path = root / _BLOCKED_LOG
    audit_dir = root / _AUDIT_DIR
    audit_dir.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "path": path,
        "reason": reason,
    }

    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass
