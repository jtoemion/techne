"""Smoke tests for scripts/knowledge_graph.py"""
import subprocess, sys

def test_help():
    r = subprocess.run(
        [sys.executable, "scripts/knowledge_graph.py", "--help"],
        capture_output=True, text=True, cwd="."
    )
    assert r.returncode == 0, f"help failed: {r.stderr}"
    assert "knowledge" in r.stdout.lower() or "graph" in r.stdout.lower()

def test_status_command_no_db():
    """status command should not crash when wikilinks.json is absent."""
    r = subprocess.run(
        [sys.executable, "scripts/knowledge_graph.py", "status"],
        capture_output=True, text=True, cwd="."
    )
    assert "Traceback" not in r.stderr, f"crashed: {r.stderr}"

def test_phases_command_no_db():
    """phases command should handle missing tasks.db gracefully."""
    r = subprocess.run(
        [sys.executable, "scripts/knowledge_graph.py", "phases"],
        capture_output=True, text=True, cwd="."
    )
    assert "Traceback" not in r.stderr, f"crashed: {r.stderr}"

def test_mistakes_command_no_file():
    """mistakes command should handle missing mistakes.md gracefully."""
    r = subprocess.run(
        [sys.executable, "scripts/knowledge_graph.py", "mistakes"],
        capture_output=True, text=True, cwd="."
    )
    assert "Traceback" not in r.stderr, f"crashed: {r.stderr}"

def test_skill_command():
    r = subprocess.run(
        [sys.executable, "scripts/knowledge_graph.py", "skill", "nonexistent"],
        capture_output=True, text=True, cwd="."
    )
    assert "Traceback" not in r.stderr, f"crashed: {r.stderr}"

def test_search_command():
    r = subprocess.run(
        [sys.executable, "scripts/knowledge_graph.py", "search", "test"],
        capture_output=True, text=True, cwd="."
    )
    assert "Traceback" not in r.stderr, f"crashed: {r.stderr}"
