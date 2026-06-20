from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest.mock as mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = REPO_ROOT / "harness"
SCRIPTS_DIR = REPO_ROOT / ".techne" / "scripts"
sys.path.insert(0, str(HARNESS_DIR))

import wikilink  # noqa: E402
from workshop import classify_policy, find_workshop_paths, load_workshop_config  # noqa: E402


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_workshop_repo(base: Path) -> Path:
    _write(
        base / ".techne" / "config.yaml",
        "\n".join(
            [
                "project_name: sample-workshop",
                "context_glob: '*.CONTEXT.md'",
                "generated_dir: .techne/generated",
                "memory_dir: .techne/memory",
                "search_max_results: 8",
                "policy_generated: [.techne/generated/**, .techne/memory/wikilinks.*]",
                "policy_proposed: [.techne/context/*.CONTEXT.md, docs/architecture/**]",
                "policy_manual: [README.md, docs/adr/**]",
            ]
        ) + "\n",
    )
    _write(
        base / ".techne" / "context" / "api.CONTEXT.md",
        """---
kind: context_doc
subsystem: api
paths: [src/api, tests]
tags: [auth, request, token]
related_tests: [tests/test_api.py]
refresh_policy: proposed
---

# API Context

## Purpose
Handles request authentication and token checks.

## Entry points
- src/api/handler.py
- tests/test_api.py
""",
    )
    _write(base / "src" / "api" / "handler.py", "def handle_request(token: str) -> bool:\n    return bool(token)\n")
    _write(base / "tests" / "test_api.py", "def test_smoke():\n    assert True\n")
    _write(base / "README.md", "sample repo\n")
    return base


def _run_script(script_name: str, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPTS_DIR / script_name), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_context_index_builds_and_assigns_subsystems() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = _make_workshop_repo(Path(tmp))
        result = _run_script("context_index.py", repo, "--json")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        mapped = {row["path"]: row.get("subsystem") for row in payload["files"]}
        assert mapped["src/api/handler.py"] == "api"
        assert mapped["tests/test_api.py"] == "api"
        generated = json.loads((repo / ".techne" / "generated" / "subsystem_map.json").read_text(encoding="utf-8"))
        assert generated["subsystem_map"]["src/api/handler.py"] == "api"


def test_context_search_ranks_matching_subsystem() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = _make_workshop_repo(Path(tmp))
        index_result = _run_script("context_index.py", repo)
        assert index_result.returncode == 0, index_result.stderr
        search_result = _run_script("context_search.py", repo, "request token auth", "--json")
        assert search_result.returncode == 0, search_result.stderr
        payload = json.loads(search_result.stdout)
        assert payload["subsystems"][0]["name"] == "api"
        assert payload["context_docs"][0]["path"] == ".techne/context/api.CONTEXT.md"


def test_refresh_generated_docs_writes_artifacts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = _make_workshop_repo(Path(tmp))
        result = _run_script(
            "refresh_generated_docs.py",
            repo,
            "--task",
            "task-123",
            "--files",
            "src/api/handler.py",
            ".techne/context/api.CONTEXT.md",
            "--json",
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["subsystems"] == ["api"]
        assert (repo / ".techne" / "generated" / "change_log.json").exists()
        assert (repo / ".techne" / "generated" / "stale_docs.json").exists()
        assert (repo / ".techne" / "tasks" / "task-123" / "refresh_context.json").exists()
        assert (repo / ".techne" / "memory" / "wikilinks.json").exists()
        assert (repo / ".techne" / "memory" / "wikilinks.md").exists()


def test_flat_policy_config_normalizes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = _make_workshop_repo(Path(tmp))
        paths = find_workshop_paths(repo)
        assert paths is not None
        config = load_workshop_config(paths)
        assert classify_policy(".techne/generated/context_index.json", config) == "generated"
        assert classify_policy(".techne/context/api.CONTEXT.md", config) == "proposed"
        assert classify_policy("README.md", config) == "manual"


def test_wikilink_graph_attaches_workshop_nodes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        context_index = {
            "project_name": "mini",
            "repo_root": tmp,
            "context_docs": [
                {
                    "path": ".techne/context/api.CONTEXT.md",
                    "subsystem": "api",
                    "tags": ["auth"],
                    "paths": ["src/api"],
                    "refresh_policy": "proposed",
                }
            ],
            "subsystems": [
                {
                    "name": "api",
                    "paths": ["src/api"],
                    "context_doc": ".techne/context/api.CONTEXT.md",
                    "tags": ["auth"],
                    "refresh_policy": "proposed",
                    "file_count": 1,
                }
            ],
            "files": [
                {"path": "src/api/handler.py", "subsystem": "api", "ext": ".py"}
            ],
        }
        index_path = Path(tmp) / "context_index.json"
        index_path.write_text(json.dumps(context_index), encoding="utf-8")
        with mock.patch.object(wikilink, "WORKSHOP_CONTEXT_INDEX", index_path):
            graph = wikilink.build_graph()
        assert graph["project"]["name"] == "mini"
        assert any(node["kind"] == "context_doc" for node in graph["nodes"])
        assert any(edge["type"] == "context_describes" for edge in graph["edges"])


if __name__ == "__main__":
    import traceback

    tests = [
        test_context_index_builds_and_assigns_subsystems,
        test_context_search_ranks_matching_subsystem,
        test_refresh_generated_docs_writes_artifacts,
        test_flat_policy_config_normalizes,
        test_wikilink_graph_attaches_workshop_nodes,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {test.__name__}: {e}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed}/{passed + failed} passed" + ("" if failed == 0 else f" ({failed} FAILED)"))
    print(f"{'='*60}")
    sys.exit(0 if failed == 0 else 1)
