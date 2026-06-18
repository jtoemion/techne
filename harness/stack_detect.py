"""
stack_detect.py — detect a project's framework stack from its manifest + config files.

The harness already HASHES these files (context_preflight.HASH_WATCH_PATTERNS) but
never reads them to answer "which framework is this." This closes that gap: read
package.json dependencies and the presence of stack-defining config files, and return
a set of stack tags. The loader (router.resolve_stack_skills) maps tags → the framework
pattern files to inject, so a SvelteKit/Firestore project never carries Next.js patterns
as dead weight — and Techne's own Python harness pulls in no JS framework files at all.

Pure + cheap: reads a handful of files, no network, no install. Detection keys off the
TARGET project root (the repo being worked on), which is where package.json lives.
"""
from __future__ import annotations

import json
from pathlib import Path

HARNESS_DIR = Path(__file__).parent
ROOT = HARNESS_DIR.parent

# Dependency-name → stack tag. Matched at TOKEN boundaries (see _dep_matches), not by
# bare substring — bare substring tagged preact→react, context→next, vitest→vite. The
# matcher still resolves related packages: "react-dom", "@sveltejs/kit", "@netlify/fn".
DEP_TAGS: tuple[tuple[str, str], ...] = (
    ("@sveltejs/kit", "sveltekit"),
    ("svelte", "svelte"),
    ("next", "nextjs"),
    ("react", "react"),
    ("typescript", "typescript"),
    ("vite", "vite"),
    ("firebase", "firestore"),
    ("firestore", "firestore"),
    ("netlify", "netlify"),
)

# Config / marker file (glob) present → stack tag. Catches projects whose framework
# is configured but not an obvious dependency name.
FILE_TAGS: tuple[tuple[str, str], ...] = (
    ("next.config.*", "nextjs"),
    ("svelte.config.*", "sveltekit"),
    ("vite.config.*", "vite"),
    ("tsconfig.json", "typescript"),
    ("netlify.toml", "netlify"),
    ("firebase.json", "firestore"),
    ("firestore.rules", "firestore"),
)

# Tags that imply other tags (a SvelteKit app is a Svelte app; Next implies React).
IMPLIES: dict[str, tuple[str, ...]] = {
    "sveltekit": ("svelte",),
    "nextjs": ("react",),
}


def _dep_matches(dep: str, needle: str) -> bool:
    """True if dependency `dep` belongs to framework `needle`, matched at token
    boundaries so unrelated substrings don't trip it (preact != react, context !=
    next). Resolves exact names, `needle-*` prefixes, and scoped `@needle*/...` or
    `@scope/needle*` packages."""
    if dep == needle or dep.startswith(needle + "-") or dep.startswith(needle + "/"):
        return True
    if dep.startswith("@") and "/" in dep:
        scope, _, name = dep[1:].partition("/")
        if scope == needle or scope.startswith(needle):  # @sveltejs/kit → svelte
            return True
        if name == needle or name.startswith(needle + "-"):  # @scope/react-x
            return True
    return False


def _read_package_deps(root: Path) -> set[str]:
    """All dependency names from package.json (deps + devDeps + peerDeps)."""
    pkg = root / "package.json"
    if not pkg.exists():
        return set()
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    deps: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        section = data.get(key)
        if isinstance(section, dict):
            deps.update(section.keys())
    return deps


def detect_stack(root: Path | str = ROOT) -> set[str]:
    """Return the set of stack tags for the project at `root`.

    An empty set means no recognized JS framework (e.g., a pure-Python repo) — the
    loader then injects no framework pattern files. Pure: no side effects.
    """
    root = Path(root)
    tags: set[str] = set()

    deps = _read_package_deps(root)
    for dep in deps:
        for needle, tag in DEP_TAGS:
            if _dep_matches(dep, needle):
                tags.add(tag)

    for pattern, tag in FILE_TAGS:
        if any(root.glob(pattern)):
            tags.add(tag)

    # Apply implications (one pass suffices for this shallow graph).
    for tag in list(tags):
        tags.update(IMPLIES.get(tag, ()))

    return tags


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else str(ROOT)
    found = detect_stack(target)
    print(f"stack at {target}: {', '.join(sorted(found)) or '(none — no JS framework)'}")
