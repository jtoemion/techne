#!/usr/bin/env python3
"""project_graph_build.py — Build a file architecture graph for a project.

Scans the project directory, identifies file types/roles, builds a node/edge
graph of imports, file relationships, and architecture patterns.

Usage:
    cd ~/my-project && python3 /path/to/scripts/project_graph_build.py
    python3 scripts/project_graph_build.py --project ~/my-project
    python3 scripts/project_graph_build.py --quick       # faster: only top-level
"""

from __future__ import annotations
import argparse, json, os, sys, re
from pathlib import Path

ROOT = Path(__file__).parent.parent

# File type classification
PATTERNS: list[tuple[str, str, dict]] = [
    ("python", "**/*.py", {"role": "python module", "weight": 1}),
    ("typescript", "**/*.ts", {"role": "typescript source", "weight": 1}),
    ("tsx", "**/*.tsx", {"role": "react component", "weight": 2}),
    ("svelte", "**/*.svelte", {"role": "svelte component", "weight": 2}),
    ("test", "**/test_*.py", {"role": "test file", "weight": 3}),
    ("test", "**/*.test.*", {"role": "test file", "weight": 3}),
    ("config", "**/package.json", {"role": "package config", "weight": 4}),
    ("config", "**/svelte.config.*", {"role": "svelte config", "weight": 4}),
    ("config", "**/vite.config.*", {"role": "vite config", "weight": 4}),
    ("config", "**/tsconfig.*", {"role": "typescript config", "weight": 4}),
    ("config", "**/*.toml", {"role": "toml config", "weight": 4}),
    ("config", "**/*.yaml", {"role": "yaml config", "weight": 4}),
    ("db", "**/convex/schema.*", {"role": "database schema", "weight": 5}),
    ("db", "**/prisma/schema.*", {"role": "database schema", "weight": 5}),
    ("db", "**/*_migration*", {"role": "migration", "weight": 5}),
    ("docs", "**/*.md", {"role": "documentation", "weight": 0}),
]

EXCLUDES = {".git", "node_modules", ".venv", "__pycache__", ".svelte-kit", ".vercel", ".netlify", "dist", "build"}

def classify_file(path: Path, rel: str) -> dict | None:
    for label, glob, meta in PATTERNS:
        if path.match(glob):
            return {"id": rel, "label": label, "role": meta["role"], "weight": meta["weight"], "path": rel}
    return None

def find_imports(text: str, ext: str) -> list[str]:
    imports = []
    if ext == ".py":
        for m in re.findall(r"from\s+(\S+)\s+import|import\s+(\S+)", text):
            imports.extend(m)
    elif ext in (".ts", ".tsx"):
        for m in re.findall(r'from\s+["\x27](\S+?)["\x27]', text):
            imports.append(m)
    elif ext == ".svelte":
        for m in re.findall(r"import\s+\S+\s+from\s+[\"'](\S+)[\"']", text):
            imports.append(m)
    return [i for i in imports if i and not i.startswith(".")]

def main():
    parser = argparse.ArgumentParser(description="Build project architecture graph")
    parser.add_argument("--project", default=".", help="Project root directory")
    parser.add_argument("--quick", action="store_true", help="Skip import scanning")
    parser.add_argument("--output", default=".techne/context/project-graph.json", help="Output path")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    if not project.exists():
        print(f"Project not found: {project}"); sys.exit(1)

    exclude_dirs = EXCLUDES | {"build", "dist", ".vercel", ".netlify"}

    nodes: list[dict] = []
    edges: list[dict] = []
    seen_ids: set[str] = set()
    total = 0

    print(f"Scanning {project}...")
    for root, dirs, files in os.walk(project):
        # Prune excludes
        dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith(".")]
        for fname in files:
            fpath = Path(root) / fname
            try:
                rel = str(fpath.relative_to(project))
            except ValueError:
                continue
            node = classify_file(fpath, rel)
            if node is None:
                continue
            if rel not in seen_ids:
                nodes.append(node)
                seen_ids.add(rel)
            total += 1

            if not args.quick and fpath.suffix in (".py", ".ts", ".tsx", ".svelte"):
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                    imports = find_imports(text, fpath.suffix)
                    for imp in imports[:5]:
                        edges.append({
                            "source": rel,
                            "target": imp,
                            "type": "imports",
                            "weight": 1,
                        })
                except: pass

    output = {
        "project": project.name,
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "total_files": total,
        "nodes": nodes,
        "edges": edges if not args.quick else [],
    }

    output_path = project / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2))
    print(f"\nGraph built: {total} files, {len(nodes)} nodes, {len(edges)} edges")
    print(f"Output: {output_path}")

if __name__ == "__main__":
    main()
