"""
task_db.py — Lightweight SQLite task database for the orchestrator.

Each task is atomic, TDD-natured, and tracked through a lifecycle:
  PENDING → IN_PROGRESS → IMPLEMENTED → REVIEWED → VERIFIED → DONE
                                                        ↘ BLOCKED → (retry)

The orchestrator creates tasks, assigns subagents, and records outcomes.
Every change is logged with task_id + diff summary for the context-guard.

Usage:
    from task_db import TaskDB

    db = TaskDB()                        # default: techne/memory/tasks.db
    t = db.create_task("add rate limiter", parent_id=None, discipline="tdd")
    db.start_task(t.id, agent="implementer")
    db.complete_task(t.id, agent="implementer", summary="token bucket, 14 tests",
                     changed_files=["rate_limiter.py"], diff_summary="+87 -3")
    db.review_task(t.id, agent="reviewer", verdict="PASS", findings="...")
    db.verify_task(t.id, agent="verifier", test_output_hash="abc123...")
    db.block_task(t.id, reason="needs auth decision", agent="critique")

    # Query
    tasks = db.get_tasks_by_status("PENDING")
    history = db.get_task_history(t.id)
    stats = db.get_mistake_stats()       # for reinforcement learning
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

HARNESS_DIR = Path(__file__).parent
MEMORY_DIR = HARNESS_DIR.parent / ".techne" / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

DEFAULT_DB = MEMORY_DIR / "tasks.db"

STATUSES = [
    "PENDING", "IN_PROGRESS", "IMPLEMENTED", "REVIEWED",
    "VERIFIED", "DONE", "BLOCKED", "FAILED",
]


@dataclass
class Task:
    id: str
    title: str
    description: str = ""
    parent_id: Optional[str] = None
    discipline: str = "tdd"           # tdd | implement | review | debug | retro
    status: str = "PENDING"
    assigned_agent: Optional[str] = None
    priority: int = 0                 # higher = more urgent
    tags: list[str] = field(default_factory=list)
    phase_mode: str = "full"          # full (10 phases) | fast (skip RECALL+CONCLUDE)
    created_at: str = ""
    updated_at: str = ""
    attempt: int = 0                  # how many times an agent has tried this
    max_attempts: int = 3             # before escalating to debugger

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


@dataclass
class TaskEvent:
    """Immutable log entry — one per agent action on a task."""
    id: str
    task_id: str
    agent: str                        # implementer | reviewer | context-guard | critique | debugger | retro
    action: str                       # start | complete | review | verify | block | fix | observe | critique
    summary: str = ""
    changed_files: list[str] = field(default_factory=list)
    diff_summary: str = ""            # +N -M lines, or brief description
    findings: str = ""                # reviewer/critique output
    verdict: str = ""                 # PASS | SOFT_FAIL | HARD_FAIL | BLOCK
    test_output_hash: str = ""
    mistakes_found: list[str] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


CURRENT_SCHEMA_VERSION = 1


class TaskDB:
    """
    SQLite-backed task database.

    Thread-safe for single-process use: SQLite's WAL mode allows concurrent
    readers while a writer holds an exclusive lock. For multi-process access,
    use separate TaskDB instances per process (SQLite's file-level locking
    handles contention). Connection pooling is not implemented; each instance
    owns one connection.
    """

    def __init__(self, db_path: str | Path | None = None, *, timeout: float = 30.0):
        self.db_path = str(db_path or DEFAULT_DB)
        self._timeout = timeout
        self._conn = sqlite3.connect(self.db_path, timeout=timeout)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

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
                max_attempts INTEGER DEFAULT 3,
                FOREIGN KEY (parent_id) REFERENCES tasks(id)
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
                timestamp TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_id);
            CREATE INDEX IF NOT EXISTS idx_events_task ON task_events(task_id);
            CREATE INDEX IF NOT EXISTS idx_events_agent ON task_events(agent);

            CREATE INDEX IF NOT EXISTS idx_tasks_status_priority ON tasks(status, priority DESC);
            CREATE INDEX IF NOT EXISTS idx_events_action_timestamp ON task_events(task_id, action, timestamp);
            CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at DESC);
        """)
        self._conn.commit()
        self.migrate_schema()

    def get_schema_version(self) -> int:
        """Return current schema version, or 0 if meta table is empty."""
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        return int(row["value"]) if row else 0

    def migrate_schema(self):
        """Apply migrations up to CURRENT_SCHEMA_VERSION."""
        version = self.get_schema_version()
        if version >= CURRENT_SCHEMA_VERSION:
            return
        # v0 -> v1: initial meta table with schema_version
        if version < 1:
            self._conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '1')"
            )
            self._conn.commit()
        # Future migrations go here
        # if version < 2:
        #     ...

    def health_check(self) -> dict:
        """
        Data integrity report. Checks:
        - orphaned_events: task_events rows with no matching task
        - stuck_tasks: tasks in IN_PROGRESS for >24 hours (by created_at)
        """
        total_tasks = self._conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        total_events = self._conn.execute("SELECT COUNT(*) FROM task_events").fetchone()[0]

        orphaned = self._conn.execute("""
            SELECT COUNT(*) FROM task_events e
            LEFT JOIN tasks t ON t.id = e.task_id
            WHERE t.id IS NULL
        """).fetchone()[0]

        # stuck tasks: IN_PROGRESS for >24h
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        stuck = self._conn.execute("""
            SELECT COUNT(*) FROM tasks
            WHERE status = 'IN_PROGRESS' AND created_at < ?
        """, (cutoff,)).fetchone()[0]

        status_counts = dict(self._conn.execute(
            "SELECT status, COUNT(*) FROM tasks GROUP BY status"
        ).fetchall())

        return {
            "total_tasks": total_tasks,
            "total_events": total_events,
            "orphaned_events": orphaned,
            "stuck_tasks": stuck,
            "status_counts": status_counts,
        }

    # ── Task CRUD ────────────────────────────────────────────────────────

    def create_task(
        self,
        title: str,
        *,
        description: str = "",
        parent_id: str | None = None,
        discipline: str = "tdd",
        priority: int = 0,
        tags: list[str] | None = None,
        phase_mode: str = "full",
    ) -> Task:
        """Create a new atomic task. Returns the Task with a generated ID."""
        task = Task(
            id=_new_id(),
            title=title,
            description=description,
            parent_id=parent_id,
            discipline=discipline,
            priority=priority,
            tags=tags or [],
            phase_mode=phase_mode,
        )
        self._conn.execute(
            """INSERT INTO tasks (id, title, description, parent_id, discipline,
               status, assigned_agent, priority, tags, phase_mode, created_at, updated_at,
               attempt, max_attempts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task.id, task.title, task.description, task.parent_id,
             task.discipline, task.status, task.assigned_agent, task.priority,
             json.dumps(task.tags), task.phase_mode, task.created_at, task.updated_at,
             task.attempt, task.max_attempts),
        )
        self._conn.commit()
        self._log_event(task.id, "orchestrator", "create", f"Task created: {title}")
        return task

    def get_task(self, task_id: str) -> Task | None:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            return None
        return _row_to_task(row)

    def get_tasks_by_status(self, status: str, *, order_by: str = "priority DESC, created_at") -> list[Task]:
        rows = self._conn.execute(
            f"SELECT * FROM tasks WHERE status = ? ORDER BY {order_by}",
            (status,),
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def get_children(self, parent_id: str) -> list[Task]:
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE parent_id = ? ORDER BY priority DESC, created_at",
            (parent_id,),
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def get_all_tasks(self) -> list[Task]:
        rows = self._conn.execute(
            "SELECT * FROM tasks ORDER BY priority DESC, created_at"
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def count_by_status(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"
        ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    # ── Status Transitions ───────────────────────────────────────────────

    def start_task(self, task_id: str, *, agent: str) -> Task:
        """Assign an agent and move to IN_PROGRESS."""
        task = self._get_or_raise(task_id)
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """UPDATE tasks SET status = 'IN_PROGRESS', assigned_agent = ?,
               attempt = attempt + 1, updated_at = ? WHERE id = ?""",
            (agent, now, task_id),
        )
        self._conn.commit()
        self._log_event(task_id, agent, "start", f"Attempt #{task.attempt + 1}")
        return self.get_task(task_id)

    def complete_task(
        self,
        task_id: str,
        *,
        agent: str,
        summary: str,
        changed_files: list[str] | None = None,
        diff_summary: str = "",
    ) -> Task:
        """Mark implementation complete. Moves to IMPLEMENTED."""
        self._get_or_raise(task_id)
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE tasks SET status = 'IMPLEMENTED', updated_at = ? WHERE id = ?",
            (now, task_id),
        )
        self._conn.commit()
        self._log_event(
            task_id, agent, "complete", summary,
            changed_files=changed_files or [], diff_summary=diff_summary,
        )
        return self.get_task(task_id)

    def review_task(
        self,
        task_id: str,
        *,
        agent: str,
        verdict: str,
        findings: str = "",
        mistakes_found: list[str] | None = None,
    ) -> Task:
        """Record review outcome. Moves to REVIEWED on PASS, BLOCKED on HARD_FAIL."""
        self._get_or_raise(task_id)
        new_status = "REVIEWED" if verdict in ("PASS", "SOFT_FAIL") else "BLOCKED"
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now, task_id),
        )
        self._conn.commit()
        self._log_event(
            task_id, agent, "review", findings[:200],
            verdict=verdict, findings=findings,
            mistakes_found=mistakes_found or [],
        )
        return self.get_task(task_id)

    def verify_task(
        self,
        task_id: str,
        *,
        agent: str,
        test_output_hash: str = "",
        summary: str = "",
    ) -> Task:
        """Record verification. Moves to VERIFIED."""
        self._get_or_raise(task_id)
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE tasks SET status = 'VERIFIED', updated_at = ? WHERE id = ?",
            (now, task_id),
        )
        self._conn.commit()
        self._log_event(
            task_id, agent, "verify", summary,
            test_output_hash=test_output_hash,
        )
        return self.get_task(task_id)

    def done_task(self, task_id: str, *, agent: str = "orchestrator") -> Task:
        """Final state. Moves to DONE."""
        self._get_or_raise(task_id)
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE tasks SET status = 'DONE', updated_at = ? WHERE id = ?",
            (now, task_id),
        )
        self._conn.commit()
        self._log_event(task_id, agent, "done", "Task complete")
        return self.get_task(task_id)

    def block_task(
        self,
        task_id: str,
        *,
        reason: str,
        agent: str,
    ) -> Task:
        """Block a task — needs human input or debugger escalation."""
        self._get_or_raise(task_id)
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE tasks SET status = 'BLOCKED', updated_at = ? WHERE id = ?",
            (now, task_id),
        )
        self._conn.commit()
        self._log_event(task_id, agent, "block", reason)
        return self.get_task(task_id)

    def fail_task(self, task_id: str, *, agent: str, reason: str) -> Task:
        """Terminal failure. Moves to FAILED."""
        self._get_or_raise(task_id)
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE tasks SET status = 'FAILED', updated_at = ? WHERE id = ?",
            (now, task_id),
        )
        self._conn.commit()
        self._log_event(task_id, agent, "fail", reason)
        return self.get_task(task_id)

    def reset_task(self, task_id: str, *, to_status: str = "PENDING") -> Task:
        """Reset a blocked/failed task for retry."""
        self._get_or_raise(task_id)
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
            (to_status, now, task_id),
        )
        self._conn.commit()
        self._log_event(task_id, "orchestrator", "reset", f"Reset to {to_status}")
        return self.get_task(task_id)

    # ── Event Log (Context-Guard feed) ───────────────────────────────────

    def get_task_history(self, task_id: str) -> list[TaskEvent]:
        """Full event log for a task. The context-guard reads this."""
        rows = self._conn.execute(
            "SELECT * FROM task_events WHERE task_id = ? ORDER BY timestamp",
            (task_id,),
        ).fetchall()
        return [_row_to_event(r) for r in rows]

    def get_recent_events(self, limit: int = 20) -> list[TaskEvent]:
        rows = self._conn.execute(
            "SELECT * FROM task_events ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_event(r) for r in rows]

    def get_events_by_agent(self, agent: str, limit: int = 50) -> list[TaskEvent]:
        rows = self._conn.execute(
            "SELECT * FROM task_events WHERE agent = ? ORDER BY timestamp DESC LIMIT ?",
            (agent, limit),
        ).fetchall()
        return [_row_to_event(r) for r in rows]

    def get_mistake_stats(self) -> dict:
        """
        Aggregate mistake data for reinforcement learning.
        Returns counts by agent, verdict, and recurring patterns.
        """
        # Mistakes by agent
        agent_rows = self._conn.execute("""
            SELECT agent, COUNT(*) as cnt FROM task_events
            WHERE action IN ('review', 'block', 'fail')
            AND verdict IN ('HARD_FAIL', 'BLOCK')
            GROUP BY agent ORDER BY cnt DESC
        """).fetchall()

        # Mistakes by task (tasks that were blocked or failed)
        task_rows = self._conn.execute("""
            SELECT t.id, t.title, t.attempt, t.status,
                   COUNT(CASE WHEN e.verdict IN ('HARD_FAIL','BLOCK') THEN 1 END) as fail_count
            FROM tasks t
            JOIN task_events e ON e.task_id = t.id
            WHERE t.attempt > 1
            GROUP BY t.id
            ORDER BY fail_count DESC, t.attempt DESC
        """).fetchall()

        # Recurring mistake patterns (from mistakes_found field)
        pattern_rows = self._conn.execute("""
            SELECT mistakes_found FROM task_events
            WHERE mistakes_found != '[]' AND mistakes_found != ''
        """).fetchall()

        all_mistakes = []
        for row in pattern_rows:
            try:
                mistakes = json.loads(row["mistakes_found"])
                all_mistakes.extend(mistakes)
            except (json.JSONDecodeError, TypeError):
                pass

        # Count occurrences
        pattern_counts = {}
        for m in all_mistakes:
            key = m.strip().lower() if isinstance(m, str) else str(m)
            pattern_counts[key] = pattern_counts.get(key, 0) + 1

        return {
            "by_agent": {r["agent"]: r["cnt"] for r in agent_rows},
            "by_task": [
                {"id": r["id"], "title": r["title"], "attempts": r["attempt"],
                 "status": r["status"], "fail_count": r["fail_count"]}
                for r in task_rows
            ],
            "recurring_patterns": dict(
                sorted(pattern_counts.items(), key=lambda x: -x[1])
            ),
            "total_tasks": self._conn.execute(
                "SELECT COUNT(*) FROM tasks"
            ).fetchone()[0],
            "total_events": self._conn.execute(
                "SELECT COUNT(*) FROM task_events"
            ).fetchone()[0],
        }

    def get_heavy_mistake_tasks(self, threshold: int = 2) -> list[Task]:
        """Tasks that failed or were blocked >= threshold times. Debugger candidates."""
        rows = self._conn.execute("""
            SELECT * FROM tasks WHERE attempt >= ? AND status IN ('BLOCKED', 'FAILED')
            ORDER BY attempt DESC
        """, (threshold,)).fetchall()
        return [_row_to_task(r) for r in rows]

    # ── Dashboard ────────────────────────────────────────────────────────

    def dashboard(self) -> str:
        """Human-readable status board."""
        counts = self.count_by_status()
        total = sum(counts.values())
        lines = [
            "=" * 50,
            f"TASK BOARD — {total} tasks",
            "=" * 50,
        ]
        for status in STATUSES:
            cnt = counts.get(status, 0)
            if cnt > 0:
                bar = "█" * min(cnt, 30)
                lines.append(f"  {status:12}: {cnt:3d}  {bar}")

        # Show in-progress tasks
        in_progress = self.get_tasks_by_status("IN_PROGRESS")
        if in_progress:
            lines.append("")
            lines.append("IN PROGRESS:")
            for t in in_progress:
                lines.append(f"  [{t.id[:8]}] {t.title} (agent: {t.assigned_agent}, attempt #{t.attempt})")

        # Show blocked tasks
        blocked = self.get_tasks_by_status("BLOCKED")
        if blocked:
            lines.append("")
            lines.append("BLOCKED:")
            for t in blocked:
                history = self.get_task_history(t.id)
                last_block = next(
                    (e for e in reversed(history) if e.action == "block"), None
                )
                reason = last_block.summary if last_block else "unknown"
                lines.append(f"  [{t.id[:8]}] {t.title} — {reason}")

        # Debugger candidates
        heavy = self.get_heavy_mistake_tasks()
        if heavy:
            lines.append("")
            lines.append("DEBUGGER CANDIDATES (≥2 failures):")
            for t in heavy:
                lines.append(f"  [{t.id[:8]}] {t.title} (attempts: {t.attempt})")

        lines.append("=" * 50)
        return "\n".join(lines)

    # ── Internal ─────────────────────────────────────────────────────────

    def _log_event(
        self,
        task_id: str,
        agent: str,
        action: str,
        summary: str = "",
        **kwargs,
    ):
        event = TaskEvent(
            id=_new_id(),
            task_id=task_id,
            agent=agent,
            action=action,
            summary=summary,
            **kwargs,
        )
        self._conn.execute(
            """INSERT INTO task_events
               (id, task_id, agent, action, summary, changed_files,
                diff_summary, findings, verdict, test_output_hash,
                mistakes_found, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event.id, event.task_id, event.agent, event.action,
             event.summary, json.dumps(event.changed_files),
             event.diff_summary, event.findings, event.verdict,
             event.test_output_hash, json.dumps(event.mistakes_found),
             event.timestamp),
        )
        self._conn.commit()

    def _get_or_raise(self, task_id: str) -> Task:
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        return task

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ── Helpers ──────────────────────────────────────────────────────────────

