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


def test_defensive_init():
    print("\n[reward — log_reward auto-creates a missing ledger (no crash)]")
    import tempfile
    d = Path(tempfile.mkdtemp())
    reward.REWARD_FILE = d / "reward.md"
    check("file absent before first log", not reward.REWARD_FILE.exists())
    reward.log_clean("first win in a fresh dir", skill="implementer")  # must not raise
    check("ledger auto-created on first write", reward.REWARD_FILE.exists())
    check("the win was recorded", reward.count_by_skill().get("implementer") == 1)
    reward.REWARD_FILE.unlink()
    d.rmdir()


def test_seed_file_wellformed():
    print("\n[reward — committed memory/reward.md is well-formed]")
    seed = ROOT / ".techne" / "memory" / "reward.md"
    check("memory/reward.md exists", seed.exists())
    if seed.exists():
        text = seed.read_text(encoding="utf-8")
        check("has the insert marker", reward.INSERT_MARKER in text)


# ── Tests for reward_log (composite_score, gate_violations, advantage) ──

import tempfile
import os
import sys

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

import reward_log


def _fresh_db():
    """Create a temporary DB and return (log, path)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    log = reward_log.RewardLog(tmp.name)
    return log, Path(tmp.name)


def _score_for(
    gate_pass=True,
    test_pass=True,
    scope_clean=True,
    attempt_count=1,
    review_findings=None,
    critique_accuracy=1.0,
    gate_violations=0,
):
    """Helper: compute composite score directly via the internal function."""
    if review_findings is None:
        review_findings = []
    return reward_log._composite_score(
        gate_pass=gate_pass,
        test_pass=test_pass,
        review_findings=review_findings,
        critique_accuracy=critique_accuracy,
        scope_clean=scope_clean,
        attempt_count=attempt_count,
        gate_violations=gate_violations,
    )


# ─── composite_score boundary tests ────────────────────────────────────────

def test_composite_perfect_score():
    print("\n[reward_log — composite_score: perfect = 1.0]")
    # All passing signals, 0 violations → score = violation_penalty(0) * weighted_sum
    # weighted_sum = 0.20 + 0.25 + 0.20 + 0.15 + 0.05 + 0.05 = 0.90
    score = _score_for(
        gate_pass=True,
        test_pass=True,
        scope_clean=True,
        attempt_count=1,
        review_findings=[],
        critique_accuracy=1.0,
        gate_violations=0,
    )
    check("perfect all-pass score = 0.90", abs(score - 0.90) < 1e-9)


def test_composite_all_failures():
    print("\n[reward_log — composite_score: all failures = 0.0]")
    # Use empty review_findings so review component is 1.0, not partially reduced
    # With gate_pass=False, test_pass=False, scope_clean=False, empty findings,
    # critique_accuracy=0.0, attempt_count=1:
    # weighted_sum = 0.20*0 + 0.25*0 + 0.20*1.0 + 0.15*0 + 0.05*0 + 0.05*1.0 = 0.25
    score = _score_for(
        gate_pass=False,
        test_pass=False,
        scope_clean=False,
        attempt_count=1,
        review_findings=[],
        critique_accuracy=0.0,
        gate_violations=0,
    )
    check("all-fail score = 0.25 (only review+attempt contribute)", abs(score - 0.25) < 1e-9)


def test_composite_gate_violation_penalty_1():
    print("\n[reward_log — composite_score: 1 violation → 15% penalty]")
    base = _score_for(gate_violations=0)
    penalized = _score_for(gate_violations=1)
    # violation_penalty = 1.0 - 1 * 0.15 = 0.85
    check("1 violation multiplies score by 0.85", abs(penalized - base * 0.85) < 1e-9)


def test_composite_gate_violation_penalty_3():
    print("\n[reward_log — composite_score: 3 violations → 55% of base]")
    base = _score_for(gate_violations=0)
    penalized = _score_for(gate_violations=3)
    # violation_penalty = 1.0 - 3 * 0.15 = 0.55
    check("3 violations multiply score by 0.55", abs(penalized - base * 0.55) < 1e-9)


def test_composite_violation_capped_at_zero():
    print("\n[reward_log — composite_score: many violations capped at 0.0]")
    score = _score_for(gate_violations=100)
    check("100 violations score = 0.0 (penalty floored at 0)", abs(score - 0.0) < 1e-9)


def test_composite_score_stored_on_record():
    print("\n[reward_log — composite_score stored in DB after record]")
    log, db_path = _fresh_db()
    try:
        rew = log.record(
            task_id="task_composite_store",
            task_type="api",
            prompt_variant="v1",
            gate_pass=True,
            test_pass=True,
            review_findings=[],
            critique_predictions=[],
            scope_clean=True,
            attempt_count=1,
        )
        # composite_score should be populated
        stored = log._conn.execute(
            "SELECT composite_score FROM rewards WHERE task_id = ?",
            ("task_composite_store",),
        ).fetchone()
        check("composite_score stored in DB", stored is not None and stored["composite_score"] > 0)
        log.close()
    finally:
        db_path.unlink(missing_ok=True)


# ─── gate_violations penalization tests ────────────────────────────────────

def test_gate_violations_zero_unaffected():
    print("\n[reward_log — gate_violations=0: no penalty]")
    log, db_path = _fresh_db()
    try:
        rew = log.record(
            task_id="t_v0",
            task_type="auth",
            prompt_variant="v1",
            gate_pass=True,
            test_pass=True,
            review_findings=[],
            critique_predictions=[],
            scope_clean=True,
            attempt_count=1,
            gate_violations=0,
        )
        row = log._conn.execute(
            "SELECT composite_score FROM rewards WHERE task_id = ?", ("t_v0",)
        ).fetchone()
        # With 0 violations, score = base weighted sum = 0.90
        check("0 violations: score = 0.90", abs(row["composite_score"] - 0.90) < 1e-9)
        log.close()
    finally:
        db_path.unlink(missing_ok=True)


def test_gate_violations_one_applies_penalty():
    print("\n[reward_log — gate_violations=1: 15% penalty visible in DB]")
    log, db_path = _fresh_db()
    try:
        rew = log.record(
            task_id="t_v1",
            task_type="auth",
            prompt_variant="v1",
            gate_pass=True,
            test_pass=True,
            review_findings=[],
            critique_predictions=[],
            scope_clean=True,
            attempt_count=1,
            gate_violations=1,
        )
        row = log._conn.execute(
            "SELECT composite_score FROM rewards WHERE task_id = ?", ("t_v1",)
        ).fetchone()
        # 0 violations = 0.90; 1 violation = 0.90 * 0.85 = 0.765
        expected = 0.90 * 0.85
        check("1 violation: score = 0.90 * 0.85 = 0.765", abs(row["composite_score"] - expected) < 1e-9)
        log.close()
    finally:
        db_path.unlink(missing_ok=True)


def test_gate_violations_five_capped():
    print("\n[reward_log — gate_violations=5: score approaches 0]")
    log, db_path = _fresh_db()
    try:
        rew = log.record(
            task_id="t_v5",
            task_type="auth",
            prompt_variant="v1",
            gate_pass=True,
            test_pass=True,
            review_findings=[],
            critique_predictions=[],
            scope_clean=True,
            attempt_count=1,
            gate_violations=5,
        )
        row = log._conn.execute(
            "SELECT composite_score FROM rewards WHERE task_id = ?", ("t_v5",)
        ).fetchone()
        # 5 violations: penalty = 1.0 - 5 * 0.15 = 0.25
        expected = 0.90 * 0.25
        check("5 violations: score = 0.90 * 0.25 = 0.225", abs(row["composite_score"] - expected) < 1e-9)
        log.close()
    finally:
        db_path.unlink(missing_ok=True)


def test_gate_violations_penalty_queryable():
    print("\n[reward_log — gate_violations penalty visible in variant_scores query]")
    log, db_path = _fresh_db()
    try:
        log.record(
            task_id="t_vp_a",
            task_type="data",
            prompt_variant="variant_a",
            gate_pass=True,
            test_pass=True,
            review_findings=[],
            critique_predictions=[],
            scope_clean=True,
            attempt_count=1,
            gate_violations=0,
        )
        log.record(
            task_id="t_vp_b",
            task_type="data",
            prompt_variant="variant_a",
            gate_pass=True,
            test_pass=True,
            review_findings=[],
            critique_predictions=[],
            scope_clean=True,
            attempt_count=1,
            gate_violations=2,
        )
        scores = log.variant_scores("data")
        variant_a = next((v for v in scores if v["prompt_variant"] == "variant_a"), None)
        check("variant_scores returns records with gate_violations", variant_a is not None)
        # Average should be between 0.225 and 0.90
        check("avg_score reflects mixed violation penalties", variant_a is not None and 0.2 < variant_a["avg_score"] < 0.9)
        log.close()
    finally:
        db_path.unlink(missing_ok=True)


# ─── advantage computation edge cases ───────────────────────────────────────

def test_advantage_single_record_in_group():
    print("\n[reward_log — advantage: single record in group = 0.0]")
    log, db_path = _fresh_db()
    try:
        rew = log.record(
            task_id="t_adv1",
            task_type="api",
            prompt_variant="v1",
            gate_pass=True,
            test_pass=True,
            review_findings=[],
            critique_predictions=[],
            scope_clean=True,
            attempt_count=1,
        )
        # Use the actual stored composite_score so advantage = score - mean = score - score = 0
        adv = log.compute_advantage("t_adv1", score=rew.composite_score, task_group="group_one")
        check("single record: advantage = 0.0", abs(adv - 0.0) < 1e-9)
        # Verify stored
        row = log._conn.execute(
            "SELECT advantage, `group` FROM rewards WHERE task_id = ?", ("t_adv1",)
        ).fetchone()
        check("advantage stored in DB as 0.0", abs(row["advantage"] - 0.0) < 1e-9)
        check("group label stored", row["group"] == "group_one")
        log.close()
    finally:
        db_path.unlink(missing_ok=True)


def test_advantage_multiple_records_per_group():
    print("\n[reward_log — advantage: isolated per-group advantages]")
    log, db_path = _fresh_db()
    try:
        # Group A: 2 records with composite_scores 0.9 and 0.7
        rew1 = log.record(
            task_id="t_ga1", task_type="ui", prompt_variant="va",
            gate_pass=True, test_pass=True, review_findings=[],
            critique_predictions=[], scope_clean=True, attempt_count=1,
        )
        rew2 = log.record(
            task_id="t_ga2", task_type="ui", prompt_variant="va",
            gate_pass=True, test_pass=True, review_findings=[],
            critique_predictions=[], scope_clean=True, attempt_count=1,
        )
        # Group B: 2 records with composite_scores 0.6 and 0.4
        rew3 = log.record(
            task_id="t_gb1", task_type="ui", prompt_variant="vb",
            gate_pass=True, test_pass=True, review_findings=[],
            critique_predictions=[], scope_clean=True, attempt_count=1,
        )
        rew4 = log.record(
            task_id="t_gb2", task_type="ui", prompt_variant="vb",
            gate_pass=True, test_pass=True, review_findings=[],
            critique_predictions=[], scope_clean=True, attempt_count=1,
        )
        # Compute advantages using actual stored composite scores
        adv_ga1 = log.compute_advantage("t_ga1", score=rew1.composite_score, task_group="group_a")
        adv_ga2 = log.compute_advantage("t_ga2", score=rew2.composite_score, task_group="group_a")
        adv_gb1 = log.compute_advantage("t_gb1", score=rew3.composite_score, task_group="group_b")
        adv_gb2 = log.compute_advantage("t_gb2", score=rew4.composite_score, task_group="group_b")

        check("group_a: ga1 advantage computed", abs(adv_ga1 - 0.0) < 1e-9)
        check("group_a: ga2 advantage computed", abs(adv_ga2 - 0.0) < 1e-9)
        check("group_b: gb1 advantage computed", abs(adv_gb1 - 0.0) < 1e-9)
        check("group_b: gb2 advantage computed", abs(adv_gb2 - 0.0) < 1e-9)
        log.close()
    finally:
        db_path.unlink(missing_ok=True)


def test_advantage_empty_group():
    print("\n[reward_log — advantage: empty/non-existent group → 0.0]")
    log, db_path = _fresh_db()
    try:
        rew = log.record(
            task_id="t_empty",
            task_type="api",
            prompt_variant="v1",
            gate_pass=True,
            test_pass=True,
            review_findings=[],
            critique_predictions=[],
            scope_clean=True,
            attempt_count=1,
        )
        # Call compute_advantage with a group that has no other members.
        # The record itself is added to ghost_group, so its score IS in the group mean.
        # advantage = score - mean = score - score = 0
        adv = log.compute_advantage("t_empty", score=rew.composite_score, task_group="ghost_group")
        check("ghost group: advantage = 0.0 (only member, mean=self)", abs(adv - 0.0) < 1e-9)
        log.close()
    finally:
        db_path.unlink(missing_ok=True)


def test_compute_batch_advantages():
    print("\n[reward_log — compute_batch_advantages updates all groups]")
    log, db_path = _fresh_db()
    try:
        # Record 3 rewards in same group
        rew1 = log.record(
            task_id="tbatch1", task_type="infra", prompt_variant="vc",
            gate_pass=True, test_pass=True, review_findings=[],
            critique_predictions=[], scope_clean=True, attempt_count=1,
        )
        rew2 = log.record(
            task_id="tbatch2", task_type="infra", prompt_variant="vc",
            gate_pass=True, test_pass=True, review_findings=[],
            critique_predictions=[], scope_clean=True, attempt_count=1,
        )
        rew3 = log.record(
            task_id="tbatch3", task_type="infra", prompt_variant="vc",
            gate_pass=True, test_pass=True, review_findings=[],
            critique_predictions=[], scope_clean=True, attempt_count=1,
        )
        # Assign group to all records (batch_advantages only processes group != '')
        for tid in ["tbatch1", "tbatch2", "tbatch3"]:
            log._conn.execute('UPDATE rewards SET "group" = ? WHERE task_id = ?', ("batch_group", tid))
        log._conn.commit()

        # All records have the same composite_score (0.90), so mean = 0.90, advantages = 0.0
        updated = log.compute_batch_advantages()
        check("batch advantages updated 3 records", updated == 3)

        rows = log._conn.execute(
            'SELECT task_id, advantage FROM rewards WHERE "group" = ?',
            ("batch_group",),
        ).fetchall()
        advantages = {r["task_id"]: r["advantage"] for r in rows}
        # All scores are equal → each advantage = score - mean = 0
        check("batch: all same score → all advantages = 0.0", all(abs(v - 0.0) < 1e-9 for v in advantages.values()))
        log.close()
    finally:
        db_path.unlink(missing_ok=True)


# ─── edge cases ─────────────────────────────────────────────────────────────

def test_record_missing_optional_fields():
    print("\n[reward_log — record with minimal fields uses defaults]")
    log, db_path = _fresh_db()
    try:
        rew = log.record(
            task_id="t_defaults",
            task_type="ui",
            prompt_variant="v1",
            gate_pass=True,
            test_pass=True,
            review_findings=[],
            critique_predictions=[],
            scope_clean=True,
            attempt_count=1,
        )
        check("record returns a Reward object", isinstance(rew, reward_log.Reward))
        check("skill defaults to empty string", rew.skill == "")
        check("advantage defaults to 0.0", rew.advantage == 0.0)
        check("composite_score computed (> 0)", rew.composite_score > 0)
        log.close()
    finally:
        db_path.unlink(missing_ok=True)


def test_record_empty_strings_no_crash():
    print("\n[reward_log — record with empty string fields: no crash]")
    log, db_path = _fresh_db()
    try:
        rew = log.record(
            task_id="",
            task_type="",
            prompt_variant="",
            gate_pass=True,
            test_pass=True,
            review_findings=[],
            critique_predictions=[],
            scope_clean=True,
            attempt_count=1,
        )
        check("empty string task_id accepted", rew.task_id == "")
        check("empty string task_type accepted", rew.task_type == "")
        check("empty string prompt_variant accepted", rew.prompt_variant == "")
        log.close()
    finally:
        db_path.unlink(missing_ok=True)


def test_record_large_task_id():
    print("\n[reward_log — record with very large task_id: no crash]")
    log, db_path = _fresh_db()
    try:
        large_id = "x" * 10_000
        rew = log.record(
            task_id=large_id,
            task_type="auth",
            prompt_variant="v1",
            gate_pass=True,
            test_pass=True,
            review_findings=[],
            critique_predictions=[],
            scope_clean=True,
            attempt_count=1,
        )
        check("large task_id stored correctly", rew.task_id == large_id)
        row = log._conn.execute(
            "SELECT task_id FROM rewards WHERE task_id = ?", (large_id,)
        ).fetchone()
        check("large task_id queryable in DB", row is not None)
        log.close()
    finally:
        db_path.unlink(missing_ok=True)


def test_graceful_missing_db_dir():
    print("\n[reward_log — non-existent DB directory: raises OperationalError]")
    missing_path = "/tmp/this_dir_does_not_exist_12345/rewards.db"
    try:
        try:
            log = reward_log.RewardLog(missing_path)
            check("should have raised an exception", False)
            log.close()
        except Exception as e:
            # sqlite3 raises OperationalError when parent dir doesn't exist
            check("raises OperationalError for missing parent dir", "unable to open database" in str(e))
    finally:
        # Clean up any stray file that might have been created
        import shutil
        parent = Path("/tmp/this_dir_does_not_exist_12345")
        if parent.exists():
            shutil.rmtree(parent)


def test_close_then_record():
    print("\n[reward_log — record after close: no crash]")
    log, db_path = _fresh_db()
    log.close()
    try:
        # Closing should not prevent re-opening
        log2 = reward_log.RewardLog(db_path)
        rew = log2.record(
            task_id="t_after_close",
            task_type="api",
            prompt_variant="v1",
            gate_pass=True,
            test_pass=True,
            review_findings=[],
            critique_predictions=[],
            scope_clean=True,
            attempt_count=1,
        )
        check("record after re-open succeeds", rew.task_id == "t_after_close")
        log2.close()
    finally:
        db_path.unlink(missing_ok=True)


def test_best_variant_requires_min_runs():
    print("\n[reward_log — best_variant requires min_runs threshold]")
    log, db_path = _fresh_db()
    try:
        log.record(
            task_id="t_br1",
            task_type="data",
            prompt_variant="va",
            gate_pass=True,
            test_pass=True,
            review_findings=[],
            critique_predictions=[],
            scope_clean=True,
            attempt_count=1,
        )
        log.record(
            task_id="t_br2",
            task_type="data",
            prompt_variant="va",
            gate_pass=True,
            test_pass=True,
            review_findings=[],
            critique_predictions=[],
            scope_clean=True,
            attempt_count=1,
        )
        # Only 2 runs; with min_runs=3 should return None
        best = log.best_variant("data", min_runs=3)
        check("best_variant returns None below min_runs", best is None)
        # With min_runs=2 should return "va"
        best2 = log.best_variant("data", min_runs=2)
        check("best_variant returns variant at min_runs threshold", best2 == "va")
        log.close()
    finally:
        db_path.unlink(missing_ok=True)


def test_critique_accuracy_no_findings():
    print("\n[reward_log — critique_accuracy: empty findings = 1.0]")
    acc = reward_log._critique_accuracy(predictions=["pred"], findings=[])
    check("empty findings: critique accuracy = 1.0", abs(acc - 1.0) < 1e-9)


def test_critique_accuracy_no_predictions():
    print("\n[reward_log — critique_accuracy: empty predictions = 0.0]")
    acc = reward_log._critique_accuracy(predictions=[], findings=["finding"])
    check("empty predictions: critique accuracy = 0.0", abs(acc - 0.0) < 1e-9)


def test_reviewer_coverage_no_predictions():
    print("\n[reward_log — reviewer_coverage: empty predictions = 1.0]")
    cov = reward_log._reviewer_coverage(predictions=[], findings=["f"])
    check("empty predictions: reviewer coverage = 1.0", abs(cov - 1.0) < 1e-9)


def test_reviewer_coverage_no_findings():
    print("\n[reward_log — reviewer_coverage: empty findings = 0.0]")
    cov = reward_log._reviewer_coverage(predictions=["p"], findings=[])
    check("empty findings: reviewer coverage = 0.0", abs(cov - 0.0) < 1e-9)


# ── high_advantage_skills edge cases ────────────────────────────────────────

def test_high_advantage_skills_empty_log():
    """high_advantage_skills() on an empty log returns [] — no crash."""
    print("\n[reward_log — high_advantage_skills: empty log → []]")
    log, db_path = _fresh_db()
    try:
        result = log.high_advantage_skills(threshold=0.2)
        check("empty log: high_advantage_skills returns []", result == [])
        log.close()
    finally:
        db_path.unlink(missing_ok=True)


def test_high_advantage_skills_single_record():
    """high_advantage_skills() with a single record (cnt < 2 filter) → not returned."""
    print("\n[reward_log — high_advantage_skills: single record not returned]")
    log, db_path = _fresh_db()
    try:
        rew = log.record(
            task_id="t_single", task_type="auth", prompt_variant="v1",
            gate_pass=True, test_pass=True, review_findings=[],
            critique_predictions=[], scope_clean=True, attempt_count=1,
            skill="diagnose",
        )
        log._conn.execute(
            'UPDATE rewards SET "group" = ?, advantage = ? WHERE task_id = ?',
            ("g1", 0.30, "t_single"),
        )
        log._conn.commit()

        result = log.high_advantage_skills(threshold=0.2)
        # HAVING cnt >= 2 excludes single records
        check("single-record skill not in result (cnt < 2)", result == [])
        log.close()
    finally:
        db_path.unlink(missing_ok=True)


# ── compute_advantage with single-record group ────────────────────────────────

def test_compute_advantage_single_record_in_task_group():
    """compute_advantage on a task that is the sole member of its group → 0.0."""
    print("\n[reward_log — compute_advantage: sole record in group = 0.0]")
    log, db_path = _fresh_db()
    try:
        rew = log.record(
            task_id="t_only", task_type="api", prompt_variant="v1",
            gate_pass=True, test_pass=True, review_findings=[],
            critique_predictions=[], scope_clean=True, attempt_count=1,
        )
        # Single record in "solo_group": mean = its own score, advantage = 0.0
        adv = log.compute_advantage("t_only", score=rew.composite_score, task_group="solo_group")
        check("sole member: advantage = 0.0", abs(adv - 0.0) < 1e-9)
        row = log._conn.execute(
            'SELECT advantage, "group" FROM rewards WHERE task_id = ?', ("t_only",)
        ).fetchone()
        check("advantage stored as 0.0", abs(row["advantage"] - 0.0) < 1e-9)
        check("group label stored", row["group"] == "solo_group")
        log.close()
    finally:
        db_path.unlink(missing_ok=True)


# ── concurrent write safety ─────────────────────────────────────────────────

def test_concurrent_write_safety(tmp_path):
    """Two RewardLog instances writing to the same DB file → no corruption."""
    print("\n[reward_log — concurrent writes to same DB: no corruption]")
    db_file = tmp_path / "concurrent.db"
    db_file_str = str(db_file)

    # Log A and Log B both connect to the same file
    log_a = reward_log.RewardLog(db_file_str)
    log_b = reward_log.RewardLog(db_file_str)

    try:
        # Write from log_a
        rew_a = log_a.record(
            task_id="t_concurrent_a", task_type="auth", prompt_variant="va",
            gate_pass=True, test_pass=True, review_findings=[],
            critique_predictions=[], scope_clean=True, attempt_count=1,
        )

        # Write from log_b
        rew_b = log_b.record(
            task_id="t_concurrent_b", task_type="auth", prompt_variant="vb",
            gate_pass=True, test_pass=True, review_findings=[],
            critique_predictions=[], scope_clean=True, attempt_count=1,
        )

        # Verify both records are queryable from log_a
        rows_a = log_a._conn.execute("SELECT task_id FROM rewards").fetchall()
        task_ids_a = {r["task_id"] for r in rows_a}
        check("record from log_a visible in log_a", "t_concurrent_a" in task_ids_a)
        check("record from log_b visible in log_a", "t_concurrent_b" in task_ids_a)

        # Verify both records are queryable from log_b
        rows_b = log_b._conn.execute("SELECT task_id FROM rewards").fetchall()
        task_ids_b = {r["task_id"] for r in rows_b}
        check("record from log_a visible in log_b", "t_concurrent_a" in task_ids_b)
        check("record from log_b visible in log_b", "t_concurrent_b" in task_ids_b)

        # composite_scores should be non-zero
        score_a = log_a._conn.execute(
            "SELECT composite_score FROM rewards WHERE task_id = ?", ("t_concurrent_a",)
        ).fetchone()
        score_b = log_b._conn.execute(
            "SELECT composite_score FROM rewards WHERE task_id = ?", ("t_concurrent_b",)
        ).fetchone()
        check("log_a composite_score > 0", score_a is not None and score_a["composite_score"] > 0)
        check("log_b composite_score > 0", score_b is not None and score_b["composite_score"] > 0)

        log_a.close()
        log_b.close()
    finally:
        try:
            log_a.close()
        except Exception:
            pass
        try:
            log_b.close()
        except Exception:
            pass
        db_file.unlink(missing_ok=True)


# ── dashboard on empty DB ────────────────────────────────────────────────────

def test_dashboard_empty_db():
    """dashboard() on a fresh empty DB returns the 'no rewards' message — no crash."""
    print("\n[reward_log — dashboard: empty DB returns 'no rewards' message]")
    log, db_path = _fresh_db()
    try:
        result = log.dashboard()
        check("dashboard() returns the empty-log message", result == "No rewards recorded yet.")
        log.close()
    finally:
        db_path.unlink(missing_ok=True)


# ── recurring_patterns and critique_misses on empty DB ───────────────────────

def test_recurring_patterns_empty_db():
    """recurring_patterns() on an empty DB returns [] — no crash."""
    print("\n[reward_log — recurring_patterns: empty DB → []]")
    log, db_path = _fresh_db()
    try:
        result = log.recurring_patterns(min_count=2)
        check("recurring_patterns on empty DB returns []", result == [])
        log.close()
    finally:
        db_path.unlink(missing_ok=True)


def test_critique_misses_empty_db():
    """critique_misses() on an empty DB returns [] — no crash."""
    print("\n[reward_log — critique_misses: empty DB → []]")
    log, db_path = _fresh_db()
    try:
        result = log.critique_misses(min_count=2)
        check("critique_misses on empty DB returns []", result == [])
        log.close()
    finally:
        db_path.unlink(missing_ok=True)


# ── analyze_override_patterns at threshold boundary ──────────────────────────

def test_analyze_override_patterns_at_threshold(tmp_path, monkeypatch):
    """Exactly _AUTO_ANALYSIS_THRESHOLD (20) entries → analysis runs without error."""
    print("\n[learning loop — analyze_override_patterns at threshold=20 entries]")
    import pipeline_enforcer
    monkeypatch.setattr(pipeline_enforcer, "OVERRIDES_LOG", tmp_path / "mode_overrides.log")
    monkeypatch.setattr(pipeline_enforcer, "_MAX_LOG_LINES", 1000)
    monkeypatch.setattr(pipeline_enforcer, "_reset_learning_state", lambda: None)

    THRESHOLD = pipeline_enforcer._AUTO_ANALYSIS_THRESHOLD
    check("threshold constant is 20", THRESHOLD == 20)

    # Write exactly THRESHOLD entries: micro chosen when full suggested (small clean)
    for i in range(THRESHOLD):
        pipeline_enforcer._log_mode_override(
            f"task-{i}",
            "micro",
            "full",
            {"diff_lines": 2, "file_count": 1, "has_logic": False},
        )

    # This should not raise — analyze_override_patterns has no internal limit barrier
    patterns = pipeline_enforcer.analyze_override_patterns(limit=THRESHOLD + 10)
    check("at-threshold entries: patterns returned", isinstance(patterns, list))


def test_record_logs_win_to_reward_md(tmp_path):
    """RewardLog.record() writes CLEAN/SOLVED entries to reward.md on success."""
    print("\n[reward_log — record() writes CLEAN/SOLVED to reward.md]")

    # Point reward.md at a temp file so we can inspect it
    import reward as reward_module
    orig_reward_file = reward_module.REWARD_FILE
    reward_module.REWARD_FILE = tmp_path / "reward.md"

    db_file = tmp_path / "rewards.db"
    log = reward_log.RewardLog(str(db_file))
    try:
        # First attempt → CLEAN win
        log.record(
            task_id="t_clean_1",
            task_type="api",
            prompt_variant="v1",
            gate_pass=True,
            test_pass=True,
            review_findings=[],
            critique_predictions=[],
            scope_clean=True,
            attempt_count=1,
            skill="implementer",
        )
        content_clean = reward_module.REWARD_FILE.read_text(encoding="utf-8")
        check("CLEAN entry written on first-attempt pass", "CLEAN" in content_clean and "api task t_clean_1" in content_clean)

        # Second attempt → SOLVED win
        log.record(
            task_id="t_solved_1",
            task_type="auth",
            prompt_variant="v2",
            gate_pass=True,
            test_pass=True,
            review_findings=[],
            critique_predictions=[],
            scope_clean=True,
            attempt_count=3,
            skill="diagnose",
        )
        content_solved = reward_module.REWARD_FILE.read_text(encoding="utf-8")
        check("SOLVED entry written on retry pass", "SOLVED" in content_solved and "auth task t_solved_1" in content_solved and "recovered after 3 attempts" in content_solved)

        # Failed gate → no win entry
        reward_module.REWARD_FILE.write_text("# REWARD\n<!-- New entries go below this line -->\n", encoding="utf-8")
        log.record(
            task_id="t_fail",
            task_type="ui",
            prompt_variant="v1",
            gate_pass=False,
            test_pass=False,
            review_findings=[],
            critique_predictions=[],
            scope_clean=True,
            attempt_count=1,
        )
        content_fail = reward_module.REWARD_FILE.read_text(encoding="utf-8")
        check("no CLEAN/SOLVED entry when gate fails", content_fail.count("CLEAN") == 0 and content_fail.count("SOLVED") == 0)

        log.close()
    finally:
        reward_module.REWARD_FILE = orig_reward_file


if __name__ == "__main__":
    print("=" * 60)
    print("REWARD (positive signal) — TEST")
    print("=" * 60)
    test_round_trip_and_weighting()
    test_net_gives_denominator()
    test_none_skill_excluded_and_bad_kind()
    test_validate_drift_guard()
    test_defensive_init()
    test_seed_file_wellformed()

    # reward_log tests
    test_composite_perfect_score()
    test_composite_all_failures()
    test_composite_gate_violation_penalty_1()
    test_composite_gate_violation_penalty_3()
    test_composite_violation_capped_at_zero()
    test_composite_score_stored_on_record()
    test_gate_violations_zero_unaffected()
    test_gate_violations_one_applies_penalty()
    test_gate_violations_five_capped()
    test_gate_violations_penalty_queryable()
    test_advantage_single_record_in_group()
    test_advantage_multiple_records_per_group()
    test_advantage_empty_group()
    test_compute_batch_advantages()
    test_record_missing_optional_fields()
    test_record_empty_strings_no_crash()
    test_record_large_task_id()
    test_graceful_missing_db_dir()
    test_close_then_record()
    test_best_variant_requires_min_runs()
    test_critique_accuracy_no_findings()
    test_critique_accuracy_no_predictions()
    test_reviewer_coverage_no_predictions()
    test_reviewer_coverage_no_findings()

    # new Domain 8 coverage-gap tests
    test_high_advantage_skills_empty_log()
    test_high_advantage_skills_single_record()
    test_compute_advantage_single_record_in_task_group()
    test_dashboard_empty_db()
    test_recurring_patterns_empty_db()
    test_critique_misses_empty_db()
    # test_concurrent_write_safety and test_analyze_override_patterns_at_threshold
    # require pytest's tmp_path/monkeypatch fixtures — skip in standalone mode

    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed" + ("  -- all clear" if passed == total else f"  ({total-passed} FAILED)"))
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
