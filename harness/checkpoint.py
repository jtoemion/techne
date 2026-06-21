"""
checkpoint.py — blocks completion claims until verification runs.

Adopted from jtoemion/harness-engineering-skills/runtime/checkpoint.py.
The conductor calls this after VERIFY phase passes. It enforces that
no pipeline can claim "done" without real verification evidence.
"""

from datetime import datetime, timezone
from pathlib import Path

from store import read_json, write_json, state_dir

HARNESS_DIR = Path(__file__).parent
ROOT = HARNESS_DIR.parent

# The DEFAULT checkpoint location (no override). Kept for external callers that
# back up / restore the real state file. Internal reads/writes go through
# _state_file(), which honors a per-worker TECHNE_STATE_DIR (Kanban isolation).
STATE_FILE = ROOT / ".techne" / "memory" / "harness-state.json"


def _state_file() -> Path:
    """Per-run checkpoint file. Resolved each call so a host's TECHNE_STATE_DIR
    override isolates parallel workers (Kanban compatibility). Default: .techne/memory/."""
    return state_dir() / "harness-state.json"


def read_state() -> dict:
    return read_json(_state_file(), default={})


def write_state(state: dict) -> None:
    write_json(_state_file(), state)


def init_state() -> dict:
    now = datetime.now(timezone.utc)
    state = {
        "session_id": now.strftime("%Y-%m-%d-%H%M"),
        "boot_time": now.isoformat(),
        "pipeline_runs": 0,
        "last_checkpoint": None,
        "verification_logged": False,
        "gates_passed": [],
        "gates_failed": [],
    }
    write_state(state)
    return state


def log_gate_pass(gate_name: str) -> None:
    state = read_state()
    if not state:
        state = init_state()
    state.setdefault("gates_passed", []).append({
        "gate": gate_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    write_state(state)


def log_gate_fail(gate_name: str, reason: str) -> None:
    state = read_state()
    if not state:
        state = init_state()
    state.setdefault("gates_failed", []).append({
        "gate": gate_name,
        "reason": reason[:200],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    write_state(state)


def mark_honcho_concluded(conclusion_id: str, peer: str = "user") -> None:
    """Mark that Hermes completed a real Honcho call for this phase.

    Called by Hermes (the host) after a genuine honcho_search or honcho_conclude.
    Mirrors mark_verified()'s pattern: the gate trusts this file, not prose.
    """
    state = read_state()
    if not state:
        state = init_state()
    state["honcho_conclusion_id"] = conclusion_id
    state["honcho_peer"] = peer
    state["honcho_logged_at"] = datetime.now(timezone.utc).isoformat()
    write_state(state)


def check_honcho_logged() -> str | None:
    """Returns the conclusion ID if a real Honcho call was logged this session, else None."""
    state = read_state()
    return state.get("honcho_conclusion_id")


def clear_honcho_flag() -> None:
    """Clear Honcho flag so subsequent gates will not see a logged Honcho call."""
    state = read_state()
    if state:
        state.pop("honcho_conclusion_id", None)
        state.pop("honcho_peer", None)
        state.pop("honcho_logged_at", None)
        write_state(state)


def mark_verified(sha_hash: str) -> None:
    """Mark pipeline as verified — only the SHA gate should call this."""
    state = read_state()
    if not state:
        state = init_state()
    state["verification_logged"] = True
    state["last_verification_sha"] = sha_hash
    state["last_checkpoint"] = datetime.now(timezone.utc).isoformat()
    write_state(state)


def check_verification() -> bool:
    """Returns True if verification has been logged for current session."""
    state = read_state()
    return state.get("verification_logged", False)


def increment_pipeline_run() -> int:
    state = read_state()
    if not state:
        state = init_state()
    state["pipeline_runs"] = state.get("pipeline_runs", 0) + 1
    state["verification_logged"] = False  # Reset on new run
    # Clear honcho flag on new run
    state.pop("honcho_conclusion_id", None)
    state.pop("honcho_peer", None)
    state.pop("honcho_logged_at", None)
    write_state(state)
    return state["pipeline_runs"]


def get_summary() -> str:
    """Print checkpoint status — used by conductor at pipeline end."""
    state = read_state()
    if not state:
        return "No harness state found."

    lines = [
        f"Session:      {state.get('session_id', 'unknown')}",
        f"Pipeline runs: {state.get('pipeline_runs', 0)}",
        f"Verified:      {state.get('verification_logged', False)}",
        f"Last SHA:      {state.get('last_verification_sha', 'none')[:16]}...",
        f"Gates passed:  {len(state.get('gates_passed', []))}",
        f"Gates failed:  {len(state.get('gates_failed', []))}",
    ]
    return "\n".join(lines)