def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        title=row["title"],
        description=row["description"] or "",
        parent_id=row["parent_id"],
        discipline=row["discipline"] or "tdd",
        status=row["status"],
        assigned_agent=row["assigned_agent"],
        priority=row["priority"] or 0,
        tags=json.loads(row["tags"]) if row["tags"] else [],
        phase_mode=row["phase_mode"] if "phase_mode" in row.keys() else "full",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        attempt=row["attempt"] or 0,
        max_attempts=row["max_attempts"] or 3,
    )


def _row_to_event(row: sqlite3.Row) -> TaskEvent:
    return TaskEvent(
        id=row["id"],
        task_id=row["task_id"],
        agent=row["agent"],
        action=row["action"],
        summary=row["summary"] or "",
        changed_files=json.loads(row["changed_files"]) if row["changed_files"] else [],
        diff_summary=row["diff_summary"] or "",
        findings=row["findings"] or "",
        verdict=row["verdict"] or "",
        test_output_hash=row["test_output_hash"] or "",
        mistakes_found=json.loads(row["mistakes_found"]) if row["mistakes_found"] else [],
        timestamp=row["timestamp"],
    )


if __name__ == "__main__":
    # Smoke test
    db = TaskDB("/tmp/test_tasks.db")
    t1 = db.create_task("add rate limiter", discipline="tdd")
    t2 = db.create_task("add auth middleware", parent_id=t1.id, discipline="tdd")
    db.start_task(t1.id, agent="implementer")
    db.complete_task(t1.id, agent="implementer", summary="token bucket impl",
                     changed_files=["rate_limiter.py"], diff_summary="+87 -3")
    db.review_task(t1.id, agent="reviewer", verdict="PASS", findings="clean")
    db.verify_task(t1.id, agent="verifier", test_output_hash="abc123")
    db.done_task(t1.id)
    print(db.dashboard())
    stats = db.get_mistake_stats()
    print(f"\nMistake stats: {json.dumps(stats, indent=2)}")
    db.close()
    import os
    os.remove("/tmp/test_tasks.db")
    print("\nSmoke test passed.")
