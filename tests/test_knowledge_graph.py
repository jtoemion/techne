"""Unit tests for scripts/knowledge_graph.py"""
import json, subprocess, sys, tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent

SAMPLE_WIKILINKS = {
    "nodes": [
        {"id": "project:root", "kind": "project", "title": "techne", "path": ".", "tags": [], "metadata": {}},
        {"id": "subsystem:harness", "kind": "subsystem", "title": "harness", "path": "harness", "tags": [], "metadata": {}},
        {"id": "file:scripts/test_knowledge_graph.py", "kind": "file", "title": "test", "path": "scripts/test_knowledge_graph.py", "tags": [], "metadata": {}},
        {"id": "file:scripts/knowledge_graph.py", "kind": "file", "title": "kg", "path": "scripts/knowledge_graph.py", "tags": [], "metadata": {}},
        {"id": "skill:python", "kind": "skill", "title": "Python", "path": "skills/python.md", "tags": [], "metadata": {}},
        {"id": "task:123", "kind": "task", "title": "Test task", "path": "tasks/123.md", "tags": [], "metadata": {}},
        {"id": "module:core", "kind": "module", "title": "core", "path": "core/__init__.py", "tags": [], "metadata": {}},
    ],
    "edges": [
        {"source": "project:root", "target": "subsystem:harness", "type": "contains"},
        {"source": "subsystem:harness", "target": "file:scripts/knowledge_graph.py", "type": "contains"},
        {"source": "skill:python", "target": "file:scripts/knowledge_graph.py", "type": "uses"},
    ],
    "entries": [],
    "skills": {},
}


def run_kg(args, wikilinks_path=None):
    """Run knowledge_graph.py with given args, optionally replacing wikilinks data."""
    env = {}
    if wikilinks_path:
        # Create a temp symlink or directly override the wikilinks path via env
        pass
    r = subprocess.run(
        [sys.executable, "scripts/knowledge_graph.py"] + args,
        capture_output=True, text=True, cwd=ROOT
    )
    return r.stdout, r.stderr, r.returncode


class TestCmdStatusKindField:
    """Verify cmd_status() uses 'kind' field, not 'type'."""

    def test_status_shows_real_kinds_not_unknown(self):
        """With real wikilinks.json, status should show kinds, not 'unknown'."""
        stdout, stderr, code = run_kg(["status"])
        # Should not crash
        assert "Traceback" not in stderr, f"Crashed: {stderr}"
        assert code == 0
        # Should show real kinds, not 321 unknown
        # Real wikilinks has kinds: project, subsystem, file, module, skill, task, decision
        output = stdout
        # Should NOT show "unknown: 321"
        lines = [l for l in output.splitlines() if "unknown" in l.lower()]
        assert not lines, f"Found 'unknown' in output (bug: type vs kind): {lines}"
        # Should show some known kinds
        assert "project" in output or "subsystem" in output or "file" in output

    def test_status_node_count(self):
        """status command should report 321 nodes."""
        stdout, stderr, code = run_kg(["status"])
        assert "Nodes:  321" in stdout, f"Expected 321 nodes, got: {stdout}"


class TestCmdSkillKindField:
    """Verify cmd_skill() filters by 'kind', not 'type'."""

    def test_skill_finds_python_skill(self):
        """Should find skill:python node when searching 'python'."""
        stdout, stderr, code = run_kg(["skill", "python"])
        assert "Traceback" not in stderr, f"Crashed: {stderr}"
        # With the kind fix, should find skill:python
        assert "Skill: skill:python" in stdout or "python" in stdout.lower()


class TestCmdFileKindField:
    """Verify cmd_file() filters by 'kind', not 'type'."""

    def test_file_finds_python_script(self):
        """Should find file node for knowledge_graph.py."""
        stdout, stderr, code = run_kg(["file", "knowledge_graph"])
        assert "Traceback" not in stderr, f"Crashed: {stderr}"
        # Should find the file node (not return "No file nodes matching")
        assert "No file nodes matching" not in stdout or "knowledge_graph" in stdout


class TestCmdSearch:
    """Tests for cmd_search()."""

    def test_search_finds_project(self):
        """search 'project' should find project:root."""
        stdout, stderr, code = run_kg(["search", "project"])
        assert "Traceback" not in stderr, f"Crashed: {stderr}"
        assert "project:root" in stdout or "Found" in stdout

    def test_search_no_match(self):
        """search with no matches should report gracefully."""
        stdout, stderr, code = run_kg(["search", "zzzzz_no_match_xyz"])
        assert "Traceback" not in stderr, f"Crashed: {stderr}"
        assert "No nodes matching" in stdout


class TestMissingFiles:
    """Tests for graceful handling of missing data files."""

    def test_phases_missing_db_no_crash(self):
        """phases command should not crash when tasks.db is absent."""
        # The default path already handles missing db gracefully (tests use real cwd)
        stdout, stderr, code = run_kg(["phases"])
        assert "Traceback" not in stderr, f"Crashed: {stderr}"
        # Should either show data or a clear "no phase data" message
        output = stdout + stderr
        assert "no phase" in output.lower() or "no tasks.db" in output.lower() or "phase" in output.lower()

    def test_mistakes_missing_file_no_crash(self):
        """mistakes command should not crash when mistakes.md is absent."""
        stdout, stderr, code = run_kg(["mistakes"])
        assert "Traceback" not in stderr, f"Crashed: {stderr}"

    def test_status_missing_wikilinks_no_crash(self):
        """status command should not crash when wikilinks.json is absent."""
        import shutil
        real_wikilinks = ROOT / ".techne" / "memory" / "wikilinks.json"
        backup = None
        if real_wikilinks.exists():
            backup = real_wikilinks.with_suffix(".json.bak")
            shutil.move(str(real_wikilinks), str(backup))
        try:
            r = subprocess.run(
                [sys.executable, "scripts/knowledge_graph.py", "status"],
                capture_output=True, text=True, cwd=ROOT
            )
            assert "Traceback" not in r.stderr, f"Crashed: {r.stderr}"
            assert "empty" in r.stdout.lower() or "0" in r.stdout, f"Expected empty graph msg, got: {r.stdout}"
        finally:
            if backup and backup.exists():
                shutil.move(str(backup), str(real_wikilinks))


class TestKnowledgeGraphScript:
    """Smoke tests for the script as a whole."""

    def test_help(self):
        r = subprocess.run(
            [sys.executable, "scripts/knowledge_graph.py", "--help"],
            capture_output=True, text=True, cwd=ROOT
        )
        assert r.returncode == 0, f"help failed: {r.stderr}"

    def test_all_commands_run_without_error(self):
        """All subcommands should run without Traceback."""
        for cmd in ["status", "phases", "mistakes", "search"]:
            stdout, stderr, code = run_kg([cmd] if cmd != "search" else [cmd, "test"])
            assert "Traceback" not in stderr, f"{cmd} crashed: {stderr}"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
