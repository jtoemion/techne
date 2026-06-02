"""
test_persona_brainstorm.py — tests for the persona-brainstorm skill family.

Verifies: file structure, router integration, sub-skill chain integrity,
format compliance (compact, has Next Steps), integration with CONTEXT.md
and docs/adr/ ecosystem.

Run from tests/:
    python test_persona_brainstorm.py
"""

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

from router import route, _load_router

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results: list[tuple[str, bool, str]] = []


def ok(label: str):
    results.append((label, True, ""))
    print(f"  {PASS} {label}")


def fail(label: str, reason: str = ""):
    results.append((label, False, reason))
    print(f"  {FAIL} {label} -- {reason}")


# ─── File structure ──────────────────────────────────────────────────────────

def test_file_structure():
    print("\n[file structure]")

    expected = {
        "skills/persona-brainstorm.md":          "entry router",
        "skills/persona-brainstorm/personas.md": "persona definitions",
        "skills/persona-brainstorm/loop.md":     "loop mechanics",
        "skills/persona-brainstorm/adr.md":      "ADR template",
    }

    for rel_path, label in expected.items():
        path = ROOT / rel_path
        if path.exists():
            content = path.read_text(encoding="utf-8")
            if len(content) > 200:
                ok(f"{rel_path} ({label})")
            else:
                fail(f"{rel_path} ({label})", f"only {len(content)} chars")
        else:
            fail(f"{rel_path} ({label})", "missing")


# ─── Router integration ──────────────────────────────────────────────────────

def test_router_integration():
    print("\n[router integration]")

    cases = [
        ("let's run a persona brainstorm", "persona-brainstorm"),
        ("Ezekiel and Jeremiah dialogue", "persona-brainstorm"),
        ("client dev dialogue to discover improvement", "persona-brainstorm"),
        ("grill session for the new feature", "persona-brainstorm"),  # contains 'grill session'
    ]

    for task, expected_id in cases:
        r = route(task)
        if r and r["id"] == expected_id:
            ok(f"'{task[:40]}...' → {expected_id}")
        else:
            got = r["id"] if r else "None"
            fail(f"'{task[:40]}...' → {expected_id}", f"got {got}")


def test_disambiguation_registered():
    print("\n[disambiguation registered]")

    router = _load_router()
    disambig = router.get("disambiguation", [])

    pairs = [set(entry.get("confused", [])) for entry in disambig]

    if {"grill", "persona-brainstorm"} in pairs:
        ok("grill vs persona-brainstorm disambiguation registered")
    else:
        fail("grill vs persona-brainstorm disambiguation", str(pairs))


# ─── Compact format compliance ───────────────────────────────────────────────

def test_compact_format():
    """All persona-brainstorm files should be reference cards, not essays."""
    print("\n[compact format]")

    files = [
        ROOT / "skills" / "persona-brainstorm.md",
        ROOT / "skills" / "persona-brainstorm" / "personas.md",
        ROOT / "skills" / "persona-brainstorm" / "loop.md",
        ROOT / "skills" / "persona-brainstorm" / "adr.md",
    ]

    for f in files:
        if not f.exists():
            fail(f"{f.name} exists", "missing")
            continue
        text = f.read_text(encoding="utf-8")
        lines = text.splitlines()

        # Entry card should stay under 100 lines (router + summary)
        # Sub-skills can be longer but should still be compact (<150)
        max_lines = 100 if f.name == "persona-brainstorm.md" else 150
        if len(lines) <= max_lines:
            ok(f"{f.name}: {len(lines)} lines (≤{max_lines})")
        else:
            fail(f"{f.name}: {len(lines)} lines", f"exceeds {max_lines}")


def test_next_steps_chain():
    """Every file in the chain must have a Next Steps section."""
    print("\n[Next Steps chain]")

    files = [
        ROOT / "skills" / "persona-brainstorm.md",
        ROOT / "skills" / "persona-brainstorm" / "personas.md",
        ROOT / "skills" / "persona-brainstorm" / "loop.md",
        ROOT / "skills" / "persona-brainstorm" / "adr.md",
    ]

    for f in files:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        if "## Next Steps" in text:
            ok(f"{f.name} has Next Steps section")
        else:
            fail(f"{f.name} has Next Steps section")


