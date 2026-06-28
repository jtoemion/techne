"""Tests for scripts/context_gap.py — W2 context-gap detector."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import context_gap


def _make_context(d: Path, content: str) -> Path:
    ctx = d / ".techne" / "context"
    ctx.mkdir(parents=True, exist_ok=True)
    (ctx / "project.md").write_text(content, encoding="utf-8")
    return ctx


def test_covered_file_detected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        # Use filename reference "auth.py" so the check finds it
        _make_context(d, "# project\n\nSee auth.py for authentication logic.")
        report = context_gap.check_files(["auth.py"], context_dir=d / ".techne" / "context")
        assert report["covered_count"] >= 1
        assert "auth.py" in report["covered"]


def test_gap_file_detected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _make_context(d, "# nothing about billing here")
        report = context_gap.check_files(["billing.py"], context_dir=d / ".techne" / "context")
        assert report["gap_count"] >= 1
        assert "billing.py" in report["gaps"]


def test_non_python_files_ignored() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        ctx = _make_context(d, "# project docs")
        report = context_gap.check_files(
            ["README.md", "package.json", "src/app.ts"],
            context_dir=ctx,
        )
        assert report["gap_count"] == 0
        assert report["covered_count"] == 0  # no Python files, nothing to check


def test_empty_context_all_gaps() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        empty_ctx = d / ".techne" / "context"
        empty_ctx.mkdir(parents=True, exist_ok=True)
        report = context_gap.check_files(["foo.py", "bar.py"], context_dir=empty_ctx)
        assert report["gap_count"] == 2
        assert report["covered_count"] == 0


def test_missing_context_dir_all_gaps() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        nonexistent = d / ".techne" / "context"
        report = context_gap.check_files(["foo.py"], context_dir=nonexistent)
        assert report["gap_count"] == 1


def test_recommendation_populated_when_gaps() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _make_context(d, "# irrelevant content")
        report = context_gap.check_files(["missing.py"], context_dir=d / ".techne" / "context")
        assert report["gap_count"] == 1
        assert len(report["recommendation"]) > 0


def test_no_recommendation_when_no_gaps() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        # Reference billing.py by filename so the detector finds it
        _make_context(d, "# billing.py handles billing logic")
        report = context_gap.check_files(["billing.py"], context_dir=d / ".techne" / "context")
        assert report["gap_count"] == 0
        assert report["recommendation"] == ""
