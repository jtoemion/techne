#!/usr/bin/env python3
"""context_gap.py — W2 Context Engine: AST-based context-gap detector.

Checks whether changed source files have corresponding context coverage in
.techne/context/. A "gap" is a changed Python file with no corresponding
CONTEXT.md entry, no mention in project_digest.md, and no entry in file_roles.md.

A gap does NOT block the pipeline (context is authoring cost, not a correctness
proof). It produces a structured report so the agent knows WHICH files need
context before GROUND (RECALL) can claim "the grounding is solid".

Usage:
    python context_gap.py --files src/foo.py src/bar.py
    python context_gap.py --scope-file .techne/loop/file_scope.json
    python context_gap.py --scope-file .techne/loop/file_scope.json --json

Output (JSON):
    {
      "gaps": ["src/foo.py"],   # files with no context coverage
      "covered": ["src/bar.py"],
      "gap_count": 1,
      "covered_count": 1,
      "recommendation": "..."
    }

Exit codes:
    0 — all files covered (or no Python files to check)
    1 — gaps found
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_CONTEXT_DIR = _ROOT / ".techne" / "context"


def _load_context_corpus(context_dir: Path) -> str:
    """Load all context files into one searchable string."""
    parts: list[str] = []
    for p in sorted(context_dir.rglob("*.md")):
        try:
            parts.append(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    return "\n".join(parts).lower()


def _extract_symbols(file_path: Path) -> list[str]:
    """Extract top-level function/class names from a Python file."""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return []
    return [
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and isinstance(getattr(node, "parent", None) if hasattr(node, "parent") else None, ast.Module)
        # top-level only — simpler: col_offset == 0
    ] + [
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and getattr(node, "col_offset", 1) == 0
    ]


def _is_covered(file_path: Path, corpus: str) -> bool:
    """Return True if the file appears to be documented in the context corpus."""
    if not corpus:
        return False  # no context at all → everything is a gap

    import re as _re

    # Check 1: filename with extension appearing in context (e.g. "auth.py")
    filename = Path(str(file_path)).name.lower()  # e.g. "auth.py"
    if _re.search(r'\b' + _re.escape(filename), corpus):
        return True

    # Check 2: file stem in backtick code span e.g. `auth` or `src/auth`
    stem = Path(str(file_path)).stem.lower()
    if _re.search(r'`[^`]*' + _re.escape(stem) + r'[^`]*`', corpus):
        return True

    # Check 3: relative path fragment (e.g. "src/auth.py" or "src/auth")
    try:
        rel = str(Path(str(file_path)).resolve().relative_to(_ROOT))
    except ValueError:
        rel = str(file_path)
    rel_norm = rel.replace("\\", "/").lower()
    if len(rel_norm) > 5 and rel_norm in corpus:  # must be a real path, not just stem
        return True

    return False


def check_files(
    files: list[str | Path],
    context_dir: Path | None = None,
) -> dict:
    """Check coverage for a list of files. Returns structured report."""
    ctx_dir = context_dir or _CONTEXT_DIR
    corpus = _load_context_corpus(ctx_dir) if ctx_dir.exists() else ""

    py_files = [
        Path(f) for f in files
        if str(f).endswith(".py")
    ]

    gaps: list[str] = []
    covered: list[str] = []

    for fp in py_files:
        if _is_covered(fp, corpus):
            covered.append(str(fp))
        else:
            gaps.append(str(fp))

    recommendation = ""
    if gaps:
        recommendation = (
            f"{len(gaps)} file(s) lack context coverage. "
            f"Add a .techne/context/ entry mentioning: "
            + ", ".join(Path(g).stem for g in gaps[:3])
            + (f" (+ {len(gaps)-3} more)" if len(gaps) > 3 else "")
            + ". Without coverage, grounding retrieval for these files returns nothing."
        )

    return {
        "gaps": gaps,
        "covered": covered,
        "gap_count": len(gaps),
        "covered_count": len(covered),
        "recommendation": recommendation,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import argparse
    p = argparse.ArgumentParser(description="Context-gap detector (W2)")
    p.add_argument("--files", nargs="+", help="Files to check")
    p.add_argument("--scope-file", help="JSON file with list of files (file_scope.json)")
    p.add_argument("--context-dir", help="Override .techne/context/ path")
    p.add_argument("--json", action="store_true", help="JSON output")
    args = p.parse_args()

    files: list[str] = []
    if args.files:
        files.extend(args.files)
    if args.scope_file:
        try:
            files.extend(json.loads(Path(args.scope_file).read_text(encoding="utf-8")))
        except Exception as e:
            print(f"Error reading scope file: {e}")
            return 1

    if not files:
        p.error("--files or --scope-file required")

    ctx_dir = Path(args.context_dir) if args.context_dir else None
    report = check_files(files, ctx_dir)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        status = "PASS" if report["gap_count"] == 0 else "GAPS FOUND"
        print(f"  [{status}] context-gap: {report['covered_count']} covered, "
              f"{report['gap_count']} gaps")
        for g in report["gaps"]:
            print(f"    GAP  {g}")
        for c in report["covered"]:
            print(f"    OK   {c}")
        if report["recommendation"]:
            print(f"  => {report['recommendation']}")

    return 0 if report["gap_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
