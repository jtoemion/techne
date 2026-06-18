"""
test_react_vite.py — tests for the React + Vite framework skill (skills/react.md).

The skill was renamed react-vite → react (router id "react-rules"); this suite tracks
the real skill. Plain asserts so pytest is authoritative — no record-and-continue
helper that could hide a regression. Route cases avoid the "test"/"component" keywords
that legitimately route to tdd/nextjs instead.

Run:  python -X utf8 tests/test_react_vite.py   (delegates to pytest)
"""

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

from router import route

REACT_SKILL = ROOT / "skills" / "react.md"


def test_file_structure():
    assert REACT_SKILL.exists(), "skills/react.md must exist"
    assert len(REACT_SKILL.read_text(encoding="utf-8")) > 500, "react.md should have content"


def test_router_routes_react_tasks_to_react_rules():
    cases = [
        "fix this React useEffect with exhaustive-deps",
        "React Query mutation inside a hook",
        "Vite dev server issue with React hooks",
    ]
    for task in cases:
        r = route(task)
        got = r["id"] if r else None
        assert got == "react-rules", f"{task!r} routed to {got!r}, expected react-rules"


def test_nextjs_near_miss_still_routes_to_nextjs():
    cases = [
        "Next.js app router page component metadata export",
        "redirect from Next.js middleware",
        "server component layout in Next.js",
    ]
    for task in cases:
        r = route(task)
        got = r["id"] if r else None
        assert got == "nextjs-rules", f"{task!r} routed to {got!r}, expected nextjs-rules"


def test_format_next_steps_and_cap():
    text = REACT_SKILL.read_text(encoding="utf-8")
    assert "## Next Steps" in text, "react.md must chain via ## Next Steps"
    assert len(text.splitlines()) <= 100, "entry card must be <= 100 lines"


def test_frontmatter():
    text = REACT_SKILL.read_text(encoding="utf-8")
    head = text[:1200]
    assert text.startswith("---"), "must start with frontmatter"
    assert "name: react" in head
    assert "triggers:" in head
    # The card is React/Vite-specific and must distinguish itself from Next.js.
    assert "Next.js" in text, "react.md should call out the Next.js distinction"


def test_react_and_nextjs_distinctly_registered():
    yaml = (ROOT / "harness" / "skill-router.yaml").read_text(encoding="utf-8")
    assert 'id: "react-rules"' in yaml
    assert 'id: "nextjs-rules"' in yaml


if __name__ == "__main__":
    import pytest as _pt
    raise SystemExit(_pt.main([__file__, "-q"]))
