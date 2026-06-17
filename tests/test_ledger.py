"""
test_ledger.py — the decision/lesson/discipline ledger (method memory).

Verifies log_decision/lesson/discipline round-trip, parsing, keyword relevance
surfacing, count_by_kind, and that the seeded memory/ledger.md is well-formed.

Run from tests/:  python test_ledger.py
"""

import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

import ledger

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []


def check(label, cond):
    results.append(cond)
    print(f"  {PASS if cond else FAIL} {label}")


SEED = "# LEDGER\n<!-- New entries go below this line -->\n"


def test_round_trip():
    print("\n[ledger — log / parse / relevance / counts]")
    tmp = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    tmp.write(SEED)
    tmp.close()
    ledger.LEDGER_FILE = Path(tmp.name)

    ledger.log_decision("reconcile three philosophies by skill type", "averaging cancels contradictions", skill="writing-skill")
    ledger.log_lesson("run the eval suite after router changes", "generic keywords stole routes", skill="none")
    ledger.log_discipline("gate self-improvement on recurrence, not scores", "scores overfit", skill="writing-skill")

    entries = ledger._parse_entries(Path(tmp.name).read_text(encoding="utf-8"))
    check("all three entries parse", len(entries) == 3)
    kinds = {e["kind"] for e in entries}
    check("kinds recorded (DECISION/LESSON/DISCIPLINE)", kinds == {"DECISION", "LESSON", "DISCIPLINE"})
    dec = [e for e in entries if e["kind"] == "DECISION"][0]
    check("decision carries skill attribution", dec["skill"] == "writing-skill")

    check("count_active = 3", ledger.count_active() == 3)
    check("count_by_kind splits kinds", ledger.count_by_kind() == {"DECISION": 1, "LESSON": 1, "DISCIPLINE": 1})

    rel = ledger.check_relevant("update the router and skill types")
    check("check_relevant surfaces matching entries", len(rel) >= 1)
    check("check_relevant matches on keywords (router/skill)",
          any("router" in e["what"].lower() or "skill" in e["what"].lower() for e in rel))

    # bad kind rejected; missing marker rejected
    try:
        ledger.log_entry("RANDOM", "x")
        check("invalid kind raises", False)
    except ValueError:
        check("invalid kind raises", True)

    Path(tmp.name).unlink()


def test_seed_file_wellformed():
    print("\n[ledger — committed memory/ledger.md is well-formed]")
    seed = ROOT / "memory" / "ledger.md"
    check("memory/ledger.md exists", seed.exists())
    if seed.exists():
        text = seed.read_text(encoding="utf-8")
        check("has the insert marker", ledger.INSERT_MARKER in text)
        # parse against the real module (LEDGER_FILE may be patched; parse text directly)
        entries = ledger._parse_entries(text)
        check("seed entries parse (>=1)", len(entries) >= 1)
        check("all seed entries have a valid kind", all(e["kind"] in ledger.KINDS for e in entries))


def test_validate_drift_guard():
    """validate() must SEE format drift instead of silently swallowing it."""
    print("\n[ledger — validate() drift guard]")
    tmp = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    tmp.write(SEED)
    tmp.close()
    ledger.LEDGER_FILE = Path(tmp.name)

    # one good entry
    ledger.log_lesson("a real lesson", "evidence", skill="none")
    check("clean ledger validates with no problems", ledger.validate() == [])

    # malformed entry: header present but wrong field name -> won't parse (count branch)
    # unknown-kind entry: well-formed but kind not in KINDS -> parses, caught by kind branch
    with open(tmp.name, "a", encoding="utf-8") as f:
        f.write("\n## [2026-06-09T00:00:00Z] LESSON | retro\n**Oops**: wrong field name\n**Status** : ACTIVE\n")
        f.write("\n## [2026-06-09T00:00:00Z] NOTE | retro\n**What**   : valid fields, bad kind\n**Why**    : x\n**Skill**  : none\n**Status** : ACTIVE\n")
    problems = ledger.validate()
    check("validate() flags the malformed entry (header > parsed)", any("malformed" in p for p in problems))
    check("validate() flags the unknown kind (NOTE)", any("unknown kind" in p for p in problems))
    check("validate() never raises (returns a list)", isinstance(problems, list))

    Path(tmp.name).unlink()


if __name__ == "__main__":
    print("=" * 60)
    print("LEDGER (method memory) — TEST")
    print("=" * 60)
    test_round_trip()
    test_seed_file_wellformed()
    test_validate_drift_guard()
    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed" + ("  -- all clear" if passed == total else f"  ({total-passed} FAILED)"))
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
