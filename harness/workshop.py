"""
workshop.py — shared helpers for Techne's project-workshop shell.

The workshop is the project-attached layer that lives under `.techne/` in a
repo and provides:
  - authored subsystem context docs (`.techne/context/*.CONTEXT.md`)
  - generated deterministic indexes (`.techne/generated/*.json`)
  - workshop memory (`.techne/memory/*`)
  - project-scoped scripts (`.techne/scripts/*`)

This module is stdlib-first. It tolerates PyYAML if installed, but does not
require it.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONTEXT_GLOB = "*.CONTEXT.md"
DEFAULT_EXCLUDES = {
    ".git",
    "node_modules",
    ".svelte-kit",
    ".next",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "venv",
}


@dataclass
class WorkshopPaths:
    repo_root: Path
    workshop_dir: Path
    context_dir: Path
    generated_dir: Path
    memory_dir: Path
    proposals_dir: Path
    tasks_dir: Path
    scripts_dir: Path
    config_path: Path


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_repo_root(start: Path | None = None) -> Path | None:
    """Walk upward to find a git repo root."""
    cursor = (start or Path.cwd()).resolve()
    if cursor.is_file():
        cursor = cursor.parent
    while True:
        if (cursor / ".git").exists():
            return cursor
        if cursor == cursor.parent:
            return None
        cursor = cursor.parent


def find_workshop_paths(start: Path | None = None) -> WorkshopPaths | None:
    """Find the nearest repo root containing a `.techne/` directory.

    Requires `.techne/config.yaml` to exist for a valid workshop root.
    """
    cursor = (start or Path.cwd()).resolve()
    if cursor.is_file():
        cursor = cursor.parent
    while True:
        workshop_dir = cursor / ".techne"
        config_path = workshop_dir / "config.yaml"
        if workshop_dir.is_dir() and config_path.exists():
            return WorkshopPaths(
                repo_root=cursor,
                workshop_dir=workshop_dir,
                context_dir=workshop_dir / "context",
                generated_dir=workshop_dir / "generated",
                memory_dir=workshop_dir / "memory",
                proposals_dir=workshop_dir / "proposals",
                tasks_dir=workshop_dir / "tasks",
                scripts_dir=workshop_dir / "scripts",
                config_path=config_path,
            )
        if cursor == cursor.parent:
            return None
        cursor = cursor.parent


def ensure_workshop_dirs(paths: WorkshopPaths) -> None:
    for d in (
        paths.context_dir,
        paths.generated_dir,
        paths.memory_dir,
        paths.proposals_dir,
        paths.tasks_dir,
        paths.scripts_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)


def _strip_comment(line: str) -> str:
    if "#" not in line:
        return line.rstrip()
    before, _, _ = line.partition("#")
    return before.rstrip()


def _parse_yaml_simple(text: str) -> dict[str, Any]:
    """Minimal YAML parser.

    Supports the subset we need for workshop config/frontmatter:
    - flat scalars
    - inline lists: [a, b]
    - indented list items under a key
    - booleans / integers
    """
    result: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in text.splitlines():
        line = _strip_comment(raw_line)
        if not line.strip():
            continue
        stripped = line.strip()
        if ":" in stripped and not stripped.startswith("- "):
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if not val:
                current_key = key
                result[current_key] = []
                continue
            current_key = None
            result[key] = _parse_scalar_or_list(val)
        elif stripped.startswith("- ") and current_key:
            current = result.get(current_key)
            if not isinstance(current, list):
                current = []
                result[current_key] = current
            current.append(_parse_scalar_or_list(stripped[2:].strip()))
    return result


def _parse_scalar_or_list(val: str) -> Any:
    val = val.strip()
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [
            _parse_scalar_or_list(part.strip())
            for part in inner.split(",")
            if part.strip()
        ]
    low = val.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if re.fullmatch(r"-?\d+", val):
        return int(val)
    return val.strip('"').strip("'")


def load_yaml_or_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(text)
        return loaded or {}
    except Exception:
        pass
    try:
        loaded = json.loads(text)
        return loaded or {}
    except Exception:
        pass
    return _parse_yaml_simple(text)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse simple YAML frontmatter from Markdown text."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    raw = text[4:end]
    body = text[end + 5 :]
    try:
        import yaml  # type: ignore

        meta = yaml.safe_load(raw) or {}
    except Exception:
        meta = _parse_yaml_simple(raw)
    return meta, body


def relativize(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def gather_repo_files(repo_root: Path, extra_excludes: set[str] | None = None) -> list[Path]:
    excludes = set(DEFAULT_EXCLUDES)
    if extra_excludes:
        excludes |= set(extra_excludes)
    files: list[Path] = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(repo_root).parts
        if any(part in excludes for part in rel_parts):
            continue
        files.append(path)
    return sorted(files)


def load_workshop_config(paths: WorkshopPaths) -> dict[str, Any]:
    cfg = load_yaml_or_json(paths.config_path)
    cfg.setdefault("project_name", paths.repo_root.name)
    cfg.setdefault("context_glob", CONTEXT_GLOB)
    cfg.setdefault("generated_dir", ".techne/generated")
    cfg.setdefault("memory_dir", ".techne/memory")
    flat_generated = cfg.get("policy_generated")
    flat_proposed = cfg.get("policy_proposed")
    flat_manual = cfg.get("policy_manual")
    cfg.setdefault("proposal_policies", {
        "generated": [".techne/generated/**", ".techne/memory/wikilinks.*"],
        "proposed": [".techne/context/*.CONTEXT.md"],
        "manual": ["docs/adr/**", "docs/architecture/**"],
    })
    if flat_generated or flat_proposed or flat_manual:
        cfg["proposal_policies"] = {
            "generated": list(flat_generated or cfg["proposal_policies"].get("generated", [])),
            "proposed": list(flat_proposed or cfg["proposal_policies"].get("proposed", [])),
            "manual": list(flat_manual or cfg["proposal_policies"].get("manual", [])),
        }
    cfg.setdefault("search", {"max_results": cfg.get("search_max_results", 8)})
    return cfg


def read_context_docs(paths: WorkshopPaths) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    if not paths.context_dir.exists():
        return docs
    for p in sorted(paths.context_dir.glob(CONTEXT_GLOB)):
        meta, body = parse_frontmatter(p.read_text(encoding="utf-8"))
        subsystem = meta.get("subsystem") or p.stem.replace(".CONTEXT", "")
        raw_paths = meta.get("paths") or []
        if isinstance(raw_paths, str):
            raw_paths = [raw_paths]
        tags = meta.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        related_tests = meta.get("related_tests") or []
        if isinstance(related_tests, str):
            related_tests = [related_tests]
        docs.append(
            {
                "path": relativize(p, paths.repo_root),
                "absolute_path": str(p.resolve()),
                "subsystem": subsystem,
                "tags": list(tags),
                "paths": list(raw_paths),
                "related_tests": list(related_tests),
                "refresh_policy": meta.get("refresh_policy", "proposed"),
                "frontmatter": meta,
                "body": body,
            }
        )
    return docs


def _best_subsystem_for_path(rel_path: str, context_docs: list[dict[str, Any]]) -> str | None:
    best: tuple[int, str] | None = None
    for doc in context_docs:
        subsystem = doc["subsystem"]
        for root in doc.get("paths", []):
            root = str(root).strip().strip("/")
            if not root:
                continue
            if rel_path == root or rel_path.startswith(root + "/"):
                score = len(root)
                if best is None or score > best[0]:
                    best = (score, subsystem)
    return best[1] if best else None


def build_context_index(paths: WorkshopPaths) -> dict[str, Any]:
    ensure_workshop_dirs(paths)
    config = load_workshop_config(paths)
    context_docs = read_context_docs(paths)
    repo_files = gather_repo_files(paths.repo_root)

    files: list[dict[str, Any]] = []
    subsystem_counts: dict[str, int] = {}
    for file_path in repo_files:
        rel = relativize(file_path, paths.repo_root)
        subsystem = _best_subsystem_for_path(rel, context_docs)
        if subsystem:
            subsystem_counts[subsystem] = subsystem_counts.get(subsystem, 0) + 1
        files.append(
            {
                "path": rel,
                "subsystem": subsystem,
                "ext": file_path.suffix,
            }
        )

    subsystems: list[dict[str, Any]] = []
    for doc in context_docs:
        subsystems.append(
            {
                "name": doc["subsystem"],
                "paths": doc.get("paths", []),
                "context_doc": doc["path"],
                "tags": doc.get("tags", []),
                "related_tests": doc.get("related_tests", []),
                "refresh_policy": doc.get("refresh_policy", "proposed"),
                "file_count": subsystem_counts.get(doc["subsystem"], 0),
            }
        )

    index = {
        "generated_at": now_utc(),
        "repo_root": str(paths.repo_root.resolve()),
        "project_name": config.get("project_name", paths.repo_root.name),
        "context_docs": [
            {
                "path": d["path"],
                "subsystem": d["subsystem"],
                "tags": d.get("tags", []),
                "paths": d.get("paths", []),
                "refresh_policy": d.get("refresh_policy", "proposed"),
            }
            for d in context_docs
        ],
        "subsystems": subsystems,
        "files": files,
        "summary": {
            "subsystem_count": len(subsystems),
            "context_doc_count": len(context_docs),
            "file_count": len(files),
        },
    }
    return index


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_context_index(paths: WorkshopPaths) -> dict[str, Any]:
    index_path = paths.generated_dir / "context_index.json"
    if not index_path.exists():
        raise FileNotFoundError(
            f"Missing {index_path}. Run .techne/scripts/context_index.py first."
        )
    return json.loads(index_path.read_text(encoding="utf-8"))


def workshop_memory_candidates(paths: WorkshopPaths) -> dict[str, Path]:
    """Preferred workshop-local memory with fallbacks to legacy root memory."""
    root_memory = paths.repo_root / "memory"
    return {
        "ledger": paths.memory_dir / "ledger.md" if (paths.memory_dir / "ledger.md").exists() else root_memory / "ledger.md",
        "mistakes": paths.memory_dir / "mistakes.md" if (paths.memory_dir / "mistakes.md").exists() else root_memory / "mistakes.md",
        "wikilinks_json": paths.memory_dir / "wikilinks.json" if (paths.memory_dir / "wikilinks.json").exists() else root_memory / "wikilinks.json",
        "wikilinks_md": paths.memory_dir / "wikilinks.md" if (paths.memory_dir / "wikilinks.md").exists() else root_memory / "wikilinks.md",
    }


def score_text(query_terms: list[str], *texts: str) -> int:
    hay = "\n".join(t.lower() for t in texts if t)
    score = 0
    for term in query_terms:
        if term in hay:
            score += 1
    return score


def detect_subsystems_for_files(index: dict[str, Any], file_paths: list[str]) -> list[str]:
    mapping = {entry["path"]: entry.get("subsystem") for entry in index.get("files", [])}
    subsystems: list[str] = []
    for path in file_paths:
        subsystem = mapping.get(path)
        if subsystem and subsystem not in subsystems:
            subsystems.append(subsystem)
    return subsystems


def touched_files_from_git(repo_root: Path, since: str | None = None) -> list[str]:
    import subprocess

    cmd = ["git", "diff", "--name-only"]
    if since:
        cmd.append(since)
    else:
        cmd.append("HEAD")
    proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "git diff failed")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def read_text_if_exists(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def stale_context_reasons(touched_files: list[str], context_docs: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Simple stale-doc heuristic: touched file under subsystem path but absent from doc body."""
    results: list[dict[str, str]] = []
    for doc in context_docs:
        body = doc.get("body", "")
        subsystem = doc["subsystem"]
        doc_path = doc["path"]
        roots = [str(p).strip().strip("/") for p in doc.get("paths", [])]
        for touched in touched_files:
            if not any(touched == root or touched.startswith(root + "/") for root in roots if root):
                continue
            basename = Path(touched).name
            if basename and basename not in body and touched not in body:
                results.append(
                    {
                        "path": doc_path,
                        "subsystem": subsystem,
                        "touched_file": touched,
                        "reason": "touched file is inside subsystem roots but not mentioned in context doc body",
                    }
                )
    return results


def classify_policy(path_str: str, config: dict[str, Any]) -> str:
    policies = config.get("proposal_policies", {})
    for policy in ("generated", "proposed", "manual"):
        patterns = policies.get(policy, []) or []
        for pattern in patterns:
            pattern = pattern.rstrip("/")
            if pattern.endswith("/**"):
                prefix = pattern[:-3].rstrip("/")
                if path_str == prefix or path_str.startswith(prefix + "/"):
                    return policy
            elif "*" not in pattern:
                if path_str == pattern or path_str.startswith(pattern.rstrip("/") + "/"):
                    return policy
            else:
                regex = "^" + re.escape(pattern).replace("\\*", ".*") + "$"
                if re.match(regex, path_str):
                    return policy
    return "manual"
