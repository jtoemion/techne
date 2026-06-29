#!/usr/bin/env python3
"""import_published_evals.py — seed the runtime eval corpus from evals/published/seed.jsonl.

Published evals are curated, committed cases that define the minimum gate invariants
for any Techne skill. Running this script merges them into .techne/eval/corpus.jsonl
(the runtime corpus used by the Promotion Gate), deduplicating by source+description.

Usage:
    python scripts/import_published_evals.py
    python scripts/import_published_evals.py --seed-file evals/published/seed.jsonl
    python scripts/import_published_evals.py --dry-run

This is called once at setup and after each published eval update. The runtime corpus
in .techne/eval/ is gitignored (runtime state); the published seed in evals/ is
committed and version-controlled.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SEED_FILE = _ROOT / "evals" / "published" / "seed.jsonl"
_CORPUS_FILE = _ROOT / ".techne" / "eval" / "corpus.jsonl"


def load_seed(seed_file: Path) -> list[dict]:
    if not seed_file.exists():
        return []
    cases = []
    for line in seed_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return cases


def load_corpus(corpus_file: Path) -> list[dict]:
    if not corpus_file.exists():
        return []
    cases = []
    for line in corpus_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return cases


def import_published_evals(
    seed_file: Path = _SEED_FILE,
    corpus_file: Path = _CORPUS_FILE,
    *,
    dry_run: bool = False,
) -> dict:
    """Merge published evals into the runtime corpus. Returns import stats."""
    seed_cases = load_seed(seed_file)
    if not seed_cases:
        return {"added": 0, "skipped": 0, "total_seed": 0, "message": "seed file empty or missing"}

    corpus_cases = load_corpus(corpus_file)
    existing_keys = {c.get("source", "") + c.get("description", "") for c in corpus_cases}

    added = []
    skipped = 0
    for case in seed_cases:
        key = case.get("source", "") + case.get("description", "")
        if key in existing_keys:
            skipped += 1
            continue
        existing_keys.add(key)
        added.append(case)

    if not dry_run and added:
        corpus_file.parent.mkdir(parents=True, exist_ok=True)
        with open(corpus_file, "a", encoding="utf-8") as fh:
            for c in added:
                fh.write(json.dumps(c, separators=(",", ":")) + "\n")

    return {
        "added": len(added),
        "skipped": skipped,
        "total_seed": len(seed_cases),
        "corpus_size": len(corpus_cases) + len(added),
        "dry_run": dry_run,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import argparse
    p = argparse.ArgumentParser(description="Import published evals into runtime corpus")
    p.add_argument("--seed-file", default=str(_SEED_FILE), help="Path to seed.jsonl")
    p.add_argument("--corpus-file", default=str(_CORPUS_FILE), help="Path to corpus.jsonl")
    p.add_argument("--dry-run", action="store_true", help="Show what would be imported without writing")
    p.add_argument("--status", action="store_true", help="Show current corpus and seed sizes")
    args = p.parse_args()

    seed_file = Path(args.seed_file)
    corpus_file = Path(args.corpus_file)

    if args.status:
        seed = load_seed(seed_file)
        corpus = load_corpus(corpus_file)
        print(f"  seed    : {len(seed)} cases  ({seed_file})")
        print(f"  corpus  : {len(corpus)} cases  ({corpus_file})")
        return 0

    stats = import_published_evals(seed_file, corpus_file, dry_run=args.dry_run)
    prefix = "[dry-run] " if args.dry_run else ""
    print(f"  {prefix}added  : {stats['added']} new case(s)")
    print(f"  {prefix}skipped: {stats['skipped']} already present")
    print(f"  {prefix}corpus : {stats.get('corpus_size', '?')} total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
