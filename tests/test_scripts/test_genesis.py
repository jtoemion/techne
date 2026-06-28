"""Tests for scripts/genesis.py — W2 GENESIS cold-start bootstrap."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import genesis


def _make_repo(d: Path) -> None:
    """Create a minimal Python repo structure for testing."""
    (d / "src").mkdir()
    (d / "src" / "app.py").write_text(
        "def hello():\n    pass\n\nclass World:\n    pass\n", encoding="utf-8"
    )
    (d / "src" / "utils.py").write_text(
        "def helper(x):\n    return x\n", encoding="utf-8"
    )
    (d / "tests").mkdir()
    (d / "tests" / "test_app.py").write_text(
        "def test_hello():\n    pass\n", encoding="utf-8"
    )
    (d / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")


def test_bootstrap_creates_three_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _make_repo(d)
        old_root = genesis._ROOT
        old_ctx = genesis._CONTEXT_DIR
        old_contract = genesis._CONTRACT
        genesis._ROOT = d
        genesis._CONTEXT_DIR = d / ".techne" / "context"
        genesis._CONTRACT = d / ".techne" / "genesis.json"
        try:
            contract = genesis.run_bootstrap(d)
        finally:
            genesis._ROOT = old_root
            genesis._CONTEXT_DIR = old_ctx
            genesis._CONTRACT = old_contract

        assert (d / ".techne" / "context" / "genesis-api-surface.md").exists()
        assert (d / ".techne" / "context" / "genesis-conventions.md").exists()
        assert (d / ".techne" / "context" / "genesis-structure.md").exists()
        assert (d / ".techne" / "genesis.json").exists()
        assert contract["modules_scanned"] >= 2  # src/app.py + src/utils.py


def test_bootstrap_excludes_tests() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _make_repo(d)
        old_root, old_ctx, old_contract = genesis._ROOT, genesis._CONTEXT_DIR, genesis._CONTRACT
        genesis._ROOT = d
        genesis._CONTEXT_DIR = d / ".techne" / "context"
        genesis._CONTRACT = d / ".techne" / "genesis.json"
        try:
            modules = genesis._find_python_modules(d)
        finally:
            genesis._ROOT = old_root
            genesis._CONTEXT_DIR = old_ctx
            genesis._CONTRACT = old_contract

        names = [m.name for m in modules]
        assert "test_app.py" not in names
        assert "app.py" in names


def test_bootstrap_idempotent_without_force() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _make_repo(d)
        old_root, old_ctx, old_contract = genesis._ROOT, genesis._CONTEXT_DIR, genesis._CONTRACT
        genesis._ROOT = d
        genesis._CONTEXT_DIR = d / ".techne" / "context"
        genesis._CONTRACT = d / ".techne" / "genesis.json"
        try:
            genesis.run_bootstrap(d)
            # Modify a file
            api_file = d / ".techne" / "context" / "genesis-api-surface.md"
            original = api_file.read_text(encoding="utf-8")
            api_file.write_text("CUSTOM CONTENT\n", encoding="utf-8")
            # Second run without force should NOT overwrite
            genesis.run_bootstrap(d, force=False)
        finally:
            genesis._ROOT = old_root
            genesis._CONTEXT_DIR = old_ctx
            genesis._CONTRACT = old_contract

        assert api_file.read_text(encoding="utf-8") == "CUSTOM CONTENT\n"


def test_verify_detects_tamper() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _make_repo(d)
        old_root, old_ctx, old_contract = genesis._ROOT, genesis._CONTEXT_DIR, genesis._CONTRACT
        genesis._ROOT = d
        genesis._CONTEXT_DIR = d / ".techne" / "context"
        genesis._CONTRACT = d / ".techne" / "genesis.json"
        try:
            genesis.run_bootstrap(d)
            # Tamper with a generated file
            api_file = d / ".techne" / "context" / "genesis-api-surface.md"
            text = api_file.read_text(encoding="utf-8")
            api_file.write_text(text + "\nTAMPERED\n", encoding="utf-8")
            ok, msg = genesis.verify_contract(d)
        finally:
            genesis._ROOT = old_root
            genesis._CONTEXT_DIR = old_ctx
            genesis._CONTRACT = old_contract

        assert not ok
        assert "SHA mismatch" in msg or "mismatch" in msg.lower()


def test_verify_passes_clean_contract() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _make_repo(d)
        old_root, old_ctx, old_contract = genesis._ROOT, genesis._CONTEXT_DIR, genesis._CONTRACT
        genesis._ROOT = d
        genesis._CONTEXT_DIR = d / ".techne" / "context"
        genesis._CONTRACT = d / ".techne" / "genesis.json"
        try:
            genesis.run_bootstrap(d)
            ok, msg = genesis.verify_contract(d)
        finally:
            genesis._ROOT = old_root
            genesis._CONTEXT_DIR = old_ctx
            genesis._CONTRACT = old_contract

        assert ok
        assert "verified" in msg.lower()


def test_mine_api_surface_extracts_public_symbols() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "mod.py").write_text(
            "def public_fn():\n    pass\n\ndef _private():\n    pass\n"
            "class PublicClass:\n    pass\n",
            encoding="utf-8",
        )
        surface = genesis._mine_api_surface([d / "mod.py"])
        symbols = list(surface.values())[0]
        assert "public_fn" in symbols
        assert "PublicClass" in symbols
        assert "_private" not in symbols
