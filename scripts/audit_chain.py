"""
Append-only hash-chained audit log module.

Each entry is sealed with a SHA-256 hash that chains to the previous entry,
making tampering detectable.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _find_techne_root() -> Path:
    """Walk up from CWD to find the .techne/ directory and return its parent."""
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".techne").is_dir():
            return parent
    # Fallback: treat CWD as the root
    return cwd


AUDIT_DIR = _find_techne_root() / ".techne" / "audit"
CHAIN_FILE = AUDIT_DIR / "chain.jsonl"

GENESIS_PREV = "0" * 64


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class AuditEntry:
    seq: int
    timestamp: str
    task_id: str
    phase: str
    gates: list[dict]
    summary: str
    prev_hash: str
    entry_hash: str = ""


# ---------------------------------------------------------------------------
# Hash computation
# ---------------------------------------------------------------------------

def _stable_dict(d: dict) -> dict:
    """Return a dict with keys sorted, suitable for deterministic hashing."""
    return dict(sorted(d.items()))


def compute_hash(entry: AuditEntry) -> str:
    """
    Compute SHA-256 hash over all fields EXCEPT entry_hash.
    Fields are sorted by key for deterministic output.
    """
    data = {
        "seq": entry.seq,
        "timestamp": entry.timestamp,
        "task_id": entry.task_id,
        "phase": entry.phase,
        "gates": entry.gates,
        "summary": entry.summary,
        "prev_hash": entry.prev_hash,
    }
    payload = json.dumps(_stable_dict(data), sort_keys=True)
    import hashlib
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def seal(entry: AuditEntry) -> None:
    """Compute and set entry_hash in place."""
    entry.entry_hash = compute_hash(entry)


# ---------------------------------------------------------------------------
# Low-level chain operations
# ---------------------------------------------------------------------------

def _read_last_line(path: Path) -> Optional[str]:
    """Return the last non-empty line of a file, or None if empty."""
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as fh:
        lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
    return lines[-1] if lines else None


def _parse_entry(line: str) -> AuditEntry:
    d = json.loads(line)
    return AuditEntry(
        seq=d["seq"],
        timestamp=d["timestamp"],
        task_id=d["task_id"],
        phase=d["phase"],
        gates=d["gates"],
        summary=d["summary"],
        prev_hash=d["prev_hash"],
        entry_hash=d["entry_hash"],
    )


def _prev_info() -> tuple[int, str]:
    """
    Return (last_seq, prev_hash) for the chain.
    Empty chain → (0, GENESIS_PREV).
    """
    last_line = _read_last_line(CHAIN_FILE)
    if last_line is None:
        return 0, GENESIS_PREV
    entry = _parse_entry(last_line)
    return entry.seq, entry.entry_hash


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def append_entry(entry: AuditEntry) -> str:
    """
    Append a sealed AuditEntry to the chain.

    Steps:
      1. Create AUDIT_DIR if it doesn't exist.
      2. Read the last chain line to get prev_hash (empty chain → '0'*64).
      3. Set entry.prev_hash, entry.seq = prev_seq + 1, then seal().
      4. Append JSON line to chain.jsonl.
      5. Return entry.entry_hash.
    """
    import os

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    prev_seq, prev_hash = _prev_info()

    entry.seq = prev_seq + 1
    entry.prev_hash = prev_hash
    seal(entry)

    line = json.dumps(asdict(entry), sort_keys=True) + "\n"
    with open(CHAIN_FILE, "a", encoding="utf-8") as fh:
        fh.write(line)

    return entry.entry_hash


def verify_chain() -> tuple[bool, str]:
    """
    Verify the entire chain for integrity.

    Checks:
      - Each entry's recomputed hash matches its stored entry_hash.
      - Sequence numbers are sequential starting at 1.
      - prev_hash links correctly to the previous entry_hash (or '0'*64 for first).

    Returns:
        (True, "chain intact")  — all checks passed.
        (False, "entry N: hash mismatch")  — first detected problem.
    """
    last_line = _read_last_line(CHAIN_FILE)
    if last_line is None:
        return True, "chain intact"

    lines = [ln for ln in last_line.split("\n") if ln.strip()]
    # Actually read all lines from file
    with open(CHAIN_FILE, "r", encoding="utf-8") as fh:
        all_lines = [ln.rstrip("\n") for ln in fh if ln.strip()]

    prev_entry_hash = GENESIS_PREV

    for idx, line in enumerate(all_lines):
        entry = _parse_entry(line)
        expected_seq = idx + 1

        # Check sequence
        if entry.seq != expected_seq:
            return False, f"entry {expected_seq}: seq mismatch (got {entry.seq})"

        # Check prev_hash link
        if entry.prev_hash != prev_entry_hash:
            return False, f"entry {expected_seq}: prev_hash mismatch"

        # Check hash
        if compute_hash(entry) != entry.entry_hash:
            return False, f"entry {expected_seq}: hash mismatch"

        prev_entry_hash = entry.entry_hash

    return True, "chain intact"


def read_entries() -> list[AuditEntry]:
    """Read and return all entries from chain.jsonl."""
    if not CHAIN_FILE.exists():
        return []
    with open(CHAIN_FILE, "r", encoding="utf-8") as fh:
        return [_parse_entry(ln.rstrip("\n")) for ln in fh if ln.strip()]
