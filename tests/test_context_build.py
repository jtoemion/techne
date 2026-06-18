"""
test_context_build.py — deterministic context-pack generation (amortization, no model).

build_context derives the base .techne/context pack from a repo with no model call. These
tests run against TEMP repos and monkeypatch the module's CONTEXT_DIR so the real
.techne/context is never touched.

Run from tests/:  python test_context_build.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

import context_build as cb
import context_preflight as cp

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []


def check(label, cond):
    results.append(bool(cond))
    print(f"  {PASS if cond else FAIL} {label}")


def _sandbox(pkg: dict | None = None, files: dict[str, str] | None = None):
    """A temp project + a temp .techne/context dir wired into both modules."""
    proj = Path(tempfile.mkdtemp(prefix="ctx_proj_"))
    ctxdir = Path(tempfile.mkdtemp(prefix="ctx_out_")) / "context"
    # Redirect where context files + hash are written (both modules share the constant).
    cb.CONTEXT_DIR = ctxdir
    cp.CONTEXT_DIR = ctxdir
    cp.PACKS_DIR = ctxdir / "context_packs"
    if pkg is not None:
        (proj / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    for name, content in (files or {}).items():
        (proj / name).write_text(content, encoding="utf-8")
    return proj, ctxdir


def test_build_creates_base_pack():
    print("\n[build — base pack files are generated]")
    proj, ctxdir = _sandbox(
        pkg={"scripts": {"test": "vitest", "build": "vite build"},
             "dependencies": {"@sveltejs/kit": "2", "firebase": "10"}},
        files={"README.md": "# Pastpapr\n\nExam prep app.\n"},
    )
    rep = cb.build_context(proj, force=True)
    for name in ("project_digest.md", "file_roles.md", "commands.md", "risk_boundaries.md"):
        check(f"{name} written", (ctxdir / name).exists() and name in rep["written"])
    check("hash returned", bool(rep["hash"]))


def test_digest_reflects_stack_and_readme():
    print("\n[digest — detected stack + README lead surface]")
    proj, ctxdir = _sandbox(
        pkg={"dependencies": {"@sveltejs/kit": "2", "firebase": "10"}},
        files={"README.md": "# Pastpapr\n\nExam prep app.\n", "netlify.toml": ""},
    )
    cb.build_context(proj, force=True)
    digest = (ctxdir / "project_digest.md").read_text(encoding="utf-8")
    check("stack tag present (sveltekit)", "sveltekit" in digest)
    check("firestore detected", "firestore" in digest)
    check("README lead included", "Exam prep app" in digest)
    risk = (ctxdir / "risk_boundaries.md").read_text(encoding="utf-8")
    check("netlify flagged as deployment risk", "deployment" in risk)


def test_commands_detected_from_manifest():
    print("\n[commands — detected from package.json + python]")
    proj, ctxdir = _sandbox(pkg={"scripts": {"test": "jest", "lint": "eslint ."}})
    cb.build_context(proj, force=True)
    cmds = (ctxdir / "commands.md").read_text(encoding="utf-8")
    check("npm test detected", "npm run test" in cmds)
    check("npm lint detected", "npm run lint" in cmds)

    proj2, ctxdir2 = _sandbox(files={"pyproject.toml": "[project]\nname='x'\n"})
    cb.build_context(proj2, force=True)
    cmds2 = (ctxdir2 / "commands.md").read_text(encoding="utf-8")
    check("python pytest detected", "pytest" in cmds2)


def test_non_destructive_preserves_existing():
    print("\n[non-destructive — existing base file is preserved without force]")
    proj, ctxdir = _sandbox(pkg={"scripts": {"test": "vitest"}})
    ctxdir.mkdir(parents=True, exist_ok=True)
    (ctxdir / "project_digest.md").write_text("HAND-WRITTEN, do not clobber", encoding="utf-8")
    rep = cb.build_context(proj, force=False)
    digest = (ctxdir / "project_digest.md").read_text(encoding="utf-8")
    check("existing digest preserved", digest == "HAND-WRITTEN, do not clobber")
    check("it was skipped, not written", "project_digest.md" in rep["skipped"])
    check("other missing files still generated", "commands.md" in rep["written"])


def test_ensure_is_idempotent_when_fresh():
    print("\n[ensure_context — builds when stale, skips when fresh]")
    proj, ctxdir = _sandbox(pkg={"scripts": {"test": "vitest"}})
    first = cb.ensure_context(proj, force=True)
    check("first run builds", first["ran"] is True)
    second = cb.ensure_context(proj)
    check("second run skips (fresh)", second["ran"] is False and second["reason"] == "fresh")


def test_digest_indexes_docs_tree():
    print("\n[recall — canonical docs/ tree is indexed in the digest]")
    proj, ctxdir = _sandbox(pkg={"scripts": {"test": "vitest"}})
    (proj / "docs").mkdir()
    (proj / "docs" / "ARCHITECTURE.md").write_text("# Arch\n", encoding="utf-8")
    (proj / "docs" / "adr").mkdir()
    (proj / "docs" / "adr" / "0001-use-convex.md").write_text("# ADR\n", encoding="utf-8")
    cb.build_context(proj, force=True)
    digest = (ctxdir / "project_digest.md").read_text(encoding="utf-8")
    check("ARCHITECTURE.md indexed", "docs/ARCHITECTURE.md" in digest)
    check("adr indexed", "docs/adr/0001-use-convex.md" in digest)
    check("HOT recall/conclude wording present", "kept HOT" in digest)


def test_conclude_refreshes_derived_preserves_policy():
    print("\n[conclude — regenerates derived summary, preserves risk policy + docs/]")
    proj, ctxdir = _sandbox(pkg={"scripts": {"test": "vitest"}},
                            files={"README.md": "# App\n\nv1.\n"})
    cb.build_context(proj, force=True)
    # Human edits the policy file; the prose docs live in docs/ (untouched by conclude).
    (ctxdir / "risk_boundaries.md").write_text("HUMAN POLICY — keep", encoding="utf-8")
    # Repo changes (a new command appears), then we conclude.
    (proj / "package.json").write_text('{"scripts": {"test": "vitest", "lint": "eslint"}}',
                                       encoding="utf-8")
    rep = cb.conclude_context(proj)
    check("derived files refreshed", "commands.md" in rep["refreshed"])
    cmds = (ctxdir / "commands.md").read_text(encoding="utf-8")
    check("conclude picked up the new lint command", "npm run lint" in cmds)
    check("human risk policy preserved (not clobbered)",
          (ctxdir / "risk_boundaries.md").read_text(encoding="utf-8") == "HUMAN POLICY — keep")
    check("hash bumped (pack stays hot)", bool(rep["hash"]))


if __name__ == "__main__":
    print("=" * 60)
    print("CONTEXT BUILD — deterministic amortized pack (no model)")
    print("=" * 60)
    test_build_creates_base_pack()
    test_digest_reflects_stack_and_readme()
    test_commands_detected_from_manifest()
    test_non_destructive_preserves_existing()
    test_ensure_is_idempotent_when_fresh()
    test_digest_indexes_docs_tree()
    test_conclude_refreshes_derived_preserves_policy()
    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed" + ("  -- all clear" if passed == total else f"  ({total-passed} FAILED)"))
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
