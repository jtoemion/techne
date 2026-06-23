"""Smoke tests for scripts/pipeline_health.py"""
import subprocess, sys

def test_help():
    """--help flag should exit cleanly."""
    r = subprocess.run(
        [sys.executable, "scripts/pipeline_health.py", "--help"],
        capture_output=True, text=True, cwd="."
    )
    assert r.returncode == 0, f"help flag failed: {r.stderr}"
    assert "pipeline health" in r.stdout.lower()

def test_quick_no_crash():
    """--quick should not crash even without a DB."""
    r = subprocess.run(
        [sys.executable, "scripts/pipeline_health.py", "--quick"],
        capture_output=True, text=True, cwd="."
    )
    # Should not crash (returncode 0 or 1 is fine, just no traceback)
    assert "Traceback" not in r.stderr, f"crashed: {r.stderr}"

def test_custom_db_flag():
    """--db flag should be accepted."""
    r = subprocess.run(
        [sys.executable, "scripts/pipeline_health.py", "--db", "/nonexistent/tasks.db"],
        capture_output=True, text=True, cwd="."
    )
    # Should not crash on a missing DB, just report it
    assert "Traceback" not in r.stderr, f"crashed: {r.stderr}"
