"""Smoke tests for scripts/session_reporter.py"""
import subprocess, sys

def test_help():
    r = subprocess.run(
        [sys.executable, "scripts/session_reporter.py", "--help"],
        capture_output=True, text=True, cwd="."
    )
    assert r.returncode == 0, f"help failed: {r.stderr}"
    assert "session" in r.stdout.lower()

def test_missing_db_handled_gracefully():
    """Should not crash when DB does not exist."""
    r = subprocess.run(
        [sys.executable, "scripts/session_reporter.py", "--db", "/nonexistent/nope.db"],
        capture_output=True, text=True, cwd="."
    )
    assert "Traceback" not in r.stderr, f"crashed: {r.stderr}"
    # Should print "(no tasks in DB)" or similar
    assert "Traceback" not in r.stderr

def test_last_flag():
    r = subprocess.run(
        [sys.executable, "scripts/session_reporter.py", "--last", "2"],
        capture_output=True, text=True, cwd="."
    )
    assert "Traceback" not in r.stderr, f"crashed: {r.stderr}"
