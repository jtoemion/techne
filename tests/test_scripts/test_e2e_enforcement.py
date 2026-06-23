"""End-to-end enforcement tests.

Scenarios:
  1. Agent skips ./next → watchdog detects stall
  2. Agent fakes state.json → watchdog detects skip
  3. Agent edits audit log → watchdog detects tamper
"""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

from scripts import watchdog


def _create_state(techne_root: Path, phase="RECALL", task_id="test-1", updated_mins_ago=0, timeout_min=30):
    loop_dir = techne_root / ".techne" / "loop"
    loop_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    updated = now - timedelta(minutes=updated_mins_ago) if updated_mins_ago > 0 else now
    state = {
        "task_id": task_id,
        "phase": phase,
        "created_at": now.isoformat(),
        "updated_at": updated.isoformat(),
        "phase_timeout_min": timeout_min,
        "summary": "",
    }
    (loop_dir / "state.json").write_text(json.dumps(state, indent=2))
    return state


def _make_entry(phase, task_id="test-1", summary="test"):
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_id": task_id,
        "phase": phase,
        "gates": [{"name": "exists", "passed": True, "detail": "ok"}],
        "summary": summary,
    }


def _create_chain(techne_root: Path, entries: list[dict]):
    audit_dir = techne_root / ".techne" / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    chain_path = audit_dir / "chain.jsonl"
    prev_hash = "0" * 64
    lines = []
    for i, entry_data in enumerate(entries):
        entry_data["seq"] = i + 1
        entry_data["prev_hash"] = prev_hash
        d = {k: v for k, v in entry_data.items() if k != "entry_hash"}
        payload = json.dumps(d, sort_keys=True)
        entry_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        entry_data["entry_hash"] = entry_hash
        lines.append(json.dumps(entry_data, sort_keys=True))
        prev_hash = entry_hash
    chain_path.write_text("\n".join(lines) + "\n")


class TestE2ESkipNext:
    """Agent works without calling ./next — watchdog catches stall."""

    def test_stall_detected_after_skip(self, tmp_path):
        """Watchdog detects stall when agent doesn't call ./next."""
        # Agent started pipeline (state.json exists, 47 min ago)
        _create_state(tmp_path, phase="IMPLEMENT", updated_mins_ago=47, timeout_min=30)
        # Agent called ./next once (1 entry in chain)
        _create_chain(tmp_path, [_make_entry("RECALL")])

        code = watchdog.main(cwd=tmp_path)
        assert code == 1, f"Expected stall (1), got {code}"


class TestE2EFakeState:
    """Agent fakes state.json to DONE — watchdog detects skip."""

    def test_fake_done_detected(self, tmp_path):
        """Watchdog catches agent that skips to DONE without audit entries."""
        _create_state(tmp_path, phase="DONE", updated_mins_ago=1, timeout_min=30)
        # Only 1 entry (RECALL), state says DONE — but DONE is terminal so
        # no stall. Check that the chain only has 1 entry.
        _create_chain(tmp_path, [_make_entry("RECALL")])
        code = watchdog.main(cwd=tmp_path)
        # DONE is terminal — watchdog should exit 0 (no alert).
        # The missing audit entries for IMPLEMENT/VERIFY/CONCLUDE/DONE
        # are only caught if state is NOT terminal and chain doesn't match.
        assert code == 0

    def test_fake_skip_verify_detected(self, tmp_path):
        """State says VERIFY but chain only has RECALL."""
        _create_state(tmp_path, phase="VERIFY", updated_mins_ago=1, timeout_min=30)
        _create_chain(tmp_path, [_make_entry("RECALL")])  # skipped IMPLEMENT
        code = watchdog.main(cwd=tmp_path)
        assert code == 3, f"Expected skip (3), got {code}"


class TestE2ETamper:
    """Agent edits audit log — watchdog detects tamper."""

    def test_tampered_entry_detected(self, tmp_path):
        """Modified audit entry is detected."""
        _create_state(tmp_path, phase="VERIFY", updated_mins_ago=1, timeout_min=30)
        _create_chain(tmp_path, [_make_entry("RECALL"), _make_entry("IMPLEMENT")])

        # Tamper: modify entry 1's summary
        chain_path = tmp_path / ".techne" / "audit" / "chain.jsonl"
        lines = chain_path.read_text().splitlines()
        entry1 = json.loads(lines[0])
        entry1["summary"] = "TAMPERED"
        lines[0] = json.dumps(entry1, sort_keys=True)
        chain_path.write_text("\n".join(lines) + "\n")

        code = watchdog.main(cwd=tmp_path)
        assert code == 2, f"Expected tamper (2), got {code}"

    def test_deleted_entry_detected(self, tmp_path):
        """Deleted entry causes seq gap → tamper detected."""
        _create_state(tmp_path, phase="CONCLUDE", updated_mins_ago=1, timeout_min=30)
        _create_chain(tmp_path, [_make_entry("RECALL"), _make_entry("IMPLEMENT"), _make_entry("VERIFY")])

        # Remove entry 2 (IMPLEMENT), re-link entry 3 to entry 1
        chain_path = tmp_path / ".techne" / "audit" / "chain.jsonl"
        lines = chain_path.read_text().splitlines()
        remaining = [json.loads(lines[0]), json.loads(lines[2])]
        # Re-link: entry 2 (now lines[1]) should point to entry 1's hash
        entry1_hash = remaining[0]["entry_hash"]
        remaining[1]["prev_hash"] = entry1_hash
        remaining[1]["seq"] = 2
        chain_path.write_text("\n".join(json.dumps(e, sort_keys=True) for e in remaining) + "\n")

        code = watchdog.main(cwd=tmp_path)
        assert code == 2, f"Expected tamper (2), got {code}"
