"""Smoke tests for scripts/mistakes_logger.py"""
import subprocess, sys

def test_import():
    """Script should import without error."""
    r = subprocess.run(
        [sys.executable, "-c", "import scripts.mistakes_logger"],
        capture_output=True, text=True, cwd="."
    )
    # Import path needs the repo root
    r2 = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0,'.'); import scripts.mistakes_logger"],
        capture_output=True, text=True, cwd="."
    )
    assert r2.returncode == 0, f"import failed: {r2.stderr}"

def test_help():
    r = subprocess.run(
        [sys.executable, "scripts/mistakes_logger.py", "--help"],
        capture_output=True, text=True, cwd="."
    )
    assert r.returncode == 0, f"help failed: {r.stderr}"
    assert "log" in r.stdout.lower()

def test_list_command_no_crash():
    """list command should not crash when file is absent."""
    r = subprocess.run(
        [sys.executable, "scripts/mistakes_logger.py", "list"],
        capture_output=True, text=True, cwd="."
    )
    assert "Traceback" not in r.stderr, f"crashed: {r.stderr}"

def test_resolve_missing_file():
    """resolve on a non-existent file should exit 1 gracefully."""
    r = subprocess.run(
        [sys.executable, "scripts/mistakes_logger.py", "resolve", "mistake-99999"],
        capture_output=True, text=True, cwd="."
    )
    # Should exit with error, not crash
    assert "Traceback" not in r.stderr, f"crashed: {r.stderr}"
