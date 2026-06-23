"""next_state.py — Loop state read/write for the ./next script.

Reads and writes .techne/loop/state.json — the single source of truth
for which phase the current task is in.

Phase sequence (one loop, every task):
  RECALL → IMPLEMENT → VERIFY → CONCLUDE → DONE
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# The phase sequence — every task passes through every phase.
# Gates self-select inside each phase; the phase itself is never skipped.
PHASE_SEQUENCE = ["RECALL", "IMPLEMENT", "VERIFY", "CONCLUDE", "DONE"]


@dataclass
class LoopState:
    """The current state of the loop for one task."""
    task_id: str
    phase: str            # current phase (one of PHASE_SEQUENCE)
    created_at: str       # ISO timestamp
    updated_at: str       # ISO timestamp
    summary: str = ""     # plain-language summary from the last ./next run

    def next_phase(self) -> Optional[str]:
        """Return the next phase, or None if already at DONE."""
        try:
            idx = PHASE_SEQUENCE.index(self.phase)
            if idx + 1 < len(PHASE_SEQUENCE):
                return PHASE_SEQUENCE[idx + 1]
            return None
        except ValueError:
            return None

    def is_terminal(self) -> bool:
        return self.phase == "DONE"


def loop_dir(cwd: Path | None = None) -> Path:
    """Resolve .techne/loop/ relative to cwd or current working dir."""
    base = cwd or Path.cwd()
    # Walk up to find .techne/
    for parent in [base] + list(base.parents):
        dot_techne = parent / ".techne"
        if dot_techne.is_dir():
            loop = dot_techne / "loop"
            loop.mkdir(parents=True, exist_ok=True)
            return loop
    # Fallback: create at cwd/.techne/loop/
    loop = base / ".techne" / "loop"
    loop.mkdir(parents=True, exist_ok=True)
    return loop


def state_path(cwd: Path | None = None) -> Path:
    return loop_dir(cwd) / "state.json"


def read_state(cwd: Path | None = None) -> LoopState | None:
    """Read loop state from disk. Returns None if no state file exists."""
    path = state_path(cwd)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return LoopState(**data)
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def write_state(state: LoopState, cwd: Path | None = None) -> Path:
    """Write loop state to disk."""
    state.updated_at = datetime.now(timezone.utc).isoformat()
    path = state_path(cwd)
    path.write_text(
        json.dumps(asdict(state), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def create_initial_state(
    task_id: str,
    cwd: Path | None = None,
) -> LoopState:
    """Create and write initial loop state (phase=RECALL)."""
    now = datetime.now(timezone.utc).isoformat()
    state = LoopState(
        task_id=task_id,
        phase="RECALL",
        created_at=now,
        updated_at=now,
    )
    write_state(state, cwd)
    return state


def artifact_path_for(phase: str, cwd: Path | None = None) -> Path:
    """Return the expected artifact path for a given phase."""
    mapping = {
        "RECALL":  "recall.txt",
        "IMPLEMENT": "diff.txt",     # the diff as text
        "VERIFY":  "test_output.txt",
        "CONCLUDE": "conclude.txt",
    }
    name = mapping.get(phase)
    if name is None:
        return loop_dir(cwd) / f"{phase.lower()}.txt"
    return loop_dir(cwd) / name
