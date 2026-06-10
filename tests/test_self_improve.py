"""
test_self_improve.py — locks the self-improvement keystone (Gap 2) and the
per-gate visibility report.

Covers:
  - mistakes carry a `skill:` field, attributed to the routed skill
  - old entries (no Skill line) still parse (backward compatible)
  - count_by_skill() gives per-skill recurrence
  - mark_resolved() works on both old and new entries
  - run_all_gates_report() returns a full per-gate board (does not stop on first fail)

Run from tests/:  python test_self_improve.py
"""

import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

import mistakes
import gates

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []


def check(label, cond):
    results.append(cond)
    print(f"  {PASS if cond else FAIL} {label}")


OLD_ENTRY = """# MISTAKES.md
<!-- New entries go below this line -->
## [2026-01-01T00:00:00Z] IMPLEMENT | AUTO-LOGGED
**Error**     : pre-skill-field entry
**Cause**     : x
**Lesson**    : y
**Gate**      : ts_suppress
**Status**    : ACTIVE
"""


def test_skill_attribution():
    print("\n[mistakes — skill attribution + backward compat]")
    tmp = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    tmp.write(OLD_ENTRY)
    tmp.close()
    mistakes.MISTAKES_FILE = Path(tmp.name)

    mistakes.log_mistake(phase="IMPLEMENT", error="ts-ignore", gate="ts_suppress", skill="typescript-rules")
    mistakes.log_mistake(phase="IMPLEMENT", error="ts-ignore again", gate="ts_suppress", skill="typescript-rules")
    mistakes.log_mistake(phase="IMPLEMENT", error="redirect", gate="nextjs_redirect", skill="nextjs-rules")

    entries = mistakes._parse_entries(Path(tmp.name).read_text(encoding="utf-8"))
    check("old + new entries all parse (backward compatible)", len(entries) == 4)
    old = [e for e in entries if "pre-skill-field" in e["error"]][0]
    check("old entry defaults skill to 'none'", old["skill"] == "none")
    new = [e for e in entries if e["error"] == "ts-ignore"][0]
    check("new entry carries the routed skill", new["skill"] == "typescript-rules")

    by_skill = mistakes.count_by_skill()
    check("count_by_skill attributes recurrence", by_skill.get("typescript-rules") == 2)
    check("count_by_skill separates skills", by_skill.get("nextjs-rules") == 1)

    check("count_by_skill excludes 'none' (no skills/none.md proposals)", "none" not in mistakes.count_by_skill())
    check("mark_resolved works on the OLD-format entry", mistakes.mark_resolved("2026-01-01T00:00:00Z") is True)

    Path(tmp.name).unlink()


def test_gate_report():
    print("\n[gates — full per-gate board, no stop-on-first]")
    clean = "+++ b/app/page.tsx\n+const x = 1\n"
    bad = "+++ b/app/page.tsx\n+// @ts-ignore\n+console.log(1)\n"

    clean_report = gates.run_all_gates_report(clean)
    check("clean diff: every gate reported", len(clean_report) == len(gates.ALL_GATES))
    check("clean diff: all gates pass", all(r["passed"] for r in clean_report))

    bad_report = gates.run_all_gates_report(bad)
    failed = [r for r in bad_report if not r["passed"]]
    check("bad diff: report does not stop on first failure (2 fails)", len(failed) == 2)
    names = {r["gate"] for r in failed}
    check("bad diff: names the ts-ignore + console.log gates", "gate_no_ts_ignore" in names and "gate_no_console_log" in names)
    check("bad diff: failed gates carry a detail line", all(r["detail"] for r in failed))

    rendered = gates.format_gate_report(bad_report)
    check("report renders ASCII-safe (no unicode)", rendered.isascii())
    check("report header shows pass count", "3/5 passed" in rendered)


