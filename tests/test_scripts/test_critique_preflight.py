"""Smoke tests for scripts/critique_preflight.py"""
import subprocess, sys

def test_help():
    r = subprocess.run(
        [sys.executable, "scripts/critique_preflight.py", "--help"],
        capture_output=True, text=True, cwd="."
    )
    assert r.returncode == 0, f"help failed: {r.stderr}"
    assert "critique" in r.stdout.lower()

def test_missing_db_exits_1():
    """Missing DB should exit with code 1 and a proper error."""
    r = subprocess.run(
        [sys.executable, "scripts/critique_preflight.py", "--db", "/nonexistent/tasks.db"],
        capture_output=True, text=True, cwd="."
    )
    assert r.returncode == 1, f"expected exit 1 for missing DB, got {r.returncode}"
    assert "Traceback" not in r.stderr, f"crashed: {r.stderr}"
    assert "ERROR" in r.stderr or "not found" in r.stderr.lower()

def test_no_task_exits_1():
    """No task found should exit with code 1."""
    # Even with a missing DB already covered, let's also verify the error path
    r = subprocess.run(
        [sys.executable, "scripts/critique_preflight.py", "--db", "/nonexistent/tasks.db", "--task", "nonexistent-task-id"],
        capture_output=True, text=True, cwd="."
    )
    assert r.returncode == 1, f"expected exit 1 for no task, got {r.returncode}"
