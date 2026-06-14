"""
test_reward.py — the positive-signal ledger (reinforcement counterpart to mistakes).

Verifies: log_clean/log_solved round-trip + parse; net-quality weighting (CLEAN > SOLVED);
per-skill counts/points; net_by_skill gives the retro its missing denominator; 'none'
skill excluded; bad kind rejected; validate() drift guard; seed reward.md well-formed.

Run from tests/:  python test_reward.py
"""

import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

import reward

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []


def check(label, cond):
    results.append(cond)
    print(f"  {PASS if cond else FAIL} {label}")


SEED = "# REWARD\n<!-- New entries go below this line -->\n"


def _fresh_file():
    tmp = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    tmp.write(SEED)
    tmp.close()
    reward.REWARD_FILE = Path(tmp.name)
    return Path(tmp.name)


def test_round_trip_and_weighting():
    print("\n[reward — log / parse / net-quality weighting]")
    p = _fresh_file()
    reward.log_clean("IMPLEMENT clean: add badge", skill="implementer", gate="all_gates")
    reward.log_clean("IMPLEMENT clean: tweak copy", skill="implementer", gate="all_gates")
    reward.log_solved("recovered after 1 retry", skill="typescript-rules", gate="all_gates")

    entries = reward._parse_entries(p.read_text(encoding="utf-8"))
    check("all three wins parse", len(entries) == 3)
    check("CLEAN worth more than SOLVED (3 vs 1)", reward.POINTS["CLEAN"] > reward.POINTS["SOLVED"])
    check("points_by_skill: implementer 2 CLEAN = 6", reward.points_by_skill().get("implementer") == 6)
    check("points_by_skill: ts 1 SOLVED = 1", reward.points_by_skill().get("typescript-rules") == 1)
    check("count_by_skill: implementer 2 wins", reward.count_by_skill().get("implementer") == 2)
    check("total_points = 7", reward.total_points() == 7)
    p.unlink()


def test_net_gives_denominator():
    print("\n[reward — net_by_skill is the retro's missing denominator]")
    _fresh_file()
    for _ in range(8):
        reward.log_clean("clean run", skill="implementer")
    # mistakes side passed in (mirrors mistakes.count_by_skill())
    net = reward.net_by_skill({"implementer": 2, "diagnose": 3})
    check("implementer net positive (8 wins - 2 losses = +6)", net["implementer"]["net"] == 6)
    check("a loss-only skill still shows up with net negative",
          net["diagnose"]["net"] == -3 and net["diagnose"]["wins"] == 0)
    check("net carries wins and losses both", net["implementer"] == {"wins": 8, "losses": 2, "net": 6})


def test_none_skill_excluded_and_bad_kind():
    print("\n[reward — 'none' skill excluded; invalid kind rejected]")
    _fresh_file()
    reward.log_clean("no routed skill", skill="none")
    reward.log_clean("real win", skill="grill")
    check("'none' excluded from per-skill credit", "none" not in reward.count_by_skill())
    check("real skill still counted", reward.count_by_skill().get("grill") == 1)
    check("total_points still counts the 'none' win (2 CLEAN = 6)", reward.total_points() == 6)
    try:
        reward.log_reward("CAPTURED", "should be rejected")
        check("bare-capture kind rejected (no reward for introducing bugs)", False)
    except ValueError:
        check("bare-capture kind rejected (no reward for introducing bugs)", True)


def test_validate_drift_guard():
    print("\n[reward — validate() drift guard]")
    p = _fresh_file()
    reward.log_solved("a real win", skill="tdd")
    check("clean reward.md validates", reward.validate() == [])
    with open(p, "a", encoding="utf-8") as f:
        f.write("\n## [2026-06-14T00:00:00Z] CLEAN | retro\n**Oops**: wrong field\n**Points** : 3\n")
        f.write("\n## [2026-06-14T00:00:00Z] BONUS | retro\n**Win**    : valid fields, bad kind\n"
                "**Skill**  : x\n**Gate**   : g\n**Points** : 9\n")
    problems = reward.validate()
    check("flags the malformed entry", any("malformed" in p for p in problems))
    check("flags the unknown kind (BONUS)", any("unknown kind" in p for p in problems))
    p.unlink()


def test_seed_file_wellformed():
    print("\n[reward — committed memory/reward.md is well-formed]")
    seed = ROOT / "memory" / "reward.md"
    check("memory/reward.md exists", seed.exists())
    if seed.exists():
        text = seed.read_text(encoding="utf-8")
        check("has the insert marker", reward.INSERT_MARKER in text)


if __name__ == "__main__":
    print("=" * 60)
    print("REWARD (positive signal) — TEST")
    print("=" * 60)
    test_round_trip_and_weighting()
    test_net_gives_denominator()
    test_none_skill_excluded_and_bad_kind()
    test_validate_drift_guard()
    test_seed_file_wellformed()
    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed" + ("  -- all clear" if passed == total else f"  ({total-passed} FAILED)"))
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
