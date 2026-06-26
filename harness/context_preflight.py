"""
context_preflight.py — mandatory context preparation for Techne tasks.

The orchestrator calls this before IMPLEMENT so worker agents receive a
targeted context pack instead of rediscovering the repository from scratch.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable

HARNESS_DIR = Path(__file__).parent
ROOT = HARNESS_DIR.parent
CONTEXT_DIR = ROOT / ".techne" / "context"
PACKS_DIR = CONTEXT_DIR / "context_packs"


def _resolve_context_dirs(root: Path) -> tuple[Path, Path]:
    """Return (context_dir, packs_dir) for the given project root."""
    ctx = root / ".techne" / "context"
    pks = ctx / "context_packs"
    return ctx, pks

BASE_FILES = (
    "project_digest.md",
    "file_roles.md",
    "commands.md",
    "risk_boundaries.md",
)

HASH_WATCH_PATTERNS = (
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "pyproject.toml",
    "requirements.txt",
    "tsconfig.json",
    "jsconfig.json",
    "vite.config.*",
    "next.config.*",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    ".env.example",
    ".hermes/skills/techne-skills/skill-router.yaml",
    "harness/gate-config.yaml",
    "harness/context_preflight.py",
    "harness/pipeline_enforcer.py",
)

PACK_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("techne", ("techne", "harness", "agent", "agents", "skill", "router", "gate", "loop", "task_db")),
    ("auth", ("auth", "login", "session", "jwt", "token", "oauth", "middleware")),
    ("database", ("database", "schema", "migration", "sql", "sqlite", "postgres", "pgvector", "dexie")),
    ("frontend", ("frontend", "react", "vite", "component", "page", "route", "ui", "css", "svelte")),
    ("deployment", ("deploy", "docker", "nginx", "tls", "dns", "vps", "production", "env", "secret")),
    ("testing", ("test", "pytest", "eval", "coverage", "mock", "fixture")),
)


def ensure_context_dir() -> None:
    """Create the context directory structure without creating content."""
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    PACKS_DIR.mkdir(parents=True, exist_ok=True)


def _watched_files(root: Path = ROOT) -> list[Path]:
    ctx_dir, pks_dir = _resolve_context_dirs(root)
    ctx_dir.mkdir(parents=True, exist_ok=True)
    pks_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []

    for pattern in HASH_WATCH_PATTERNS:
        files.extend(p for p in root.glob(pattern) if p.is_file())

    if ctx_dir.exists():
        files.extend(p for p in ctx_dir.glob("*.md") if p.is_file())
        if pks_dir.exists():
            files.extend(p for p in pks_dir.glob("*.md") if p.is_file())

    return sorted({p.resolve() for p in files})


def compute_context_hash(root: Path = ROOT) -> str:
    """Hash context-affecting files, excluding context_hash.txt itself."""
    h = hashlib.sha256()

    for path in _watched_files(root):
        try:
            rel = path.relative_to(root)
        except ValueError:
            rel = path
        h.update(str(rel).replace("\\", "/").encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())

    return h.hexdigest()[:16]


def context_status(root: Path = ROOT) -> dict[str, object]:
    """Return context freshness and selected metadata."""
    ctx_dir, pks_dir = _resolve_context_dirs(root)
    ctx_dir.mkdir(parents=True, exist_ok=True)
    pks_dir.mkdir(parents=True, exist_ok=True)
    base = {name: (ctx_dir / name).exists() for name in BASE_FILES}
    packs = sorted(p.stem for p in pks_dir.glob("*.md")) if pks_dir.exists() else []
    current_hash = compute_context_hash(root)
    stored_path = ctx_dir / "context_hash.txt"
    stored_hash = stored_path.read_text(encoding="utf-8").strip() if stored_path.exists() else ""

    return {
        "dir": str(ctx_dir),
        "base_files": base,
        "missing_base_files": [name for name, exists in base.items() if not exists],
        "packs": packs,
        "current_hash": current_hash,
        "stored_hash": stored_hash,
        "fresh": bool(stored_hash) and stored_hash == current_hash,
    }


def write_context_hash(root: Path = ROOT) -> str:
    """Write the current context hash and return it."""
    ctx_dir, pks_dir = _resolve_context_dirs(root)
    ctx_dir.mkdir(parents=True, exist_ok=True)
    pks_dir.mkdir(parents=True, exist_ok=True)
    digest = compute_context_hash(root)
    (ctx_dir / "context_hash.txt").write_text(f"{digest}\n", encoding="utf-8")
    return digest


def select_context_pack(
    title: str,
    description: str = "",
    discipline: str = "",
    tags: Iterable[str] | None = None,
    changed_files: Iterable[str] | None = None,
) -> list[str]:
    """Select context packs from task metadata."""
    text = "\n".join(
        [
            title,
            description,
            discipline,
            " ".join(tags or []),
            " ".join(changed_files or []),
        ]
    ).lower()

    selected: list[str] = []
    for pack_name, needles in PACK_RULES:
        if any(needle in text for needle in needles):
            selected.append(pack_name)

    # Keep deterministic order and avoid duplicates.
    return list(dict.fromkeys(selected))


def _format_list(items: Iterable[str]) -> str:
    values = list(items)
    return ", ".join(values) if values else "none"


def format_preflight_prompt(
    task_id: str,
    title: str,
    description: str = "",
    discipline: str = "",
    tags: Iterable[str] | None = None,
    changed_files: Iterable[str] | None = None,
) -> str:
    """Build the mandatory context-preflight prompt for the host agent."""
    status = context_status()
    packs = select_context_pack(title, description, discipline, tags, changed_files)
    pack_files = [f"{pack}.md" for pack in packs]
    missing = status["missing_base_files"]
    stale = not status["fresh"]

    lines = [
        "CONTEXT_PREFLIGHT (mandatory)",
        f"TASK: {task_id} — {title}",
        f"DISCIPLINE: {discipline or 'general'}",
        "",
        "CONTEXT STATUS:",
        f"  base_missing: {_format_list(missing) if missing else 'none'}",
        f"  stale: {'yes' if stale else 'no'}",
        f"  current_hash: {status['current_hash']}",
        f"  stored_hash: {status['stored_hash'] or 'missing'}",
        f"  available_packs: {_format_list(status['packs'])}",
        "",
        f"SELECTED_PACKS: {_format_list(pack_files)}",
        "",
        "REQUIRED ACTION:",
        "  1. Create missing base context files under .techne/context/.",
        "  2. Refresh stale context files and selected packs.",
        "  3. Write .techne/context/context_hash.txt after edits.",
        "  4. Return a short report with files written and HITL boundaries.",
    ]

    if not missing and not stale:
        lines.append("  5. Confirm context is fresh; no file edits are needed.")
    else:
        lines.append("  5. Do not proceed to IMPLEMENT until context_hash.txt is fresh.")

    lines.extend(
        [
            "",
            "READ ORDER FOR NEXT PHASE:",
            "  .techne/context/project_digest.md",
            "  .techne/context/file_roles.md",
            "  .techne/context/commands.md",
            "  .techne/context/risk_boundaries.md",
            "  selected .techne/context/context_packs/*.md files",
            "",
            "WORKER AGENT RULE:",
            "  Worker agents may not browse the whole repo. Use the digest,",
            "  file role map, risk boundaries, selected packs, and task files only.",
        ]
    )

    return "\n".join(lines)


def extract_changed_files_from_report(report: str) -> list[str]:
    """Extract written context files from a context-preflight report."""
    files: list[str] = []
    for line in report.splitlines():
        match = re.search(r"\.techne/context/([^\s]+)", line)
        if match:
            path = match.group(1).rstrip(",;:")
            if path and path not in files:
                files.append(f".techne/context/{path}")
    return files


if __name__ == "__main__":
    print(format_preflight_prompt("demo-task", "Add context preflight to Techne", discipline="tdd"))
