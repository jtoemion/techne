"""Smoke tests for scripts/diff_gate_checker.py"""
import subprocess, sys

def test_help():
    r = subprocess.run(
        [sys.executable, "scripts/diff_gate_checker.py", "--help"],
        capture_output=True, text=True, cwd="."
    )
    assert r.returncode == 0, f"help failed: {r.stderr}"
    assert "diff" in r.stdout.lower()

def test_empty_input_exits_1():
    """Empty stdin should exit with code 1."""
    r = subprocess.run(
        [sys.executable, "scripts/diff_gate_checker.py"],
        capture_output=True, text=True, cwd=".", input=""
    )
    assert r.returncode == 1, f"expected exit 1, got {r.returncode}"
    assert "FAIL" in r.stdout

def test_valid_implement_diff():
    """A diff with proper markers should pass."""
    diff = """--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 def foo():
     return 1
+    return 2
"""
    r = subprocess.run(
        [sys.executable, "scripts/diff_gate_checker.py", "--phase", "implement"],
        input=diff, capture_output=True, text=True, cwd="."
    )
    assert r.returncode == 0, f"valid diff should pass: {r.stdout}\n{r.stderr}"

def test_invalid_implement_diff():
    """A prose-only diff should fail the gate."""
    prose = "This is my implementation.\nIt does something.\n"
    r = subprocess.run(
        [sys.executable, "scripts/diff_gate_checker.py", "--phase", "implement"],
        input=prose, capture_output=True, text=True, cwd="."
    )
    assert r.returncode == 1, f"prose-only diff should fail: {r.stdout}"
    assert "MISSING" in r.stdout

def test_context_guard_punch_list():
    """A diff with punch list should pass context-guard check."""
    text = """## CONCLUDE PUNCH LIST\n- [ ] item1\ndocs: README.md\nhoncho: proof-123
"""
    r = subprocess.run(
        [sys.executable, "scripts/diff_gate_checker.py", "--phase", "context-guard"],
        input=text, capture_output=True, text=True, cwd="."
    )
    assert r.returncode == 0, f"punch list diff should pass: {r.stdout}\n{r.stderr}"

def test_conclude_phase():
    """Conclude phase needs SHA, HONCHO, DOCS."""
    text = """honcho: honcho://conclusion/abc123
docs: README.md
sha:""" + "a" * 40 + """
"""
    r = subprocess.run(
        [sys.executable, "scripts/diff_gate_checker.py", "--phase", "conclude"],
        input=text, capture_output=True, text=True, cwd="."
    )
    assert r.returncode == 0, f"valid conclude diff should pass: {r.stdout}\n{r.stderr}"
