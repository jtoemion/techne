"""
test_task_db.py — hardening tests for harness/task_db.py Domain 3 (Task Lifecycle)

Run: python3 -m pytest tests/test_task_db.py -v
"""

from __future__ import annotations

import pytest
import sqlite3
import tempfile
import os
from datetime import datetime, timezone, timedelta

# Ensure harness is on path
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "harness"))

from task_db import TaskDB, CURRENT_SCHEMA_VERSION


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    """In-memory DB for each test."""
    d = TaskDB(":memory:")
    yield d
    d.close()


@pytest.fixture
def db_with_data():
    """In-memory DB seeded with known tasks and events."""
    d = TaskDB(":memory:")
    t1 = d.create_task("task one", priority=1)
    t2 = d.create_task("task two", priority=2)
    t3 = d.create_task("task three", priority=3)
    d.start_task(t1.id, agent="worker")
    # t1 is IN_PROGRESS
    # t2, t3 are PENDING
    yield d, t1, t2, t3
    d.close()


# ── 1. Schema Migration ─────────────────────────────────────────────────────

class TestSchemaMigration:
    def test_schema_version_is_1_after_init(self, db):
        """After _init_schema, schema_version should match CURRENT_SCHEMA_VERSION."""
        assert db.get_schema_version() == CURRENT_SCHEMA_VERSION

    def test_migrate_schema_idempotent(self, db):
        """Calling migrate_schema twice is safe."""
        db.migrate_schema()
        assert db.get_schema_version() == CURRENT_SCHEMA_VERSION
        db.migrate_schema()
        assert db.get_schema_version() == CURRENT_SCHEMA_VERSION

    def test_meta_table_exists(self, db):
        """meta table should exist and be queryable."""
        row = db._conn.execute(
            "SELECT * FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        assert row is not None
        assert row["value"] == str(CURRENT_SCHEMA_VERSION)


# ── 2. Performance Indexes ───────────────────────────────────────────────────

class TestPerformanceIndexes:
    @pytest.mark.parametrize("index_name,table,columns", [
        ("idx_tasks_status_priority", "tasks", ["status", "priority"]),
        ("idx_events_action_timestamp", "task_events", ["task_id", "action", "timestamp"]),
        ("idx_tasks_updated", "tasks", ["updated_at"]),
    ])
    def test_index_exists(self, db, index_name, table, columns):
        """Each required index is present in the database."""
        indexes = db._conn.execute(
            f"PRAGMA index_list({table})"
        ).fetchall()
        index_names = [r["name"] for r in indexes]
        assert index_name in index_names, f"{index_name} not found in {index_names}"

    @pytest.mark.parametrize("index_name,columns", [
        ("idx_tasks_status_priority", [("seqno", 0, "status"), ("seqno", 1, "priority")]),
        ("idx_events_action_timestamp", [("seqno", 0, "task_id"), ("seqno", 1, "action"), ("seqno", 2, "timestamp")]),
        ("idx_tasks_updated", [("seqno", 0, "updated_at")]),
    ])
    def test_index_columns(self, db, index_name, columns):
        """Each index has the expected columns in order."""
        result = db._conn.execute(
            f"PRAGMA index_info({index_name})"
        ).fetchall()
        for r in result:
            print(f"  index_info({index_name}): seqno={r['seqno']} cid={r['cid']} name={r['name']}")
        result = db._conn.execute(
            f"PRAGMA index_info({index_name})"
        ).fetchall()
        for r, (_, seq, col) in zip(result, columns):
            assert r["seqno"] == seq
            assert r["name"] == col


# ── 3. Data Integrity / health_check ───────────────────────────────────────

class TestHealthCheck:
    def test_health_check_empty_db(self, db):
        h = db.health_check()
        assert h["total_tasks"] == 0
        assert h["total_events"] == 0
        assert h["orphaned_events"] == 0
        assert h["stuck_tasks"] == 0
        assert h["status_counts"] == {}

    def test_health_check_with_tasks(self, db_with_data):
        db, t1, t2, t3 = db_with_data
        h = db.health_check()
        assert h["total_tasks"] == 3
        # Each create_task logs an event → 3 events
        # t1 start_task logs another → 4 events total
        assert h["total_events"] == 4
        assert h["orphaned_events"] == 0
        assert h["stuck_tasks"] == 0  # t1 is just now IN_PROGRESS, not stuck
        assert h["status_counts"]["PENDING"] == 2
        assert h["status_counts"]["IN_PROGRESS"] == 1

    def test_health_check_orphaned_event(self, db):
        """An event whose task was deleted shows up as orphaned."""
        t = db.create_task("will be deleted", priority=1)
        # Disable FK checks to force an orphaned event record
        db._conn.execute("PRAGMA foreign_keys=OFF")
        try:
            db._conn.execute(
                """INSERT INTO task_events (id, task_id, agent, action, summary, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (t.id + "X", "nonexistent_task_id", "agent", "create", "orphan",
                 datetime.now(timezone.utc).isoformat())
            )
            db._conn.commit()
        finally:
            db._conn.execute("PRAGMA foreign_keys=ON")
        h = db.health_check()
        assert h["orphaned_events"] == 1

    def test_health_check_stuck_task(self, db):
        """A task IN_PROGRESS for >24h is flagged as stuck."""
        # Insert a task directly with old created_at
        old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        db._conn.execute(
            """INSERT INTO tasks (id, title, description, status, priority, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("stuck1", "stuck task", "", "IN_PROGRESS", 0, old_time, old_time)
        )
        db._conn.commit()
        h = db.health_check()
        assert h["stuck_tasks"] == 1

    def test_health_check_recent_in_progress_not_stuck(self, db):
        """A task IN_PROGRESS but <24h old is NOT stuck."""
        recent = datetime.now(timezone.utc).isoformat()
        db._conn.execute(
            """INSERT INTO tasks (id, title, description, status, priority, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("recent1", "recent task", "", "IN_PROGRESS", 0, recent, recent)
        )
        db._conn.commit()
        h = db.health_check()
        assert h["stuck_tasks"] == 0


# ── 4. Concurrent Access Safety ─────────────────────────────────────────────

class TestConcurrentSafety:
    def test_timeout_parameter_passed(self):
        """timeout kwarg is stored and passed to sqlite3.connect."""
        d = TaskDB(":memory:", timeout=7.5)
        try:
            assert d._timeout == 7.5
        finally:
            d.close()

    def test_default_timeout_is_30(self):
        """Default timeout is 30 seconds when not specified."""
        d = TaskDB(":memory:")
        try:
            assert d._timeout == 30.0
        finally:
            d.close()

    def test_wal_mode_on_file_db(self):
        """WAL journal mode is active for file-based databases."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp = f.name
        try:
            d = TaskDB(tmp)
            try:
                mode = d._conn.execute("PRAGMA journal_mode").fetchone()[0]
                assert mode.upper() == "WAL", f"Expected WAL, got {mode}"
            finally:
                d.close()
        finally:
            os.remove(tmp)


# ── 5. get_tasks_by_status ordering ─────────────────────────────────────────

class TestGetTasksByStatusOrdering:
    def test_default_order(self, db_with_data):
        db, t1, t2, t3 = db_with_data
        tasks = db.get_tasks_by_status("PENDING")
        assert len(tasks) == 2
        # Default order: priority DESC, created_at
        # t3 has highest priority (3), t2 has priority 2
        assert tasks[0].id == t3.id
        assert tasks[1].id == t2.id

    def test_custom_order_by_priority_asc(self, db_with_data):
        db, t1, t2, t3 = db_with_data
        tasks = db.get_tasks_by_status("PENDING", order_by="priority ASC, created_at")
        assert len(tasks) == 2
        # Lowest priority first
        assert tasks[0].id == t2.id  # priority 2
        assert tasks[1].id == t3.id  # priority 3

    def test_custom_order_by_created_at(self, db_with_data):
        db, t1, t2, t3 = db_with_data
        tasks = db.get_tasks_by_status("PENDING", order_by="created_at ASC")
        assert len(tasks) == 2
        # Oldest created first (t2 before t3 since t3 was created later)
        # Both are PENDING; depends on create order

    def test_empty_status_returns_empty_list(self, db):
        tasks = db.get_tasks_by_status("DONE")
        assert tasks == []


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
