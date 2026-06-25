"""Tests for scripts/hash_gate.py — diff context validation (Hashline gate)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Ensure scripts/ is importable
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from hash_gate import parse_diff_files, validate_diff_context


# ── parse_diff_files unit tests ───────────────────────────────────────────────

def test_parse_empty_returns_empty() -> None:
    assert parse_diff_files("") == []


def test_parse_single_file_single_hunk() -> None:
    diff = """\
--- a/foo.py
+++ b/foo.py
@@ -1,4 +1,5 @@
 def foo():
     x = 1
+    x += 1
     return x
"""
    files = parse_diff_files(diff)
    assert len(files) == 1
    fname, hunks = files[0]
    assert fname == "foo.py"
    assert len(hunks) == 1
    start, ctx = hunks[0]
    assert start == 1
    # context lines: "def foo():", "    x = 1", "    return x"
    assert "def foo():" in ctx
    assert "    x = 1" in ctx
    assert "    return x" in ctx
    # added line must NOT be in context
    assert "    x += 1" not in ctx


def test_parse_strips_b_prefix() -> None:
    diff = """\
--- /dev/null
+++ b/new_file.py
@@ -0,0 +1,2 @@
+line1
+line2
"""
    files = parse_diff_files(diff)
    assert files[0][0] == "new_file.py"


def test_parse_two_files() -> None:
    diff = """\
--- a/alpha.py
+++ b/alpha.py
@@ -1,2 +1,3 @@
 alpha line
+new line
 alpha end
--- a/beta.py
+++ b/beta.py
@@ -5,3 +5,4 @@
 beta line
+another new
 beta end
"""
    files = parse_diff_files(diff)
    assert len(files) == 2
    assert files[0][0] == "alpha.py"
    assert files[1][0] == "beta.py"


# ── validate_diff_context integration tests ───────────────────────────────────

def _write(root: Path, relpath: str, content: str) -> Path:
    p = root / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_clean_diff_passes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, "foo.py", "def foo():\n    x = 1\n    return x\n")
        diff = """\
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 def foo():
     x = 1
+    x += 1
     return x
"""
        passed, detail = validate_diff_context(diff, root)
        assert passed, detail
        assert "verified" in detail


def test_stale_context_fails() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # File on disk has been edited since the agent read it
        _write(root, "foo.py", "def foo():\n    x = 99\n    return x\n")
        diff = """\
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 def foo():
     x = 1
+    x += 1
     return x
"""
        passed, detail = validate_diff_context(diff, root)
        assert not passed, "stale context should fail"
        assert "foo.py" in detail
        assert "hunk@" in detail


def test_new_file_creation_passes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # File doesn't exist — new file creation
        diff = """\
--- /dev/null
+++ b/new_file.py
@@ -0,0 +1,3 @@
+def new():
+    pass
+
"""
        passed, detail = validate_diff_context(diff, root)
        assert passed, detail


def test_pure_addition_hunk_no_context_passes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, "foo.py", "def foo():\n    pass\n")
        # Hunk with no context lines — only additions
        diff = """\
--- a/foo.py
+++ b/foo.py
@@ -1,0 +1,1 @@
+    x = 1
"""
        passed, _ = validate_diff_context(diff, root)
        assert passed


def test_empty_diff_passes() -> None:
    passed, detail = validate_diff_context("", Path("/tmp"))
    assert passed
    assert "no hunks" in detail


def test_whitespace_corruption_fails() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, "foo.py", "def foo():\n    x = 1\n    return x\n")
        # Context line has tabs instead of spaces (whitespace mangled)
        diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1,3 +1,4 @@\n def foo():\n\t    x = 1\n+    x += 1\n     return x\n"
        passed, detail = validate_diff_context(diff, root)
        # Tab-indented context won't match space-indented file
        assert not passed
        assert "foo.py" in detail


def test_multi_hunk_one_stale_fails() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, "foo.py", "def foo():\n    x = 1\n    return x\n\ndef bar():\n    y = 2\n    return y\n")
        diff = """\
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 def foo():
     x = 1
+    x += 1
     return x
@@ -5,3 +5,4 @@
 def bar():
     y = STALE
+    y += 1
     return y
"""
        passed, detail = validate_diff_context(diff, root)
        assert not passed
        assert "hunk@5" in detail


def test_context_with_position_drift_passes() -> None:
    """Context lines are correct but hunk header line number is slightly off (±5 lines)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # File has 5 leading blank lines the agent didn't know about
        content = "\n\n\n\n\ndef foo():\n    x = 1\n    return x\n"
        _write(root, "foo.py", content)
        # Hunk claims to start at line 1 but actual content is at line 6
        diff = """\
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 def foo():
     x = 1
+    x += 1
     return x
"""
        # Full-file fallback should find the context even with line drift
        passed, detail = validate_diff_context(diff, root)
        assert passed, f"fallback full-file scan should succeed: {detail}"
