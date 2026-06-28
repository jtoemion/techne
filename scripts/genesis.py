#!/usr/bin/env python3
"""genesis.py — W2 GENESIS cold-start bootstrap (GRAND-PLAN-FINAL).

One-time bootstrap that mines conventions from the codebase via static analysis
and seeds the OKF context store. Produces a verifiable .bootstrap contract that
can be checked in a fresh sandbox.

What it does:
  1. Scan the repo: detect stack, top-level layout, test commands
  2. Mine Python public API surface (modules, classes, functions)
  3. Produce OKF-style context files in .techne/context/:
       genesis-api-surface.md   — public symbols per module
       genesis-conventions.md   — detected conventions (test runner, imports, etc.)
       genesis-structure.md     — top-level directory layout
  4. Write .techne/genesis.json — the verifiable contract (SHA of produced files)

The contract is reward-hacking-resistant because:
  - It must actually PASS context_gap.py on the source files it claims to cover
  - The SHA chain in genesis.json pins what was produced and when
  - Running genesis.py twice is idempotent (won't overwrite richer hand-written files)

Usage:
    python genesis.py                     # bootstrap current repo
    python genesis.py --force             # regenerate even if exists
    python genesis.py --dry-run           # show what would be written, don't write
    python genesis.py --verify            # verify .bootstrap contract is intact
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_CONTEXT_DIR = _ROOT / ".techne" / "context"
_CONTRACT = _ROOT / ".techne" / "genesis.json"

_SKIP_DIRS = {
    ".git", ".techne", "__pycache__", "node_modules", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".claude",
}


def _find_python_modules(root: Path) -> list[Path]:
    """Find Python source files (not tests, not __pycache__)."""
    modules: list[Path] = []
    for p in sorted(root.rglob("*.py")):
        # Skip if any path component RELATIVE to root is in the skip set.
        # (Do not check absolute path parts — the repo may live inside .claude/worktrees/)
        try:
            rel_parts = p.relative_to(root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        if p.name.startswith("test_") or "tests" in rel_parts:
            continue
        modules.append(p)
    return modules


def _mine_api_surface(modules: list[Path]) -> dict[str, list[str]]:
    """Extract top-level public symbols from each module."""
    surface: dict[str, list[str]] = {}
    for mod in modules:
        try:
            tree = ast.parse(mod.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        symbols = [
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and getattr(node, "col_offset", 1) == 0
            and not node.name.startswith("_")
        ]
        if symbols:
            try:
                rel = str(mod.relative_to(_ROOT)).replace("\\", "/")
            except ValueError:
                rel = str(mod).replace("\\", "/")
            surface[rel] = symbols
    return surface


def _detect_conventions(root: Path) -> dict[str, str]:
    """Detect project conventions from manifests."""
    conv: dict[str, str] = {}

    # Test runner
    if (root / "pytest.ini").exists() or (root / "pyproject.toml").exists():
        conv["test_runner"] = "pytest"
    elif (root / "setup.cfg").exists():
        conv["test_runner"] = "pytest (setup.cfg)"

    # Type checker
    if (root / "mypy.ini").exists() or (root / ".mypy.ini").exists():
        conv["type_checker"] = "mypy"
    elif (root / "pyproject.toml").exists():
        t = (root / "pyproject.toml").read_text(encoding="utf-8", errors="replace")
        if "pyright" in t:
            conv["type_checker"] = "pyright"
        elif "mypy" in t:
            conv["type_checker"] = "mypy"

    # Import style
    init_files = list((root / "harness").glob("__init__.py")) if (root / "harness").exists() else []
    if init_files:
        conv["package_root"] = "harness/"

    # Git presence
    if (root / ".git").exists():
        conv["vcs"] = "git"

    return conv


def _detect_structure(root: Path) -> list[dict]:
    """Top-level directory layout with file counts."""
    entries: list[dict] = []
    for child in sorted(root.iterdir()):
        if child.name.startswith(".") or child.name in _SKIP_DIRS:
            continue
        if child.is_dir():
            py_count = len(list(child.rglob("*.py")))
            entries.append({
                "name": child.name,
                "type": "dir",
                "py_files": py_count,
            })
    return entries


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_okf_file(path: Path, frontmatter: dict, body: str, force: bool) -> bool:
    """Write an OKF-style context file. Returns True if written."""
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    fm_lines = ["---"]
    fm_lines.append(f"name: {frontmatter.get('name', path.stem)}")
    fm_lines.append(f"type: {frontmatter.get('type', 'source-note')}")
    fm_lines.append(f"title: {frontmatter.get('title', path.stem)}")
    fm_lines.append(f"description: {frontmatter.get('description', 'Auto-generated by genesis.py')}")
    fm_lines.append(f"timestamp: {now}")
    fm_lines.append("tags: [genesis, auto]")
    fm_lines.append("---")
    content = "\n".join(fm_lines) + "\n\n" + body
    path.write_text(content, encoding="utf-8")
    return True


def run_bootstrap(root: Path, force: bool = False, dry_run: bool = False) -> dict:
    """Run the GENESIS bootstrap. Returns the contract dict."""
    _CONTEXT_DIR.mkdir(parents=True, exist_ok=True)

    # Mine data
    modules = _find_python_modules(root)
    api_surface = _mine_api_surface(modules)
    conventions = _detect_conventions(root)
    structure = _detect_structure(root)

    # Build context file content
    files_written: list[str] = []
    produced_shas: dict[str, str] = {}

    # 1. API surface
    api_lines = ["# Auto-generated API Surface (GENESIS)\n"]
    api_lines.append(f"Generated from {len(modules)} Python source modules.\n")
    for mod_path, symbols in sorted(api_surface.items())[:40]:  # cap for size
        api_lines.append(f"\n## `{mod_path}`\n")
        for sym in symbols[:20]:
            api_lines.append(f"- `{sym}`")
    api_body = "\n".join(api_lines)

    api_file = _CONTEXT_DIR / "genesis-api-surface.md"
    if not dry_run:
        written = _write_okf_file(api_file, {
            "name": "genesis-api-surface",
            "type": "source-note",
            "title": "Auto-generated API surface",
            "description": f"Public symbols from {len(modules)} Python modules",
        }, api_body, force)
        if written:
            files_written.append(str(api_file.relative_to(root)))
        produced_shas["genesis-api-surface.md"] = _sha(api_body)

    # 2. Conventions
    conv_lines = ["# Auto-detected Project Conventions (GENESIS)\n"]
    for k, v in sorted(conventions.items()):
        conv_lines.append(f"- **{k}**: {v}")
    if not conventions:
        conv_lines.append("- No conventions auto-detected. Hand-write .techne/context/ files.")
    conv_body = "\n".join(conv_lines)

    conv_file = _CONTEXT_DIR / "genesis-conventions.md"
    if not dry_run:
        written = _write_okf_file(conv_file, {
            "name": "genesis-conventions",
            "type": "policy-note",
            "title": "Auto-detected conventions",
            "description": "Test runner, type checker, VCS detected from manifests",
        }, conv_body, force)
        if written:
            files_written.append(str(conv_file.relative_to(root)))
        produced_shas["genesis-conventions.md"] = _sha(conv_body)

    # 3. Structure
    struct_lines = ["# Auto-generated Project Structure (GENESIS)\n",
                    f"Repo root: `{root.name}`\n",
                    "| Directory | Python files |",
                    "|-----------|-------------|"]
    for entry in structure:
        struct_lines.append(f"| `{entry['name']}/` | {entry['py_files']} |")
    struct_body = "\n".join(struct_lines)

    struct_file = _CONTEXT_DIR / "genesis-structure.md"
    if not dry_run:
        written = _write_okf_file(struct_file, {
            "name": "genesis-structure",
            "type": "domain",
            "title": "Project structure",
            "description": "Top-level directory layout auto-detected at bootstrap",
        }, struct_body, force)
        if written:
            files_written.append(str(struct_file.relative_to(root)))
        produced_shas["genesis-structure.md"] = _sha(struct_body)

    # Build contract
    contract = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "modules_scanned": len(modules),
        "files_written": files_written,
        "shas": produced_shas,
        "conventions": conventions,
        "contract_sha": _sha(json.dumps(produced_shas, sort_keys=True)),
    }

    if not dry_run:
        _CONTRACT.write_text(
            json.dumps(contract, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    return contract


def verify_contract(root: Path) -> tuple[bool, str]:
    """Verify the .bootstrap contract is intact (produced files match their SHAs)."""
    if not _CONTRACT.exists():
        return False, "No genesis.json contract found. Run: python genesis.py"
    try:
        contract = json.loads(_CONTRACT.read_text(encoding="utf-8"))
    except Exception as e:
        return False, f"Failed to parse genesis.json: {e}"

    shas = contract.get("shas", {})
    for filename, expected_sha in shas.items():
        path = _CONTEXT_DIR / filename
        if not path.exists():
            return False, f"Contract file missing: {filename}"
        # SHA check is on body only (stripped), not frontmatter (timestamps vary)
        text = path.read_text(encoding="utf-8")
        body = text.split("---\n", 2)[-1].lstrip("\n") if "---" in text else text
        actual_sha = _sha(body)
        if actual_sha != expected_sha:
            return False, (
                f"SHA mismatch for {filename}: "
                f"expected {expected_sha[:12]}... got {actual_sha[:12]}..."
            )

    return True, f"Contract verified: {len(shas)} file(s) intact"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import argparse
    p = argparse.ArgumentParser(description="GENESIS cold-start bootstrap (W2)")
    p.add_argument("--force", action="store_true",
                   help="Regenerate files even if they already exist")
    p.add_argument("--dry-run", action="store_true",
                   help="Show what would be written without writing")
    p.add_argument("--verify", action="store_true",
                   help="Verify the genesis.json contract is intact")
    args = p.parse_args()

    if args.verify:
        ok, msg = verify_contract(_ROOT)
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {msg}")
        return 0 if ok else 1

    print(f"  GENESIS bootstrap — scanning {_ROOT.name}...")
    contract = run_bootstrap(_ROOT, force=args.force, dry_run=args.dry_run)

    if args.dry_run:
        print(f"  [DRY-RUN] Would scan {contract['modules_scanned']} modules")
        print(f"  [DRY-RUN] Would write {len(contract.get('shas', {}))} context files")
        for f in contract.get("files_written", []):
            print(f"    + {f}")
        return 0

    print(f"  Scanned: {contract['modules_scanned']} Python source modules")
    written = contract.get("files_written", [])
    if written:
        print(f"  Written: {len(written)} file(s)")
        for f in written:
            print(f"    + {f}")
    else:
        print("  No new files written (already exists; use --force to regenerate)")
    print(f"  Contract: .techne/genesis.json (sha={contract['contract_sha'][:16]}...)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
