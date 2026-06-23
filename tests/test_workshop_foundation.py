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
from task_db import TaskDB  # noqa: E402
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
        tmp_path = Path(tmp)

        # Write fixture context_index with a "harness" subsystem
        context_index = {
            "project_name": "mini",
            "repo_root": tmp,
            "context_docs": [
                {
                    "path": ".techne/context/harness.CONTEXT.md",
                    "subsystem": "harness",
                    "tags": ["pipeline", "gates"],
                    "paths": ["harness"],
                    "refresh_policy": "proposed",
                }
            ],
            "subsystems": [
                {
                    "name": "harness",
                    "paths": ["harness"],
                    "context_doc": ".techne/context/harness.CONTEXT.md",
                    "tags": ["pipeline", "gates"],
                    "refresh_policy": "proposed",
                    "file_count": 42,
                }
            ],
            "files": [
                {"path": "harness/wikilink.py", "subsystem": "harness", "ext": ".py"}
            ],
        }
        # Create a temp project with the right .techne/ structure
        proj_root = tmp_path / "mini"
        techne_memory = proj_root / ".techne" / "memory"
        techne_memory.mkdir(parents=True, exist_ok=True)
        techne_generated = proj_root / ".techne" / "generated"
        techne_generated.mkdir(parents=True, exist_ok=True)

        # Write context_index.json under .techne/generated/
        index_path = techne_generated / "context_index.json"
        index_path.write_text(json.dumps(context_index), encoding="utf-8")

        # Write mistakes.md under .techne/memory/
        mistakes_content = (
            "## [2026-06-20T00:00:00Z] IMPLEMENT | AUTO-LOGGED\n"
            "**Error**     : Intent gate: MISMATCH\n"
            "**Cause**     : Something went wrong\n"
            "**Lesson**    : Always check intent\n"
            "**Gate**      : intent\n"
            "**Status**    : ACTIVE\n"
        )
        mistakes_path = techne_memory / "mistakes.md"
        mistakes_path.write_text(mistakes_content, encoding="utf-8")

        # Write empty ledger.md
        ledger_path = techne_memory / "ledger.md"
        ledger_path.write_text("# LEDGER\n", encoding="utf-8")

        # ── Seed a temporary task_db with DONE tasks ──
        task_db_path = techne_memory / "tasks.db"
        db = TaskDB(str(task_db_path))
        t1 = db.create_task("add wikilink graph v2", discipline="tdd",
                            tags=["wikilink", "graph", "harness"])
        db.start_task(t1.id, agent="implementer")
        db.complete_task(t1.id, agent="implementer", summary="task nodes + edges",
                         changed_files=["harness/wikilink.py"], diff_summary="+87 -3")
        db.review_task(t1.id, agent="reviewer", verdict="PASS", findings="clean")
        db.verify_task(t1.id, agent="verifier", test_output_hash="abc123")
        db.done_task(t1.id)

        t2 = db.create_task("add rate limiter", discipline="implement",
                            tags=["rate-limit", "middleware"])
        db.start_task(t2.id, agent="implementer")
        db.complete_task(t2.id, agent="implementer", summary="token bucket",
                         changed_files=["src/middleware/rate.py", "tests/test_rate.py"],
                         diff_summary="+42 -0")
        db.review_task(t2.id, agent="reviewer", verdict="PASS", findings="ok")
        db.verify_task(t2.id, agent="verifier", test_output_hash="def456")
        db.done_task(t2.id)

        # An IN_PROGRESS task should NOT get a node
        t3 = db.create_task("incomplete work", discipline="tdd")
        db.start_task(t3.id, agent="implementer")
        # intentionally NOT done
        db.close()

        # No mocks needed — build_graph(root=) reads from the passed root
        graph = wikilink.build_graph(root=proj_root)

        # ── structural graph assertions (unchanged) ──
        assert graph["project"]["name"] == "mini"
        assert any(node["kind"] == "context_doc" for node in graph["nodes"])
        assert any(edge["type"] == "context_describes" for edge in graph["edges"])

        # ── entry-edge assertions (new for A3) ──
        assert len(graph["entries"]) == 1
        entry = graph["entries"][0]
        assert entry["kind"] == "MISTAKE"
        assert entry["gate"] == "intent"
        # The heuristic maps gate="intent" → subsystem:harness
        assert any(
            e["from"] == entry["slug"]
            and e["type"] == "mistake_applies_to"
            and e["to"] == "subsystem:harness"
            for e in graph["edges"]
        ), (
            f"Expected a 'mistake_applies_to' edge from entry "
            f"slug={entry['slug']!r} to 'subsystem:harness', "
            f"but edges={graph['edges']}"
        )

        # ── task-node assertions (new for A4) ──
        task_nodes = [n for n in graph["nodes"] if n["kind"] == "task"]
        assert len(task_nodes) == 2, (
            f"Expected 2 task nodes (DONE), got {len(task_nodes)}: {task_nodes}"
        )
        assert task_nodes[0]["slug"].startswith("task:")
        assert task_nodes[0]["metadata"]["status"] == "DONE"
        assert task_nodes[1]["slug"].startswith("task:")
        assert task_nodes[1]["metadata"]["status"] == "DONE"

        # Task→file edges (task_touched)
        touched_edges = [
            e for e in graph["edges"]
            if e["type"] == "task_touched" and e["source"] == "task_db"
        ]
        assert len(touched_edges) >= 2, (
            f"Expected at least 2 task_touched edges, got {len(touched_edges)}"
        )
        assert any(e["to"] == "file:harness/wikilink.py" for e in touched_edges)
        assert any(e["to"] == "file:src/middleware/rate.py" for e in touched_edges)

        # Task→entry edges (task_triggered)
        triggered_edges = [
            e for e in graph["edges"]
            if e["type"] == "task_triggered" and e["source"] == "task_db"
        ]
        # t1 has tag "harness" which should match entry fields (no direct match since
        # the entry has gate="intent", phase="IMPLEMENT", skill="none")
        # But t1 also has tag "graph" — no match. Task t2 has "middleware" — no match.
        # Still check the structure is sound
        for te in triggered_edges:
            assert te["from"].startswith("task:")
            assert te["to"].startswith("2026-")  # entry slug pattern


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
