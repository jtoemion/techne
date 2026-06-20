#!/usr/bin/env python3
"""
stack_detect.py — pick the right diagnose-skill subskill based on touched files.

The debugger (or any agent invoking the diagnose skill) calls this BEFORE Phase 4
(Instrument) to find stack-specific patterns. Output is a Markdown pointer the
agent loads via skill_view.

Usage:
    python3 stack_detect.py <repo_root>
    python3 stack_detect.py <repo_root> --json   # machine-readable

Detection is signature-based: each stack declares its file extensions,
config filenames, and import patterns. The first match wins (priority order).
Add a new stack by appending to STACKS — no other code changes needed.

This script is *also* an extension point: as new stacks recur (>=3 failure
patterns), add them here so the next debugger pre-loads the right patterns.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ── Stack signatures ────────────────────────────────────────────────────────
# Each stack: (name, skill_path, file_extensions, config_files, import_patterns)
# Priority order matters — more-specific stacks before more-general.

STACKS: list[dict] = [
    {
        "name": "firestore",
        "skill": "skills/diagnose/firestore.md",
        "extensions": [],
        "config_files": ["firestore.rules", "firestore.indexes.json", ".firebaserc"],
        "import_patterns": ["firebase/firestore", "from 'firebase/firestore'"],
        "description": "Firebase Firestore — rules, indexes, security",
    },
    {
        "name": "netlify",
        "skill": "skills/diagnose/netlify.md",
        "extensions": [],
        "config_files": ["netlify.toml", "_redirects", "_headers"],
        "import_patterns": ["netlify"],
        "description": "Netlify deploy, redirects, functions",
    },
    {
        "name": "svelte",
        "skill": "skills/diagnose/svelte.md",
        "extensions": [".svelte"],
        "config_files": ["svelte.config.js", "svelte.config.ts", "vite.config.ts"],
        "import_patterns": ["svelte", "@sveltejs"],
        "description": "Svelte/SvelteKit — runes, stores, lifecycle",
    },
    {
        "name": "nextjs",
        "skill": "skills/nextjs.md",
        "extensions": [],
        "config_files": ["next.config.js", "next.config.ts", "next.config.mjs"],
        "import_patterns": ["next/server", "next/router", "next/navigation", "next/image"],
        "description": "Next.js — app router, server components, edge runtime",
    },
    {
        "name": "react",
        "skill": "skills/react.md",
        "extensions": [".tsx", ".jsx"],
        "config_files": [],
        "import_patterns": ["react", "react-dom", "@tanstack"],
        "description": "React 19 — hooks, suspense, transitions",
    },
    {
        "name": "typescript",
        "skill": "skills/typescript.md",
        "extensions": [".ts"],
        "config_files": ["tsconfig.json"],
        "import_patterns": [],
        "description": "TypeScript — strict mode, type narrowing, generics",
    },
]


def detect(repo_root: Path) -> list[dict]:
    """Walk the repo and return all matching stacks with evidence.

    Returns list of {stack, matches, evidence} ordered by specificity (most
    matches first). Empty list means no specific stack detected.
    """
    if not repo_root.exists() or not repo_root.is_dir():
        return []

    hits: list[dict] = []

    # Index files once (extension + config presence)
    extensions_seen: set[str] = set()
    configs_seen: set[str] = set()
    imports_seen: list[str] = []

    for path in repo_root.rglob("*"):
        if path.is_dir():
            # Skip heavy dirs
            parts = path.parts
            if any(skip in parts for skip in ("node_modules", ".git", "dist", "build", ".next", ".svelte-kit", "__pycache__")):
                continue
            continue

        # Skip heavy dirs for files too
        parts = path.parts
        if any(skip in parts for skip in ("node_modules", ".git", "dist", "build", ".next", ".svelte-kit", "__pycache__")):
            continue

        extensions_seen.add(path.suffix.lower())
        configs_seen.add(path.name)

        # Sample imports from source files (first 5KB only — patterns are prefixes)
        if path.suffix in (".ts", ".tsx", ".js", ".jsx", ".svelte", ".py"):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")[:5120]
                imports_seen.append(text)
            except Exception:
                pass

    imports_blob = "\n".join(imports_seen)

    for stack in STACKS:
        evidence: list[str] = []
        matches = 0

        # File extensions
        for ext in stack["extensions"]:
            if ext in extensions_seen:
                evidence.append(f"ext:{ext}")
                matches += 1

        # Config files
        for cfg in stack["config_files"]:
            if cfg in configs_seen:
                evidence.append(f"cfg:{cfg}")
                matches += 2  # config files are stronger signals

        # Import patterns
        for pat in stack["import_patterns"]:
            if pat in imports_blob:
                evidence.append(f"import:{pat}")
                matches += 1

        if matches > 0:
            hits.append({
                "stack": stack["name"],
                "skill": stack["skill"],
                "description": stack["description"],
                "matches": matches,
                "evidence": evidence,
            })

    hits.sort(key=lambda h: -h["matches"])
    return hits


def format_markdown(repo_root: Path, hits: list[dict]) -> str:
    """Format a Markdown pointer the agent can pass to skill_view."""
    if not hits:
        return (
            f"# Stack Detection — {repo_root}\n\n"
            "No specific stack detected. Load `skills/diagnose.md` for the generic method.\n"
        )

    lines = [f"# Stack Detection — {repo_root}", ""]
    lines.append("**Load these skills via `skill_view` before Phase 4 (Instrument):**")
    lines.append("")
    for h in hits:
        lines.append(f"- `{h['skill']}` — {h['description']}")
        lines.append(f"  - Evidence: {', '.join(h['evidence'])}")
    lines.append("")
    lines.append("Always also load `skills/diagnose.md` and `skills/diagnose/feedback-loop.md`.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Detect tech stack and recommend diagnose subskills.")
    ap.add_argument("repo_root", type=Path, help="Path to project root")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown")
    args = ap.parse_args()

    hits = detect(args.repo_root)

    if args.json:
        print(json.dumps({"repo_root": str(args.repo_root), "hits": hits}, indent=2))
    else:
        print(format_markdown(args.repo_root, hits))
    return 0


if __name__ == "__main__":
    sys.exit(main())
