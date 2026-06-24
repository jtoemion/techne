"""Tests for the techne Hermes plugin (pre_tool_call enforcement hook).

Run: python3 -m pytest tests/test_plugin_techne.py -v

These tests import the plugin module and test the enforcement logic
directly without requiring a running Hermes session.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Load the plugin module directly from its file path
_PLUGIN_PATH = Path.home() / ".hermes" / "plugins" / "techne" / "__init__.py"
_spec = importlib.util.spec_from_file_location("techne_plugin", str(_PLUGIN_PATH))
plugin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plugin)


# ── Helpers ────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_ctx(monkeypatch):
    """Create a mock Hermes plugin context."""
    ctx = MagicMock()
    # Register hooks by tracking what @ctx.on returns
    hooks = {}
    def on_side_effect(hook_name):
        def decorator(fn):
            hooks[hook_name] = fn
            return fn
        return decorator
    ctx.on.side_effect = on_side_effect

    commands = {}
    def register_side_effect(name, handler, description=""):
        commands[name] = handler
    ctx.register_command.side_effect = register_side_effect

    plugin.register(ctx)
    ctx._hooks = hooks
    ctx._commands = commands

    # Isolate from the real tasks.db — returning None simulates no DB found.
    # Tests that need an active task mock _has_active_task or the DB directly.
    monkeypatch.setattr(plugin, "_find_tasks_db", lambda: None)
    return ctx


@pytest.fixture
def active_plugin(mock_ctx):
    """Plugin with pipeline mode activated (as if /techne was called)."""
    cmd = mock_ctx._commands.get("techne")
    assert cmd is not None, "/techne command not registered"
    return mock_ctx


# ── _is_allowed_path tests ────────────────────────────────────────────────

class TestAllowedPath:
    """Paths that should bypass enforcement."""

    def test_tmp_path_allowed(self):
        assert plugin._is_allowed_path("/tmp/test.txt")

    def test_techne_dir_allowed(self):
        assert plugin._is_allowed_path(".techne/context/project_digest.md")
        assert plugin._is_allowed_path("project/.techne/memory/tasks.db")

    def test_hermes_dir_allowed(self):
        home = str(Path.home())
        assert plugin._is_allowed_path(f"{home}/.hermes/logs/gateway.log")

    def test_dev_null_allowed(self):
        assert plugin._is_allowed_path("/dev/null")

    def test_project_source_not_allowed(self):
        assert not plugin._is_allowed_path("src/main.py")
        assert not plugin._is_allowed_path("/home/user/project/app.ts")

    def test_empty_path_not_allowed(self):
        assert not plugin._is_allowed_path("")


# ── _find_tasks_db tests ──────────────────────────────────────────────────

class TestFindTasksDb:

    def test_no_db_returns_none(self, monkeypatch):
        monkeypatch.chdir("/tmp")
        result = plugin._find_tasks_db()
        # May find the techne repo fallback, but if not, should be None
        assert result is None or result.exists()

    def test_finds_db_in_temp_dir(self, tmp_path):
        """Walk-up should find .techne/memory/tasks.db in a parent."""
        db_dir = tmp_path / ".techne" / "memory"
        db_dir.mkdir(parents=True)
        db_file = db_dir / "tasks.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE tasks (id TEXT)")
        conn.close()

        # Change to a subdirectory and walk up
        subdir = tmp_path / "src" / "deep"
        subdir.mkdir(parents=True)
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.chdir(str(subdir))
        try:
            found = plugin._find_tasks_db()
            assert found is not None
            assert str(found) == str(db_file)
        finally:
            monkeypatch.undo()


# ── _is_write_file tests ──────────────────────────────────────────────────

class TestIsWriteFile:

    def test_write_file_is_destructive(self):
        is_destructive, reason = plugin._is_write_file("write_file", {"path": "src/main.py"})
        assert is_destructive
        assert reason

    def test_write_file_to_techne_allowed(self):
        is_destructive, reason = plugin._is_write_file("write_file", {"path": ".techne/context/project.md"})
        assert not is_destructive

    def test_write_file_to_tmp_allowed(self):
        is_destructive, reason = plugin._is_write_file("write_file", {"path": "/tmp/scratch.txt"})
        assert not is_destructive

    def test_patch_is_destructive(self):
        is_destructive, reason = plugin._is_write_file("patch", {"path": "src/main.py", "old_string": "a", "new_string": "b"})
        assert is_destructive

    def test_patch_to_techne_allowed(self):
        is_destructive, reason = plugin._is_write_file("patch", {"path": ".techne/context/hash.txt"})
        assert not is_destructive

    def test_read_file_not_destructive(self):
        is_destructive, reason = plugin._is_write_file("read_file", {"path": "src/main.py"})
        assert not is_destructive

    def test_terminal_ls_not_destructive(self):
        is_destructive, reason = plugin._is_write_file("terminal", {"command": "ls -la"})
        assert not is_destructive

    def test_terminal_git_commit_destructive(self):
        is_destructive, reason = plugin._is_write_file("terminal", {"command": "git commit -m 'fix'"})
        assert is_destructive
        assert "git commit" in reason

    def test_terminal_git_push_destructive(self):
        is_destructive, reason = plugin._is_write_file("terminal", {"command": "git push origin master"})
        assert is_destructive

    def test_terminal_rm_rf_destructive(self):
        is_destructive, reason = plugin._is_write_file("terminal", {"command": "rm -rf node_modules"})
        assert is_destructive

    def test_terminal_mv_destructive(self):
        is_destructive, reason = plugin._is_write_file("terminal", {"command": "mv file.txt new.txt"})
        assert is_destructive

    def test_terminal_mv_not_false_positive(self):
        """'mv' as substring should not trigger (e.g., 'mview', 'improve')."""
        is_destructive, reason = plugin._is_write_file("terminal", {"command": "improve"})
        assert not is_destructive, f"False positive on 'impr**ove**'"

    def test_terminal_npm_build_not_destructive(self):
        is_destructive, reason = plugin._is_write_file("terminal", {"command": "npm run build"})
        assert not is_destructive

    def test_terminal_cat_not_destructive(self):
        is_destructive, reason = plugin._is_write_file("terminal", {"command": "cat file.txt"})
        assert not is_destructive

    def test_execute_code_with_write_file_detected(self):
        is_destructive, reason = plugin._is_write_file("execute_code", {
            "code": "from hermes_tools import write_file\nwrite_file('test.txt', 'content')"
        })
        assert is_destructive

    def test_execute_code_without_write_file_ignored(self):
        is_destructive, reason = plugin._is_write_file("execute_code", {
            "code": "print('hello')"
        })
        assert not is_destructive

    def test_empty_tool_input_not_destructive(self):
        is_destructive, reason = plugin._is_write_file("terminal", {})
        assert not is_destructive


# ── pre_tool_call hook integration tests ──────────────────────────────────

class TestPreToolCallHook:

    def test_hook_allows_when_inactive(self, mock_ctx):
        """With pipeline inactive, host-direct-write still blocks source files."""
        hook = mock_ctx._hooks.get("pre_tool_call")
        assert hook is not None

        # Host-direct-write blocks source files even when inactive
        result = hook(tool_name="write_file", tool_input={"path": "src/main.py"})
        assert result is not None
        assert result["action"] == "block"
        assert "Host agent" in result["message"]

        # Non-source paths still pass
        result2 = hook(tool_name="write_file", tool_input={"path": "/tmp/test.txt"})
        assert result2 is None, "Non-source writes should pass when inactive"

    def test_hook_allows_read_file_when_active_no_task(self, active_plugin):
        """Read-only tools always pass even when pipeline is active."""
        hook = active_plugin._hooks["pre_tool_call"]
        cmd = active_plugin._commands["techne"]

        # Activate
        cmd()

        result = hook(tool_name="read_file", tool_input={"path": "src/main.py"})
        assert result is None, "read_file should pass even without task"

    def test_hook_blocks_write_when_no_task(self, active_plugin):
        """write_file is blocked when pipeline is active and no task exists."""
        hook = active_plugin._hooks["pre_tool_call"]
        cmd = active_plugin._commands["techne"]

        cmd()  # activate
        result = hook(tool_name="write_file", tool_input={"path": "src/main.py"})
        assert result is not None
        assert result["action"] == "block"
        assert "WRITE BLOCKED" in result["message"] and ("Host agent" in result["message"] or "No active pipeline" in result["message"])

    def test_hook_allows_write_to_techne(self, active_plugin):
        """Writes to .techne/ paths bypass enforcement."""
        hook = active_plugin._hooks["pre_tool_call"]
        cmd = active_plugin._commands["techne"]
        cmd()

        # RECALL phase artifact should be allowed
        result = hook(tool_name="write_file", tool_input={"path": ".techne/loop/recall.txt"})
        assert result is None, ".techne/ write should be allowed"

    def test_hook_allows_write_with_bypass(self, active_plugin):
        """/techne bypass grants temporary write access for non-source paths."""
        hook = active_plugin._hooks["pre_tool_call"]
        cmd = active_plugin._commands["techne"]

        cmd()  # activate
        cmd("bypass")  # grant 3 bypasses

        # Host-direct-write blocks source files regardless of bypass
        result = hook(tool_name="write_file", tool_input={"path": "src/main.py"})
        assert result is not None
        assert result["action"] == "block"
        assert "Host agent" in result["message"]

        # Bypass should allow writes to non-source/non-blocked paths
        result2 = hook(tool_name="write_file", tool_input={"path": "/tmp/test.txt"})
        assert result2 is None, "Bypass should allow temp writes"

    def test_techne_off_disables_enforcement(self, active_plugin):
        """/techne off disables pipeline enforcement but host-direct-write still blocks."""
        hook = active_plugin._hooks["pre_tool_call"]
        cmd = active_plugin._commands["techne"]

        cmd()  # activate
        cmd("off")  # deactivate

        # Host-direct-write always blocks host-level source writes
        result = hook(tool_name="write_file", tool_input={"path": "src/main.py"})
        assert result is not None
        assert result["action"] == "block"
        assert "Host agent" in result["message"]

        # Non-source writes should pass after /techne off
        result2 = hook(tool_name="write_file", tool_input={"path": "/tmp/test.txt"})
        assert result2 is None, "Non-source writes should pass after off"

    def test_block_log_on_hook_block(self, active_plugin):
        """Blocked tools are recorded in the block log."""
        hook = active_plugin._hooks["pre_tool_call"]
        cmd = active_plugin._commands["techne"]

        cmd()  # activate
        # Block a write
        hook(tool_name="write_file", tool_input={"path": "src/main.py"})
        hook(tool_name="patch", tool_input={"path": "src/lib.ts"})

        status_output = cmd("status")
        assert "Total blocks this session: 2" in status_output
        assert "write_file" in status_output
        assert "patch" in status_output

    def test_bypass_consumes_count(self, active_plugin):
        """Each bypass write decrements the bypass counter."""
        hook = active_plugin._hooks["pre_tool_call"]
        cmd = active_plugin._commands["techne"]

        cmd()
        cmd("bypass")  # 3 bypasses

        # Use 3 bypasses
        hook(tool_name="write_file", tool_input={"path": "a.ts"})
        hook(tool_name="write_file", tool_input={"path": "b.ts"})
        hook(tool_name="write_file", tool_input={"path": "c.ts"})

        # 4th should be blocked
        result = hook(tool_name="write_file", tool_input={"path": "d.ts"})
        assert result is not None
        assert result["action"] == "block"

    def test_terminal_block_adds_to_log(self, active_plugin):
        """Blocked terminal commands appear in the block log."""
        hook = active_plugin._hooks["pre_tool_call"]
        cmd = active_plugin._commands["techne"]

        cmd()  # activate
        hook(tool_name="terminal", tool_input={"command": "git push origin master"})

        status_output = cmd("status")
        assert "git push" in status_output or "Total blocks" in status_output


# ── _find_tasks_db walk-up test ───────────────────────────────────────────

class TestTasksDbWalkUp:

    def test_walk_up_skips_non_techne(self, tmp_path, monkeypatch):
        """Walk-up should not find tasks.db in a plain temp dir."""
        subdir = tmp_path / "work" / "src"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(str(subdir))
        result = plugin._find_tasks_db()
        # Should be None (no .techne/memory/tasks.db exists in the tree)
        assert result is None or result == plugin.TECHNE_REPO / ".techne" / "memory" / "tasks.db"