def test_apply_target_resolution():
    """retro emits 'skills/<file>.md'; apply_retro must NOT double the skills/ prefix."""
    print("\n[apply_retro — proposal targets resolve to real files]")
    import apply_retro as ar

    cases = {
        "skills/nextjs.md": "skills/nextjs.md",
        "skills/tdd/mocking.md": "skills/tdd/mocking.md",          # sub-skill
        "skills/writing-skill/discipline.md": "skills/writing-skill/discipline.md",
        "nextjs.md": "skills/nextjs.md",                            # bare → under skills/
    }
    for target, expected_rel in cases.items():
        resolved = ar._resolve_target(target)
        rel = resolved.relative_to(ar.ROOT).as_posix()
        check(f"{target!r} -> {expected_rel} (exists)", rel == expected_rel and resolved.exists())

    # the original bug: skills/skills/... must never be produced
    bug = ar._resolve_target("skills/nextjs.md")
    check("never produces double skills/ prefix", "skills/skills" not in bug.as_posix())


def test_structural_gate():
    """Gap 3: applied edits must obey the line-cap / Next-Steps gates,
    but pre-existing violations must not cause false rejects."""
    print("\n[Gap 3 — apply_retro obeys structure gates]")
    import apply_retro as ar

    ns = "\n## Next Steps\n- back\n"
    entry = "\n".join(f"line {i}" for i in range(90)) + ns          # ~92 lines
    grown_over = entry + "\n" + "\n".join(f"x{i}" for i in range(20))  # ~112
    ok, _ = ar._validate_edit(ar.ROOT / "skills/foo.md", entry, grown_over)
    check("entry edit over 100-line cap is rejected", ok is False)

    ok, _ = ar._validate_edit(ar.ROOT / "skills/foo.md", entry, entry + "\none more\n")
    check("entry edit staying under cap is allowed", ok is True)

    sub = "\n".join(f"l{i}" for i in range(140)) + ns
    sub_over = sub + "\n" + "\n".join(f"x{i}" for i in range(20))
    ok, _ = ar._validate_edit(ar.ROOT / "skills/x/y.md", sub, sub_over)
    check("sub-skill edit over 150-line cap is rejected", ok is False)

    big = "\n".join(str(i) for i in range(500))
    ok, _ = ar._validate_edit(ar.ROOT / "skills/webapp-testing/SKILL.md", "x", big)
    check("capability SKILL.md is cap-exempt", ok is True)

    ok, _ = ar._validate_edit(ar.ROOT / "skills/foo.md", entry, entry.replace("## Next Steps", "## Gone"))
    check("edit removing ## Next Steps is rejected", ok is False)

    over = "\n".join(f"l{i}" for i in range(130)) + ns               # already > 100
    shrunk = "\n".join(f"l{i}" for i in range(120)) + ns
    ok, _ = ar._validate_edit(ar.ROOT / "skills/foo.md", over, shrunk)
    check("delete on a pre-existing over-cap file is allowed (not worsened)", ok is True)


def test_eval_regression():
    """Gap 4: applied edits are tagged with eval@apply; regression flags when eval drops."""
    print("\n[Gap 4 — eval-tagged edits + regression flag]")
    import json
    import apply_retro as ar
    import evaluator

    prop = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    prop.write(
        "## Retro — 2026-06-09\n\n"
        "### PROPOSE ADD to skills/tdd.md\nbody text\n"
        "<!-- APPLIED: 2026-06-09T00:00:00Z | eval@apply=80 — appended -->\n"
    )
    prop.close()
    ar.PROPOSALS_FILE = Path(prop.name)

    hist = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    hist.close()
    evaluator.EVAL_HISTORY = Path(hist.name)

    Path(hist.name).write_text(json.dumps([{"total": 90}, {"total": 70}]), encoding="utf-8")
    flags = ar.check_regressions()
    check("regression flagged when eval dropped below eval@apply",
          len(flags) == 1 and flags[0]["target"] == "skills/tdd.md")
    check("regression delta is correct (-10)", flags and flags[0]["delta"] == -10)

    Path(hist.name).write_text(json.dumps([{"total": 85}]), encoding="utf-8")
    check("no flag once eval recovers above eval@apply", ar.check_regressions() == [])

    Path(prop.name).unlink()
    Path(hist.name).unlink()


if __name__ == "__main__":
    print("=" * 60)
    print("SELF-IMPROVEMENT + GATE VISIBILITY — TEST")
    print("=" * 60)
    test_skill_attribution()
    test_gate_report()
    test_apply_target_resolution()
    test_structural_gate()
    test_eval_regression()
    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed" + ("  -- all clear" if passed == total else f"  ({total-passed} FAILED)"))
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
