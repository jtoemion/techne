"""
test_writing_skill.py — tests for the writing-skill system.

Verifies: file structure, router integration, compact format,
Next Steps chains, ecosystem references, checklist completeness,
and that the template covers all skill types.

Run from tests/:
    python test_writing_skill.py
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


# ─── File structure ──────────────────────────────────────────────────────────

def test_file_structure():
    print("\n[file structure]")

    files = {
        "skills/writing-skill.md":               "entry card",
        "skills/writing-skill/template.md":       "copy-paste scaffold",
        "skills/writing-skill/checklist.md":      "pre-publish review",
    }

    for rel, label in files.items():
        path = ROOT / rel
        if path.exists() and len(path.read_text(encoding="utf-8")) > 200:
            ok(f"{rel} ({label})")
        else:
            fail(f"{rel} ({label})", "missing or empty")


# ─── Router integration ──────────────────────────────────────────────────────

def test_router():
    print("\n[router integration]")

    cases = [
        ("I need to write a skill for deployment",   "writing-skill"),
        ("create a new skill that follows techne",   "writing-skill"),
        ("skill template for a new workflow",        "writing-skill"),
        ("audit this skill for compliance",          "writing-skill"),
        ("refactor the diagnose skill",              "writing-skill"),
    ]

    for task, expected in cases:
        r = route(task)
        if r and r["id"] == expected:
            ok(f"'{task[:45]}' → {expected}")
        else:
            got = r["id"] if r else "None"
            fail(f"'{task[:45]}' → {expected}", f"got {got}")


# ─── Newspaper test ──────────────────────────────────────────────────────────

def test_newspaper_rule():
    """First 10 lines of every file should answer: what + when + critical rule."""
    print("\n[newspaper rule — first 10 lines tell the story]")

    files = [
        ROOT / "skills" / "writing-skill.md",
        ROOT / "skills" / "writing-skill" / "template.md",
        ROOT / "skills" / "writing-skill" / "checklist.md",
    ]

    for f in files:
        if not f.exists():
            fail(f"{f.name} exists")
            continue

        text = f.read_text(encoding="utf-8")
        first_ten = "\n".join(text.splitlines()[:12])

        # Must have name + description in frontmatter
        if "name:" in first_ten and "description:" in first_ten:
            ok(f"{f.name}: frontmatter in first 10 lines")
        else:
            fail(f"{f.name}: frontmatter in first 10 lines", first_ten[:200])


# ─── Compact format ──────────────────────────────────────────────────────────

def test_compact():
    print("\n[compact format]")

    limits = {
        "skills/writing-skill.md":               100,
        "skills/writing-skill/template.md":       200,  # template has embedded scaffolds
        "skills/writing-skill/checklist.md":      150,
    }

    for rel, max_lines in limits.items():
        path = ROOT / rel
        if not path.exists():
            fail(f"{rel} exists")
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= max_lines:
            ok(f"{rel}: {len(lines)} lines (≤{max_lines})")
        else:
            fail(f"{rel}: {len(lines)} lines", f"exceeds {max_lines}")


# ─── Next Steps chain ────────────────────────────────────────────────────────

def test_next_steps_chain():
    print("\n[Next Steps chain — every file must have one]")

    files = [
        ROOT / "skills" / "writing-skill.md",
        ROOT / "skills" / "writing-skill" / "template.md",
        ROOT / "skills" / "writing-skill" / "checklist.md",
    ]

    for f in files:
        if not f.exists():
            continue
        if "## Next Steps" in f.read_text(encoding="utf-8"):
            ok(f"{f.name} has ## Next Steps")
        else:
            fail(f"{f.name} has ## Next Steps")


def test_chain_integrity():
    """Sub-skills should chain back to entry or forward to other sub-skills."""
    print("\n[chain integrity — sub-skills reference each other]")

    template = (ROOT / "skills" / "writing-skill" / "template.md").read_text(encoding="utf-8")
    checklist = (ROOT / "skills" / "writing-skill" / "checklist.md").read_text(encoding="utf-8")
    entry = (ROOT / "skills" / "writing-skill.md").read_text(encoding="utf-8")

    # Template chains to checklist
    if "checklist.md" in template:
        ok("template → checklist (forward chain)")
    else:
        fail("template → checklist")

    # Checklist chains to template
    if "template.md" in checklist:
        ok("checklist → template (back chain)")
    else:
        fail("checklist → template")

    # Entry chains to both sub-skills
    if "template.md" in entry and "checklist.md" in entry:
        ok("entry → template + checklist")
    else:
        fail("entry → both sub-skills", "missing one or both")


# ─── Ecosystem references ────────────────────────────────────────────────────

def test_ecosystem_references():
    print("\n[ecosystem integration references]")

    entry = (ROOT / "skills" / "writing-skill.md").read_text(encoding="utf-8")
    checklist = (ROOT / "skills" / "writing-skill" / "checklist.md").read_text(encoding="utf-8")
    template = (ROOT / "skills" / "writing-skill" / "template.md").read_text(encoding="utf-8")

    checks = [
        (entry,     "skill-router.yaml",  "entry references router"),
        (entry,     "CONTEXT.md",         "entry references CONTEXT.md"),
        (entry,     "docs/adr/",          "entry references ADR"),
        (entry,     "SESSION.md",         "entry references session"),
        (entry,     "harness/gates.py",   "entry references gates"),
        (checklist, "gates.py",           "checklist references gates.py"),
        (checklist, "skill-router.yaml",  "checklist references router"),
        (template,  "skill-router.yaml",  "template has router entry scaffold"),
        (template,  "tests/test_",        "template has test file scaffold"),
    ]

    for text, needle, label in checks:
        if needle in text:
            ok(label)
        else:
            fail(label, f"'{needle}' not found")


# ─── Newspaper logic documented ──────────────────────────────────────────────

def test_newspaper_logic_present():
    print("\n[newspaper logic documented]")

    entry = (ROOT / "skills" / "writing-skill.md").read_text(encoding="utf-8")

    terms = ["inverted pyramid", "HEADLINE", "LEAD", "TAIL", "Newspaper"]
    found = [t for t in terms if t in entry]

    if len(found) >= 3:
        ok(f"newspaper logic documented ({len(found)}/{len(terms)} terms found)")
    else:
        fail("newspaper logic documented", f"only found: {found}")


# ─── Template covers all skill types ─────────────────────────────────────────

def test_template_coverage():
    print("\n[template covers all skill types]")

    template = (ROOT / "skills" / "writing-skill" / "template.md").read_text(encoding="utf-8")

    types = [
        ("Entry Card",    "Entry Card"),
        ("Sub-Skill",     "Sub-Skill"),
        ("Rule File",     "Rule File"),
        ("Router Entry",  "Router Entry"),
        ("Test File",     "Test File"),
    ]

    for label, marker in types:
        if marker in template:
            ok(f"template has {label} scaffold")
        else:
            fail(f"template has {label} scaffold")


# ─── Checklist is complete ───────────────────────────────────────────────────

def test_checklist_completeness():
    print("\n[checklist completeness]")

    checklist = (ROOT / "skills" / "writing-skill" / "checklist.md").read_text(encoding="utf-8")

    required_sections = [
        "Newspaper Test",
        "Structure",
        "Ecosystem Wiring",
        "Tests",
        "Common Mistakes",
    ]

    for section in required_sections:
        if section in checklist:
            ok(f"checklist has '{section}' section")
        else:
            fail(f"checklist has '{section}' section")


# ─── Run all ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 64)
    print("WRITING-SKILL — STRESS TEST")
    print("=" * 64)

    test_file_structure()
    test_router()
    test_newspaper_rule()
    test_compact()
    test_next_steps_chain()
    test_chain_integrity()
    test_ecosystem_references()
    test_newspaper_logic_present()
    test_template_coverage()
    test_checklist_completeness()

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

    import sys as _sys
    _sys.exit(0 if failed == 0 else 1)
