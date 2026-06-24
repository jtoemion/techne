"""core.py — Import bridge between techne_cli and scripts/ internals."""
from __future__ import annotations
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "scripts"
_HARNESS = _REPO / "harness"

for _p in [str(_SCRIPTS), str(_HARNESS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from next_state import (          # noqa: E402
    LoopState, read_state, write_state,
    create_initial_state, artifact_path_for,
    PHASE_SEQUENCE, state_path, loop_dir,
)
from audit_chain import (         # noqa: E402
    AuditEntry, append_entry, verify_chain, read_entries,
)

__all__ = [
    "LoopState", "read_state", "write_state",
    "create_initial_state", "artifact_path_for",
    "PHASE_SEQUENCE", "state_path", "loop_dir",
    "AuditEntry", "append_entry", "verify_chain", "read_entries",
]
