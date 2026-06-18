"""
test_stack_detect.py — framework detection + stack-aware skill loading.

detect_stack() reads a project's package.json + config files and returns stack tags;
router.resolve_stack_skills() maps those to the framework pattern files to inject, and
stack_gated_paths() are the files the conductor fallback must NOT load unconditionally.
This is what keeps diagnose framework-aware without bloating unrelated codebases.

Run from tests/:  python test_stack_detect.py
"""

import json
import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

from stack_detect import detect_stack
import router

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []


def check(label, cond):
    results.append(bool(cond))
    print(f"  {PASS if cond else FAIL} {label}")


def _project(pkg: dict | None = None, files: list[str] | None = None) -> Path:
    """Make a temp project dir with an optional package.json + marker files."""
    d = Path(tempfile.mkdtemp(prefix="stack_"))
    if pkg is not None:
        (d / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    for name in files or []:
        (d / name).write_text("", encoding="utf-8")
    return d


def test_detects_nextjs_implies_react():
    print("\n[detect — Next.js project implies react]")
    d = _project({"dependencies": {"next": "14.0.0", "react": "18.0.0"}})
    tags = detect_stack(d)
    check("nextjs detected", "nextjs" in tags)
    check("react implied/detected", "react" in tags)


def test_detects_sveltekit_firestore_netlify():
    print("\n[detect — SvelteKit + Firestore + Netlify (the pastpapr/BnB stack)]")
    d = _project(
        {"dependencies": {"@sveltejs/kit": "2.0.0", "firebase": "10.0.0"},
         "devDependencies": {"typescript": "5.0.0"}},
        files=["netlify.toml", "svelte.config.js"],
    )
    tags = detect_stack(d)
    check("sveltekit detected", "sveltekit" in tags)
    check("svelte implied", "svelte" in tags)
    check("firestore detected", "firestore" in tags)
    check("netlify detected (netlify.toml)", "netlify" in tags)
    check("typescript detected", "typescript" in tags)


def test_config_files_without_deps():
    print("\n[detect — config-file markers alone]")
    d = _project(files=["next.config.mjs", "tsconfig.json", "firestore.rules"])
    tags = detect_stack(d)
    check("nextjs from next.config.*", "nextjs" in tags)
    check("typescript from tsconfig.json", "typescript" in tags)
    check("firestore from firestore.rules", "firestore" in tags)


def test_pure_python_repo_detects_nothing():
    print("\n[detect — no package.json, no JS config → empty (e.g. Techne itself)]")
    d = _project(files=["pyproject.toml", "main.py"])
    tags = detect_stack(d)
    check("no framework tags on a python repo", tags == set())


def test_no_substring_false_positives():
    print("\n[detect — token-boundary match, not bare substring]")
    d = _project({"dependencies": {"preact": "10", "vitest": "2", "context-menu": "1"}})
    tags = detect_stack(d)
    check("preact does NOT tag react", "react" not in tags)
    check("context-menu does NOT tag nextjs", "nextjs" not in tags)
    # scoped + prefixed real packages STILL resolve
    d2 = _project({"dependencies": {"@netlify/functions": "2", "react-dom": "18"}})
    tags2 = detect_stack(d2)
    check("@netlify/functions tags netlify", "netlify" in tags2)
    check("react-dom tags react", "react" in tags2)


def test_malformed_package_json_is_safe():
    print("\n[detect — malformed package.json doesn't crash]")
    d = Path(tempfile.mkdtemp(prefix="stack_bad_"))
    (d / "package.json").write_text("{ not json", encoding="utf-8")
    tags = detect_stack(d)
    check("malformed manifest → empty set, no raise", tags == set())


def test_resolver_maps_tags_to_skill_files():
    print("\n[resolve_stack_skills — detected stack → framework pattern files]")
    d = _project({"dependencies": {"@sveltejs/kit": "2.0.0", "firebase": "10.0.0"}},
                 files=["netlify.toml"])
    paths = router.resolve_stack_skills(d)
    check("svelte.md resolved", "skills/svelte.md" in paths)
    check("firestore diagnose resolved", "skills/diagnose/firestore.md" in paths)
    check("netlify diagnose resolved", "skills/diagnose/netlify.md" in paths)
    check("nextjs.md NOT resolved (wrong stack)", "skills/nextjs.md" not in paths)
    check("no duplicate paths", len(paths) == len(set(paths)))


def test_python_repo_resolves_no_framework_files():
    print("\n[resolve_stack_skills — python repo gets no framework files]")
    d = _project(files=["pyproject.toml"])
    check("empty resolution on no-framework repo", router.resolve_stack_skills(d) == [])


def test_stack_gated_paths_cover_framework_files():
    print("\n[stack_gated_paths — framework files are gated out of the fallback]")
    gated = router.stack_gated_paths()
    check("svelte.md is gated", "skills/svelte.md" in gated)
    check("nextjs.md is gated", "skills/nextjs.md" in gated)
    check("typescript.md is gated", "skills/typescript.md" in gated)
    check("firestore diagnose is gated", "skills/diagnose/firestore.md" in gated)
    # The whole point: these must NOT be in the always-loaded globals.
    check("framework files are NOT in always_loaded",
          not (set(router.get_always_loaded()) & gated))


if __name__ == "__main__":
    print("=" * 60)
    print("STACK DETECT + STACK-AWARE LOADING — TEST")
    print("=" * 60)
    test_detects_nextjs_implies_react()
    test_detects_sveltekit_firestore_netlify()
    test_config_files_without_deps()
    test_no_substring_false_positives()
    test_pure_python_repo_detects_nothing()
    test_malformed_package_json_is_safe()
    test_resolver_maps_tags_to_skill_files()
    test_python_repo_resolves_no_framework_files()
    test_stack_gated_paths_cover_framework_files()
    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed" + ("  -- all clear" if passed == total else f"  ({total-passed} FAILED)"))
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
