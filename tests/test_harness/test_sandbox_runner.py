"""Tests for harness/sandbox_runner.py — W6 throwaway-worktree sandbox."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "harness"))

from sandbox_runner import (
    SandboxHaltError,
    SandboxResult,
    git_diff_head,
    run_in_worktree,
    sandbox_test_runner,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _is_git_repo(path: Path) -> bool:
    r = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=path, capture_output=True)
    return r.returncode == 0


def _git_init_repo(d: Path) -> None:
    """Create a minimal git repo with one committed file."""
    subprocess.run(["git", "init", "-b", "main"], cwd=d, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=d, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=d, capture_output=True)
    (d / "hello.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=d, capture_output=True)


def _make_patch(old: str, new: str, filename: str = "hello.py") -> str:
    """Return a unified diff patching `old` to `new` for `filename`."""
    with tempfile.TemporaryDirectory() as tmp:
        old_f = Path(tmp) / "old"
        new_f = Path(tmp) / "new"
        old_f.write_text(old, encoding="utf-8")
        new_f.write_text(new, encoding="utf-8")
        proc = subprocess.run(
            ["git", "diff", "--no-index", f"a/{filename}", f"b/{filename}"],
            input=f"--- a/{filename}\n+++ b/{filename}\n",
            cwd=tmp,
            capture_output=True,
            text=True,
        )
        # git diff --no-index exits 1 on differences — that's expected
        r = subprocess.run(
            ["diff", "-u", str(old_f), str(new_f)],
            capture_output=True, text=True,
        )
    # Rewrite diff header to match git format
    lines = r.stdout.splitlines(keepends=True)
    if len(lines) >= 2:
        lines[0] = f"--- a/{filename}\n"
        lines[1] = f"+++ b/{filename}\n"
    return "".join(lines)


# ── SandboxResult dataclass ───────────────────────────────────────────────────

def test_sandbox_result_fields() -> None:
    r = SandboxResult(passed=True, patch_applied=False, stdout="ok", exit_code=0)
    assert r.passed
    assert not r.patch_applied
    assert r.stdout == "ok"
    assert r.exit_code == 0
    assert r.worktree_path is None


# ── run_in_worktree: no-patch baseline ───────────────────────────────────────

def test_run_in_worktree_no_patch_passes_trivial_test() -> None:
    """An empty patch with a trivially passing test command should succeed."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _git_init_repo(d)
        result = run_in_worktree("", "python --version", cwd=d)
    assert result.passed
    assert result.exit_code == 0
    assert not result.patch_applied


def test_run_in_worktree_failing_test_returns_not_passed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _git_init_repo(d)
        # Use sys.exit via -c with double quotes (works on cmd.exe and bash)
        result = run_in_worktree("", 'python -c "import sys; sys.exit(1)"', cwd=d)
    assert not result.passed
    assert result.exit_code == 1


# ── run_in_worktree: patch application ───────────────────────────────────────

def test_run_in_worktree_applies_patch_and_sees_change() -> None:
    """Patch adds a new variable; test checks that hello.py was modified."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _git_init_repo(d)
        # Patch adds y = 2 to hello.py
        patch = _make_patch("x = 1\n", "x = 1\ny = 2\n")
        # Read the file and grep for the added line via python -m
        result = run_in_worktree(
            patch,
            'python -c "assert open(\'hello.py\').read().count(\'y = 2\') == 1"',
            cwd=d,
        )
    assert result.passed, f"Test failed: {result.stdout}"
    assert result.patch_applied


def test_run_in_worktree_patch_change_not_in_main_tree() -> None:
    """After sandbox run, the main working tree must NOT be modified."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _git_init_repo(d)
        patch = _make_patch("x = 1\n", "x = 1\ny = 99\n")
        run_in_worktree(patch, "python -c 'print(\"ok\")'", cwd=d)
        # Main tree's hello.py must still be the original
        content = (d / "hello.py").read_text(encoding="utf-8")
    assert "y = 99" not in content, "Sandbox leaked patch into main tree!"


# ── run_in_worktree: halt on bad patch ───────────────────────────────────────

def test_run_in_worktree_raises_halt_on_bad_patch() -> None:
    """A patch that doesn't apply must raise SandboxHaltError, never silently pass."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _git_init_repo(d)
        bad_patch = (
            "--- a/nonexistent.py\n"
            "+++ b/nonexistent.py\n"
            "@@ -1 +1 @@\n"
            "-old line\n"
            "+new line\n"
        )
        with pytest.raises(SandboxHaltError):
            run_in_worktree(bad_patch, "python -c 'print(\"ok\")'", cwd=d)


# ── sandbox_test_runner factory ───────────────────────────────────────────────

def test_sandbox_test_runner_returns_callable() -> None:
    fn = sandbox_test_runner("pytest -q", lambda: "")
    assert callable(fn)


def test_sandbox_test_runner_runs_in_worktree() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _git_init_repo(d)
        test_fn = sandbox_test_runner(
            "python --version",
            lambda: "",
            cwd=d,
        )
        output = test_fn()
    # python --version prints to stderr on some versions, stdout on others
    assert "Python" in output or output == ""  # any output means it ran


def test_sandbox_test_runner_propagates_halt_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _git_init_repo(d)
        bad_patch = "--- a/missing\n+++ b/missing\n@@ -1 +1 @@\n-x\n+y\n"
        test_fn = sandbox_test_runner(
            "python -c 'print(\"ok\")'",
            lambda: bad_patch,
            cwd=d,
        )
        with pytest.raises(SandboxHaltError):
            test_fn()


# ── git_diff_head ─────────────────────────────────────────────────────────────

def test_git_diff_head_returns_string() -> None:
    """git_diff_head should return a string (possibly empty) for the real repo."""
    diff = git_diff_head(cwd=REPO_ROOT)
    assert isinstance(diff, str)


def test_git_diff_head_clean_repo_is_empty_or_staged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _git_init_repo(d)
        diff = git_diff_head(cwd=d)
    assert isinstance(diff, str)
    # A freshly committed repo has no diff
    assert diff == ""