def test_frontmatter():
    """Every file needs YAML frontmatter with name + description."""
    print("\n[frontmatter]")

    files = [
        ROOT / "skills" / "persona-brainstorm.md",
        ROOT / "skills" / "persona-brainstorm" / "personas.md",
        ROOT / "skills" / "persona-brainstorm" / "loop.md",
        ROOT / "skills" / "persona-brainstorm" / "adr.md",
    ]

    for f in files:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        if text.startswith("---") and "name:" in text[:300] and "description:" in text[:600]:
            ok(f"{f.name} has valid frontmatter")
        else:
            fail(f"{f.name} frontmatter", text[:200])


# ─── Ecosystem integration ───────────────────────────────────────────────────

def test_integrates_with_context_md():
    """The skill should reference CONTEXT.md (where Megumi writes)."""
    print("\n[CONTEXT.md integration]")

    entry = (ROOT / "skills" / "persona-brainstorm.md").read_text(encoding="utf-8")
    if "CONTEXT.md" in entry:
        ok("entry card references CONTEXT.md")
    else:
        fail("entry card references CONTEXT.md")

    loop = (ROOT / "skills" / "persona-brainstorm" / "loop.md").read_text(encoding="utf-8")
    if "CONTEXT.md" in loop and "G-Q" in loop:
        ok("loop card references CONTEXT.md with G-Q format")
    else:
        fail("loop card G-Q + CONTEXT.md")


def test_integrates_with_adr_format():
    """ADR sub-skill should reference docs/adr/ and the base ADR-FORMAT.md."""
    print("\n[docs/adr/ integration]")

    adr_skill = (ROOT / "skills" / "persona-brainstorm" / "adr.md").read_text(encoding="utf-8")
    if "docs/adr/" in adr_skill:
        ok("ADR sub-skill references docs/adr/")
    else:
        fail("ADR sub-skill references docs/adr/")

    if "ADR-FORMAT.md" in adr_skill:
        ok("ADR sub-skill references base ADR-FORMAT.md")
    else:
        fail("ADR sub-skill references ADR-FORMAT.md")

    base_format = ROOT / "docs" / "adr" / "ADR-FORMAT.md"
    if base_format.exists():
        ok("base docs/adr/ADR-FORMAT.md exists")
    else:
        fail("base ADR-FORMAT.md exists")


def test_session_handoff_aware():
    """Entry card should mention SESSION.md for multi-agent handoff."""
    print("\n[SESSION.md awareness]")

    entry = (ROOT / "skills" / "persona-brainstorm.md").read_text(encoding="utf-8")
    if "SESSION.md" in entry:
        ok("entry card references SESSION.md for handoff")
    else:
        fail("entry card references SESSION.md")


# ─── Persona rule consistency ────────────────────────────────────────────────

def test_persona_rules():
    """The four hard rules from the original skill must survive the rework."""
    print("\n[persona rules preserved]")

    all_text = (
        (ROOT / "skills" / "persona-brainstorm.md").read_text(encoding="utf-8")
        + (ROOT / "skills" / "persona-brainstorm" / "personas.md").read_text(encoding="utf-8")
        + (ROOT / "skills" / "persona-brainstorm" / "loop.md").read_text(encoding="utf-8")
        + (ROOT / "skills" / "persona-brainstorm" / "adr.md").read_text(encoding="utf-8")
    )

    rules = [
        ("Judah is not Jeremiah", ["Judah is NOT Jeremiah", "Judah is not Jeremiah", "NOT Jeremiah"]),
        ("Cap at 3 ADRs",         ["3 ADRs", "three ADRs", "3 finished"]),
        ("One question at a time", ["ONE question", "One question at a time", "one at a time"]),
        ("Auto-loop default",      ["Auto-loop", "auto-loop"]),
        ("Temp-KB regenerated",    ["regenerated every session", "regenerated", "never cache"]),
        ("Friction not aspiration", ["friction, not aspiration", "from friction", "not aspirational"]),
    ]

    for rule_name, variants in rules:
        if any(v.lower() in all_text.lower() for v in variants):
            ok(f"rule preserved: {rule_name}")
        else:
            fail(f"rule preserved: {rule_name}", "not found in any skill file")


# ─── Run all ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 64)
    print("PERSONA-BRAINSTORM SKILL — STRESS TEST")
    print("=" * 64)

    test_file_structure()
    test_router_integration()
    test_disambiguation_registered()
    test_compact_format()
    test_next_steps_chain()
    test_frontmatter()
    test_integrates_with_context_md()
    test_integrates_with_adr_format()
    test_session_handoff_aware()
    test_persona_rules()

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
