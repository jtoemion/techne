"""
tests/tests_task_db.py — Tests for TaskDB lifecycle hardening (Domain 3).

Run with: python3 -m pytest tests/tests_task_db.py -v
"""

import json, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

from task_db import TaskDB, CURRENT_SCHEMA_VERSION


def test_migration_adds_notes_column(tmp_path):
    """Migration v1→v2 should add notes column to tasks table."""
    # Create DB with v1 schema — match what TaskDB v1 would create
    db_path = tmp_path / "test_migrate.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta (key, value) VALUES ('schema_version', '1');
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            parent_id TEXT,
            discipline TEXT DEFAULT 'tdd',
            status TEXT DEFAULT 'PENDING',
            assigned_agent TEXT,
            priority INTEGER DEFAULT 0,
            tags TEXT DEFAULT '[]',
            phase_mode TEXT DEFAULT 'full',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            attempt INTEGER DEFAULT 0,
            max_attempts INTEGER DEFAULT 3
        );
        CREATE TABLE IF NOT EXISTS task_events (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            agent TEXT NOT NULL,
            action TEXT NOT NULL,
            summary TEXT DEFAULT '',
            changed_files TEXT DEFAULT '[]',
            diff_summary TEXT DEFAULT '',
            findings TEXT DEFAULT '',
            verdict TEXT DEFAULT '',
            test_output_hash TEXT DEFAULT '',
            mistakes_found TEXT DEFAULT '[]',
            timestamp TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()
    
    # Open with TaskDB — should trigger v1→v2 migration
    db = TaskDB(str(db_path))
    assert db.get_schema_version() >= 2, f"Expected v2+, got v{db.get_schema_version()}"
    
    # Verify notes column exists
    cols = [r[1] for r in db._conn.execute("PRAGMA table_info(tasks)").fetchall()]
    assert "notes" in cols, f"notes column missing from tasks table: {cols}"
    db.close()


def test_migration_idempotent(tmp_path):
    """Opening twice should not fail — second open skips migration."""
    db_path = tmp_path / "test_idempotent.db"
    db1 = TaskDB(str(db_path))
    v1 = db1.get_schema_version()
    db1.close()
    
    db2 = TaskDB(str(db_path))
    v2 = db2.get_schema_version()
    assert v1 == v2, f"Versions differ: {v1} vs {v2}"
    
    # Verify notes column exists
    cols = [r[1] for r in db2._conn.execute("PRAGMA table_info(tasks)").fetchall()]
    assert "notes" in cols
    db2.close()


def test_prune_orphaned_events(tmp_path):
    """prune_orphaned_events() deletes events with no matching task."""
    db = TaskDB(str(tmp_path / "test_prune.db"))
    
    # Create a task
    task = db.create_task("test task")
    
    # Manually insert an orphaned event (different task_id)
    # Disable FK check temporarily to insert the orphan
    db._conn.execute("PRAGMA foreign_keys=OFF")
    db._conn.execute(
        "INSERT INTO task_events (id, task_id, agent, action, timestamp) VALUES (?, ?, ?, ?, ?)",
        ("orphan-1", "no-such-task", "test", "test", datetime.now(timezone.utc).isoformat())
    )
    db._conn.execute("PRAGMA foreign_keys=ON")
    db._conn.commit()
    
    # Verify orphan exists
    health = db.health_check()
    assert health["orphaned_events"] >= 1, "Orphaned event should exist"
    
    # Prune
    count = db.prune_orphaned_events()
    assert count >= 1, f"Expected ≥1 pruned, got {count}"
    
    # Verify gone
    health2 = db.health_check()
    assert health2["orphaned_events"] == 0, "Orphaned events should be 0 after prune"
    db.close()


def test_release_stuck_tasks(tmp_path):
    """release_stuck_tasks() resets IN_PROGRESS tasks stuck for >hours."""
    db = TaskDB(str(tmp_path / "test_stuck.db"))
    
    # Create a task and force it to IN_PROGRESS with old timestamp
    task = db.create_task("stuck task")
    old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    db._conn.execute(
        "UPDATE tasks SET status = 'IN_PROGRESS', created_at = ? WHERE id = ?",
        (old_time, task.id)
    )
    db._conn.commit()
    
    # Verify stuck
    health = db.health_check()
    assert health["stuck_tasks"] >= 1, "Expected stuck task"
    
    # Release
    count = db.release_stuck_tasks(hours=24)
    assert count >= 1, f"Expected ≥1 released, got {count}"
    
    # Verify reset to PENDING
    task2 = db.get_task(task.id)
    assert task2.status == "PENDING", f"Expected PENDING, got {task2.status}"
    db.close()


def test_get_tasks_by_column_valid(tmp_path):
    """get_tasks_by_column() returns matching tasks for valid column."""
    db = TaskDB(str(tmp_path / "test_column.db"))
    t1 = db.create_task("task alpha", tags=["p1"])
    t2 = db.create_task("task beta", tags=["p2"])
    t3 = db.create_task("task alpha", tags=["p3"])
    
    results = db.get_tasks_by_column("title", "task alpha")
    assert len(results) == 2, f"Expected 2, got {len(results)}"
    ids = {r["id"] for r in results}
    assert t1.id in ids and t3.id in ids
    
    results2 = db.get_tasks_by_column("title", "task beta")
    assert len(results2) == 1
    assert results2[0]["id"] == t2.id
    db.close()


def test_get_tasks_by_column_injection_raises(tmp_path):
    """get_tasks_by_column() raises ValueError for invalid column names."""
    db = TaskDB(str(tmp_path / "test_inject.db"))
    
    # SQL injection attempt
    try:
        db.get_tasks_by_column("id; DROP TABLE tasks; --", "test")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Invalid column" in str(e)
    
    # Non-existent column
    try:
        db.get_tasks_by_column("fake_column", "test")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Invalid column" in str(e)
    
    # Empty string
    try:
        db.get_tasks_by_column("", "test")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Invalid column" in str(e)
    
    db.close()


def test_get_tasks_by_column_notes(tmp_path):
    """get_tasks_by_column() works with the new notes column."""
    db = TaskDB(str(tmp_path / "test_notes_col.db"))
    t1 = db.create_task("notes test")
    
    # Set notes via raw SQL (TaskDB.create_task doesn't expose notes yet)
    db._conn.execute(
        "UPDATE tasks SET notes = ? WHERE id = ?",
        ("migration note", t1.id)
    )
    db._conn.commit()
    
    results = db.get_tasks_by_column("notes", "migration note")
    assert len(results) == 1
    assert results[0]["id"] == t1.id
    db.close()


def test_health_check_returns_new_fields(tmp_path):
    """health_check() returns all expected fields including new ones."""
    db = TaskDB(str(tmp_path / "test_health.db"))
    health = db.health_check()
    
    expected = {"total_tasks", "total_events", "orphaned_events", "stuck_tasks", "status_counts"}
    assert expected.issubset(health.keys()), f"Missing fields: {expected - health.keys()}"
    db.close()
