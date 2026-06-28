"""Tests for scripts/mutation_gate.py — the model-independent test-strength gate."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import mutation_gate  # noqa: E402


_SRC = "def is_adult(age):\n    return age >= 18\n"
_WEAK = "from mod import is_adult\n\ndef test_weak():\n    assert is_adult(40)\n"
_STRONG = (
    "from mod import is_adult\n\n"
    "def test_boundary():\n"
    "    assert is_adult(18)\n"
    "    assert not is_adult(17)\n"
    "    assert not is_adult(0)\n"
)


def _make(d: Path, test_body: str) -> Path:
    (d / "mod.py").write_text(_SRC, encoding="utf-8")
    (d / "test_x.py").write_text(test_body, encoding="utf-8")
    return d / "mod.py"


def _cmd(d: Path) -> str:
    return f'"{sys.executable}" -m pytest -q "{d / "test_x.py"}"'


def test_weak_suite_is_blocked() -> None:
    """A test that doesn't constrain the boundary must leave a surviving mutant."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        src = _make(d, _WEAK)
        res = mutation_gate.run_gate(src, _cmd(d), timeout=60)
        assert res["passed"] is False
        assert res["survived"] >= 1


def test_strong_suite_passes() -> None:
    """A boundary-checking test must kill every mutation."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        src = _make(d, _STRONG)
        res = mutation_gate.run_gate(src, _cmd(d), timeout=60)
        assert res["passed"] is True
        assert res["survived"] == 0
        assert res["killed"] >= 1


def test_source_is_restored_after_run() -> None:
    """The original source must be byte-identical after mutation (try/finally)."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        src = _make(d, _STRONG)
        before = src.read_text(encoding="utf-8")
        mutation_gate.run_gate(src, _cmd(d), timeout=60)
        assert src.read_text(encoding="utf-8") == before


def test_no_mutable_sites_passes() -> None:
    """A file with nothing to mutate is a soft pass, not a crash."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        src = d / "plain.py"
        src.write_text("x = 'hello'\n", encoding="utf-8")
        res = mutation_gate.run_gate(src, "true", timeout=10)
        assert res["passed"] is True
        assert res["killed"] == 0 and res["survived"] == 0


def test_changed_lines_scope_limits_mutation() -> None:
    """Scoping to a line with no mutable site yields zero mutants (soft pass)."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        src = _make(d, _STRONG)
        res = mutation_gate.run_gate(src, _cmd(d), changed_lines={1}, timeout=60)
        # line 1 is the `def` line — no mutable operator there
        assert res["passed"] is True
        assert res["killed"] == 0 and res["survived"] == 0
