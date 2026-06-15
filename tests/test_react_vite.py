"""
test_react_vite.py - tests for the React + Vite framework skill.

Run from tests/:
    python test_react_vite.py
"""

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

from router import route

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results: list[tuple[str, bool, str]] = []


def ok(label: str):
    results.append((label, True, ""))
    print(f"  {PASS} {label}")


def fail(label: str, reason: str = ""):
    results.append((label, False, reason))
    print(f"  {FAIL} {label} -- {reason}")


def test_file_structure():
    print("\n[file structure]")
    path = ROOT / "skills" / "react-vite.md"
    if not path.exists():
        fail("skills/react-vite.md exists", "missing")
        return
    text = path.read_text(encoding="utf-8")
    if len(text) > 500:
        ok("skills/react-vite.md has content")
    else:
        fail("skills/react-vite.md has content", f"only {len(text)} chars")


def test_router():
    print("\n[router]")
    cases = [
        ("fix this React hook in our Vite app", "react-vite"),
        ("the Vite build fails after adding a component", "react-vite"),
        ("Vitest jsdom test for a React component", "react-vite"),
        ("TanStack Query mutation inside a React hook", "react-vite"),
        ("Tailwind Vite styling issue in the React app", "react-vite"),
    ]
    for task, expected_id in cases:
        r = route(task)
        got = r["id"] if r else "None"
        if got == expected_id:
            ok(f"'{task[:45]}...' -> {expected_id}")
        else:
            fail(f"'{task[:45]}...' -> {expected_id}", f"got {got}")


def test_nextjs_near_miss():
    print("\n[near miss]")
    cases = [
        ("Next.js app router page component metadata export", "nextjs-rules"),
        ("redirect from Next.js middleware", "nextjs-rules"),
        ("server component layout in Next.js", "nextjs-rules"),
    ]
    for task, expected_id in cases:
        r = route(task)
        got = r["id"] if r else "None"
        if got == expected_id:
            ok(f"'{task[:45]}...' -> {expected_id}")
        else:
            fail(f"'{task[:45]}...' -> {expected_id}", f"got {got}")


def test_next_steps_and_gotchas():
    print("\n[format]")
    text = (ROOT / "skills" / "react-vite.md").read_text(encoding="utf-8")
    if "## Gotchas" in text:
        ok("has Gotchas")
    else:
        fail("has Gotchas")
    if "## Next Steps" in text:
        ok("has Next Steps")
    else:
        fail("has Next Steps")
    if len(text.splitlines()) <= 100:
        ok("entry card <= 100 lines")
    else:
        fail("entry card <= 100 lines", f"{len(text.splitlines())} lines")


def test_frontmatter():
    print("\n[frontmatter]")
    text = (ROOT / "skills" / "react-vite.md").read_text(encoding="utf-8")
    head = text[:1200]
    checks = [
        ("starts with frontmatter", text.startswith("---")),
        ("has name", "name: react-vite" in head),
        ("has use-when description", "description: >" in head and "Use when" in head),
        ("has triggers", "triggers:" in head),
        ("excludes Next.js", "Not for Next.js" in head),
    ]
    for label, passed in checks:
        ok(label) if passed else fail(label)


def test_disambiguation_registered():
    print("\n[disambiguation]")
    text = (ROOT / "harness" / "skill-router.yaml").read_text(encoding="utf-8")
    if "- react-vite" in text and "- nextjs-rules" in text:
        ok("react-vite vs nextjs-rules registered")
    else:
        fail("react-vite vs nextjs-rules registered")


if __name__ == "__main__":
    print("=" * 64)
    print("REACT-VITE SKILL - STRESS TEST")
    print("=" * 64)

    test_file_structure()
    test_router()
    test_nextjs_near_miss()
    test_next_steps_and_gotchas()
    test_frontmatter()
    test_disambiguation_registered()

    total = len(results)
    passed = sum(1 for _, ok_flag, _ in results if ok_flag)
    failed = total - passed

    print("\n" + "=" * 64)
    print(f"RESULTS: {passed}/{total} passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
        for label, ok_flag, reason in results:
            if not ok_flag:
                print(f"  {FAIL} {label}: {reason}")
    else:
        print("  -- all clear")
    print("=" * 64)

    sys.exit(0 if failed == 0 else 1)
