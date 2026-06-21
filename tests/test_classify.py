"""
test_classify.py — Unit tests for classify_task_group.

Run from tests/:  python test_classify.py
"""

from __future__ import annotations

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

from classify import classify_task_group
from task_db import Task

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []


def check(label: str, cond: bool) -> None:
    results.append(cond)
    print(f"  {PASS if cond else FAIL} {label}")


# ── Discipline-based grouping ─────────────────────────────────────────────


def test_same_discipline_same_group() -> None:
    """Two tasks with the same discipline produce the same group label."""
    t1 = Task(id="a", title="task a", discipline="implement")
    t2 = Task(id="b", title="task b", discipline="implement")
    g1 = classify_task_group(t1)
    g2 = classify_task_group(t2)
    check("same discipline → same group", g1 == g2)
    check("group equals discipline when no tags match", g1 == "implement")


def test_different_discipline_different_group() -> None:
    """Tasks with different disciplines produce different group labels."""
    t1 = Task(id="a", title="task a", discipline="implement")
    t2 = Task(id="b", title="task b", discipline="review")
    check("different discipline → different group",
          classify_task_group(t1) != classify_task_group(t2))


def test_all_disciplines_map() -> None:
    """Every valid discipline produces its own unrefined group label."""
    for disc in ("tdd", "implement", "review", "debug", "retro"):
        t = Task(id="x", title="test", discipline=disc)
        g = classify_task_group(t)
        check(f"discipline '{disc}' → '{disc}'", g == disc)


# ── Tag-based refinement ──────────────────────────────────────────────────


def test_tag_keyword_appends_suffix() -> None:
    """A tag matching a category keyword refines the group with a suffix."""
    t = Task(id="a", title="auth work", discipline="implement", tags=["auth"])
    g = classify_task_group(t)
    check("tag 'auth' refines to 'implement:auth'", g == "implement:auth")


def test_multiple_keywords_first_wins() -> None:
    """When multiple tags match keywords, the first one encountered wins."""
    t = Task(id="a", title="multi", discipline="implement",
             tags=["data", "api", "auth"])
    g = classify_task_group(t)
    check("first matching tag 'data' wins", g == "implement:data")


def test_non_keyword_tags_ignored() -> None:
    """Tags that don't match a category keyword leave the group unrefined."""
    t = Task(id="a", title="random", discipline="implement",
             tags=["refactor", "urgent", "bugfix"])
    g = classify_task_group(t)
    check("non-keyword tags ignored → just discipline", g == "implement")


def test_empty_tags_no_refinement() -> None:
    """An empty tags list produces the discipline-only group."""
    t = Task(id="a", title="empty tags", discipline="review", tags=[])
    g = classify_task_group(t)
    check("empty tags → 'review'", g == "review")


def test_all_category_keywords() -> None:
    """Each supported keyword refines correctly when used as the only tag."""
    for kw in ("auth", "ui", "api", "data", "infra"):
        t = Task(id="x", title=kw, discipline="implement", tags=[kw])
        g = classify_task_group(t)
        check(f"keyword '{kw}' → 'implement:{kw}'", g == f"implement:{kw}")


# ── Determinism ───────────────────────────────────────────────────────────


def test_deterministic() -> None:
    """Calling classify_task_group twice on the same task yields the same label."""
    t = Task(id="stable", title="deterministic test",
             discipline="debug", tags=["api", "auth"])
    first = classify_task_group(t)
    second = classify_task_group(t)
    check("deterministic: same task → same label", first == second)


# ── Edge cases ────────────────────────────────────────────────────────────


def test_case_insensitive_tag_matching() -> None:
    """Tags are matched case-insensitively (lowercased)."""
    t = Task(id="a", title="Auth", discipline="implement", tags=["Auth"])
    g = classify_task_group(t)
    check("case-insensitive tag 'Auth' → 'implement:auth'", g == "implement:auth")


def test_whitespace_stripped() -> None:
    """Tags with surrounding whitespace are still matched."""
    t = Task(id="a", title="whitespace", discipline="review", tags=["  auth  "])
    g = classify_task_group(t)
    check("whitespace-padded '  auth  ' → 'review:auth'", g == "review:auth")


# ── Runner ────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    print("=" * 60)
    print("CLASSIFY — classify_task_group unit tests")
    print("=" * 60)

    for name, fn in sorted({k: v for k, v in globals().items()
                            if k.startswith("test_")}.items()):
        print(f"\n[{name}]")
        fn()

    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed" +
          ("" if passed == total else f" ({total-passed} FAILED)"))
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
