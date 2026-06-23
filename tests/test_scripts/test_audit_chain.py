"""Tests for scripts/audit_chain.py"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

from scripts.audit_chain import AuditEntry, compute_hash, seal, append_entry, verify_chain, read_entries, GENESIS_PREV


def _make_entry(task_id="test-1", phase="RECALL", summary="test entry"):
    return AuditEntry(
        seq=0,
        timestamp="2026-06-23T12:00:00+00:00",
        task_id=task_id,
        phase=phase,
        gates=[{"name": "exists", "passed": True, "detail": "file found"}],
        summary=summary,
        prev_hash="0" * 64,
    )


class TestAuditEntry:
    def test_compute_hash_deterministic(self):
        """Same content always produces the same hash."""
        e1 = _make_entry()
        e2 = _make_entry()
        assert compute_hash(e1) == compute_hash(e2)

    def test_seal_sets_entry_hash(self):
        """seal() sets entry_hash to a non-empty hex string."""
        e = _make_entry()
        assert e.entry_hash == ""
        seal(e)
        assert len(e.entry_hash) == 64
        assert all(c in "0123456789abcdef" for c in e.entry_hash)

    def test_different_content_different_hash(self):
        """Different summary produces different hash."""
        e1 = _make_entry(summary="one")
        e2 = _make_entry(summary="two")
        assert compute_hash(e1) != compute_hash(e2)

    def test_hash_excludes_entry_hash(self):
        """compute_hash produces the same result whether entry_hash is set or not."""
        e = _make_entry()
        h1 = compute_hash(e)
        e.entry_hash = "x" * 64
        h2 = compute_hash(e)
        assert h1 == h2


class TestAppendChain:
    def test_append_creates_chain(self, tmp_path):
        """First append creates chain.jsonl with seq=1."""
        (tmp_path / ".techne").mkdir()
        audit_dir = tmp_path / ".techne" / "audit"
        orig_cwd = Path.cwd()
        try:
            import os
            os.chdir(tmp_path)
            # Re-import to pick up new AUDIT_DIR
            import importlib
            import scripts.audit_chain as ac
            importlib.reload(ac)

            e1 = _make_entry(task_id="t1", phase="RECALL")
            h1 = ac.append_entry(e1)

            assert ac.CHAIN_FILE.exists()
            entries = ac.read_entries()
            assert len(entries) == 1
            assert entries[0].seq == 1
            assert entries[0].phase == "RECALL"
            assert entries[0].prev_hash == GENESIS_PREV
            assert entries[0].entry_hash == h1
        finally:
            os.chdir(orig_cwd)

    def test_append_sequential(self, tmp_path):
        """Entries get seq=1,2,3."""
        (tmp_path / ".techne").mkdir()
        orig_cwd = Path.cwd()
        try:
            import os
            os.chdir(tmp_path)
            import importlib
            import scripts.audit_chain as ac
            importlib.reload(ac)

            for i, phase in enumerate(["RECALL", "IMPLEMENT", "VERIFY"]):
                e = _make_entry(task_id="t1", phase=phase, summary=f"step {i}")
                ac.append_entry(e)

            entries = ac.read_entries()
            assert [e.seq for e in entries] == [1, 2, 3]
            assert [e.phase for e in entries] == ["RECALL", "IMPLEMENT", "VERIFY"]
        finally:
            os.chdir(orig_cwd)

    def test_append_links_prev_hash(self, tmp_path):
        """Each entry's prev_hash matches the previous entry's entry_hash."""
        (tmp_path / ".techne").mkdir()
        orig_cwd = Path.cwd()
        try:
            import os
            os.chdir(tmp_path)
            import importlib
            import scripts.audit_chain as ac
            importlib.reload(ac)

            hashes = []
            for i in range(3):
                e = _make_entry(task_id="t1", phase=f"PHASE{i}")
                h = ac.append_entry(e)
                hashes.append(h)

            entries = ac.read_entries()
            assert entries[0].prev_hash == GENESIS_PREV
            assert entries[1].prev_hash == hashes[0]
            assert entries[2].prev_hash == hashes[1]
        finally:
            os.chdir(orig_cwd)


class TestVerifyChain:
    def test_verify_clean_chain(self, tmp_path):
        """Clean chain returns (True, 'chain intact')."""
        (tmp_path / ".techne").mkdir()
        orig_cwd = Path.cwd()
        try:
            import os
            os.chdir(tmp_path)
            import importlib
            import scripts.audit_chain as ac
            importlib.reload(ac)

            for i in range(3):
                e = _make_entry(task_id="t1", phase=f"P{i}")
                ac.append_entry(e)

            ok, msg = ac.verify_chain()
            assert ok, f"Expected chain intact, got: {msg}"
            assert "intact" in msg
        finally:
            os.chdir(orig_cwd)

    def test_verify_empty_chain(self, tmp_path):
        """Empty chain.jsonl returns (True, ...)."""
        (tmp_path / ".techne").mkdir()
        orig_cwd = Path.cwd()
        try:
            import os
            os.chdir(tmp_path)
            import importlib
            import scripts.audit_chain as ac
            importlib.reload(ac)

            ok, msg = ac.verify_chain()
            assert ok
        finally:
            os.chdir(orig_cwd)

    def test_verify_tampered_entry(self, tmp_path):
        """Modified entry is detected."""
        (tmp_path / ".techne").mkdir()
        orig_cwd = Path.cwd()
        try:
            import os
            os.chdir(tmp_path)
            import importlib
            import scripts.audit_chain as ac
            importlib.reload(ac)

            e = _make_entry(task_id="t1", phase="RECALL")
            ac.append_entry(e)

            # Tamper with the chain file
            chain_file = ac.CHAIN_FILE
            content = chain_file.read_text()
            content = content.replace("test entry", "TAMPERED")
            chain_file.write_text(content)

            ok, msg = ac.verify_chain()
            assert not ok
            assert "hash mismatch" in msg
        finally:
            os.chdir(orig_cwd)

    def test_verify_broken_link(self, tmp_path):
        """Modified prev_hash is detected."""
        (tmp_path / ".techne").mkdir()
        orig_cwd = Path.cwd()
        try:
            import os
            os.chdir(tmp_path)
            import importlib
            import scripts.audit_chain as ac
            importlib.reload(ac)

            for i in range(2):
                e = _make_entry(task_id="t1", phase=f"P{i}")
                ac.append_entry(e)

            # Break the link in entry 2
            chain_file = ac.CHAIN_FILE
            lines = chain_file.read_text().splitlines()
            entry2 = json.loads(lines[1])
            entry2["prev_hash"] = "f" * 64
            lines[1] = json.dumps(entry2, sort_keys=True)
            chain_file.write_text("\n".join(lines) + "\n")

            ok, msg = ac.verify_chain()
            assert not ok
            assert "prev_hash mismatch" in msg
        finally:
            os.chdir(orig_cwd)


class TestEdgeCases:
    def test_append_after_restart(self, tmp_path):
        """New AuditChain.append_entry continues from existing chain."""
        (tmp_path / ".techne").mkdir()
        orig_cwd = Path.cwd()
        try:
            import os
            os.chdir(tmp_path)
            import importlib
            import scripts.audit_chain as ac
            importlib.reload(ac)

            # First session: append 2
            for i in range(2):
                e = _make_entry(task_id="t1", phase=f"P{i}")
                ac.append_entry(e)

            # Second session: reload module and append another
            importlib.reload(ac)
            e3 = _make_entry(task_id="t1", phase="P2")
            ac.append_entry(e3)

            entries = ac.read_entries()
            assert len(entries) == 3
            assert [e.seq for e in entries] == [1, 2, 3]
        finally:
            os.chdir(orig_cwd)
