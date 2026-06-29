"""Tests for scripts/import_published_evals.py — W9 published eval corpus seed."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from import_published_evals import import_published_evals, load_corpus, load_seed


def _write_seed(d: Path, cases: list[dict]) -> Path:
    f = d / "seed.jsonl"
    f.write_text(
        "\n".join(json.dumps(c) for c in cases) + "\n", encoding="utf-8"
    )
    return f


def _write_corpus(d: Path, cases: list[dict]) -> Path:
    f = d / "corpus.jsonl"
    f.write_text(
        "\n".join(json.dumps(c) for c in cases) + "\n", encoding="utf-8"
    )
    return f


# ── load_seed ─────────────────────────────────────────────────────────────────

def test_load_seed_returns_empty_for_missing() -> None:
    cases = load_seed(Path("/tmp/nonexistent_seed_12345.jsonl"))
    assert cases == []


def test_load_seed_reads_jsonl() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        seed = _write_seed(d, [
            {"id": "a", "source": "published", "description": "test A"},
            {"id": "b", "source": "published", "description": "test B"},
        ])
        cases = load_seed(seed)
    assert len(cases) == 2
    assert cases[0]["id"] == "a"


# ── import_published_evals ────────────────────────────────────────────────────

def test_import_adds_all_seed_to_empty_corpus() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        seed = _write_seed(d, [
            {"id": "x1", "source": "published", "description": "no API keys"},
            {"id": "x2", "source": "published", "description": "tests required"},
        ])
        corpus = d / "corpus.jsonl"
        stats = import_published_evals(seed, corpus)
        assert stats["added"] == 2
        assert stats["skipped"] == 0
        corpus_cases = load_corpus(corpus)
        assert len(corpus_cases) == 2


def test_import_skips_duplicates_by_source_description() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        seed = _write_seed(d, [
            {"id": "x1", "source": "published", "description": "no API keys"},
        ])
        # Pre-populate corpus with same case
        corpus = _write_corpus(d, [
            {"id": "x1", "source": "published", "description": "no API keys"},
        ])
        stats = import_published_evals(seed, corpus)
    assert stats["added"] == 0
    assert stats["skipped"] == 1


def test_import_dry_run_does_not_write() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        seed = _write_seed(d, [{"id": "y1", "source": "published", "description": "dry test"}])
        corpus = d / "corpus_dry.jsonl"
        stats = import_published_evals(seed, corpus, dry_run=True)
    assert stats["added"] == 1
    assert stats["dry_run"] is True
    assert not corpus.exists()   # nothing written in dry-run


def test_import_empty_seed_returns_zero_added() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        empty_seed = d / "empty.jsonl"
        empty_seed.write_text("", encoding="utf-8")
        corpus = d / "corpus.jsonl"
        stats = import_published_evals(empty_seed, corpus)
    assert stats["added"] == 0


def test_import_appends_to_existing_corpus() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        seed = _write_seed(d, [{"id": "n1", "source": "published", "description": "new case"}])
        corpus = _write_corpus(d, [{"id": "e1", "source": "runtime", "description": "existing"}])
        stats = import_published_evals(seed, corpus)
        assert stats["added"] == 1
        final = load_corpus(corpus)
        assert len(final) == 2


# ── seed file integrity ───────────────────────────────────────────────────────

def test_published_seed_file_is_valid_jsonl() -> None:
    """The committed seed.jsonl must be valid JSONL with required fields."""
    seed_path = REPO_ROOT / "evals" / "published" / "seed.jsonl"
    assert seed_path.exists(), "evals/published/seed.jsonl missing from repo"
    cases = load_seed(seed_path)
    assert len(cases) >= 5, f"seed should have at least 5 cases, got {len(cases)}"
    for case in cases:
        assert "id" in case, f"case missing 'id': {case}"
        assert "source" in case
        assert "description" in case
        assert isinstance(case.get("forbidden_patterns", []), list)
        assert isinstance(case.get("required_patterns", []), list)
