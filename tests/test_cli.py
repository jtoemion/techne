"""test_cli.py — Tests for the techne CLI."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(*args, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["techne", *args],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_help_exits_zero() -> None:
    r = _run("--help")
    assert r.returncode == 0
    assert "init" in r.stdout
    assert "next" in r.stdout
    assert "status" in r.stdout
    assert "doctor" in r.stdout


def test_init_creates_state_json() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write(tmp / ".techne" / "config.yaml", "project_name: test\n")
        r = _run("init", "my-task-1", cwd=tmp)
        assert r.returncode == 0, r.stderr
        state_file = tmp / ".techne" / "loop" / "state.json"
        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert state["task_id"] == "my-task-1"
        assert state["phase"] == "RECALL"


def test_init_fails_if_state_exists_without_force() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write(tmp / ".techne" / "config.yaml", "project_name: test\n")
        _run("init", "task-1", cwd=tmp)
        r = _run("init", "task-2", cwd=tmp)
        assert r.returncode != 0
        assert "force" in r.stdout.lower() or "force" in r.stderr.lower()


def test_init_force_overwrites() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write(tmp / ".techne" / "config.yaml", "project_name: test\n")
        _run("init", "task-1", cwd=tmp)
        r = _run("init", "--force", "task-2", cwd=tmp)
        assert r.returncode == 0
        state = json.loads((tmp / ".techne" / "loop" / "state.json").read_text())
        assert state["task_id"] == "task-2"


def test_next_blocked_when_no_artifact() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write(tmp / ".techne" / "config.yaml", "project_name: test\n")
        _run("init", "task-1", cwd=tmp)
        r = _run("next", cwd=tmp)
        assert r.returncode != 0  # No artifact written — gates should fail


def test_status_no_pipeline() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # Create an empty .techne/ so loop_dir() doesn't walk up to a parent
        (tmp / ".techne").mkdir()
        r = _run("status", cwd=tmp)
        assert r.returncode == 0
        assert "No active pipeline" in r.stdout


def test_status_shows_phase() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write(tmp / ".techne" / "config.yaml", "project_name: test\n")
        _run("init", "task-1", cwd=tmp)
        r = _run("status", cwd=tmp)
        assert r.returncode == 0
        assert "RECALL" in r.stdout
        assert "task-1" in r.stdout


def test_doctor_exits_zero() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / ".techne").mkdir()  # shadow parent .techne for isolation
        r = _run("doctor", cwd=tmp)
        assert r.returncode == 0


def test_doctor_detects_no_techne_dir() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        r = _run("doctor", cwd=Path(tmp))
        assert r.returncode == 0
        assert "✗" in r.stdout or "not found" in r.stdout.lower()


def test_handoff_no_pipeline_exits_zero() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / ".techne").mkdir()  # shadow parent .techne
        r = _run("handoff", cwd=tmp)
        assert r.returncode == 0
        assert "nothing to hand off" in r.stdout.lower() or "no active" in r.stdout.lower()


def test_handoff_writes_markdown_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write(tmp / ".techne" / "config.yaml", "project_name: test\n")
        _run("init", "handoff-task-1", cwd=tmp)
        r = _run("handoff", cwd=tmp)
        assert r.returncode == 0
        handoff_path = tmp / ".techne" / "loop" / "handoff.md"
        assert handoff_path.exists(), "handoff.md should be written"
        content = handoff_path.read_text()
        assert "handoff-task-1" in content
        assert "RECALL" in content
        # Should include next-action instructions
        assert "recall.txt" in content or "techne next" in content


def test_help_includes_handoff() -> None:
    r = _run("--help")
    assert r.returncode == 0
    assert "handoff" in r.stdout
