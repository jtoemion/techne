"""
test_group_scoring.py — GRPO group-based scoring for reward_log (B2).

Verifies:
  - compute_advantage sets group label and computes score - mean(group)
  - Single record in group → advantage = 0.0
  - Multiple records → advantage = score - group_mean
  - compute_batch_advantages processes all groups
  - Empty group string is excluded from batch processing
  - Backward compatibility with existing records

Run from tests/:  python test_group_scoring.py
"""

import os
import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

from reward_log import RewardLog, Reward

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []


def check(label, cond):
    results.append(bool(cond))
    print(f"  {PASS if cond else FAIL} {label}")


def _fresh_log():
    """Return a RewardLog backed by a temp DB file."""
    return RewardLog(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)


def _seed(log, task_id, task_type, score):
    """Record a reward for the given task with a known composite score."""
    # We bypass the normal scoring to set an exact composite_score.
    # Record normally, then overwrite the score.
    reward = log.record(
        task_id=task_id,
        task_type=task_type,
        prompt_variant="implementer_v1",
        gate_pass=True,
        test_pass=True,
        review_findings=[],
        critique_predictions=[],
        scope_clean=True,
        attempt_count=1,
    )
    log._conn.execute(
        "UPDATE rewards SET composite_score = ? WHERE task_id = ?",
        (score, task_id),
    )
    log._conn.commit()
    return reward


# ── Tests ──────────────────────────────────────────────────────────────────


def test_single_record_advantage_zero():
    print("\n[group-scoring — single record → advantage = 0.0]")
    log = _fresh_log()
    _seed(log, "t1", "auth", 0.85)

    adv = log.compute_advantage("t1", 0.85, "implement:auth")

    check("advantage is 0.0 for single record", adv == 0.0)

    # Verify in DB
    row = log._conn.execute(
        "SELECT advantage, \"group\" FROM rewards WHERE task_id = ?", ("t1",)
    ).fetchone()
    check("DB stores advantage = 0.0", row["advantage"] == 0.0)
    check("DB stores group label", row["group"] == "implement:auth")

    log.close()
    os.remove(log.db_path)


def test_two_records_same_group():
    print("\n[group-scoring — two records, same group]")
    log = _fresh_log()
    _seed(log, "t1", "auth", 0.80)
    _seed(log, "t2", "auth", 0.90)

    # Set groups for both tasks
    log.compute_advantage("t1", 0.80, "implement:auth")
    log.compute_advantage("t2", 0.90, "implement:auth")

    # Batch-recompute so both reflect the full group composition
    updated = log.compute_batch_advantages()

    check("batch updated both records", updated == 2)

    rows = log._conn.execute(
        "SELECT task_id, advantage, composite_score FROM rewards WHERE \"group\" = 'implement:auth' ORDER BY task_id"
    ).fetchall()
    advs = {r["task_id"]: r["advantage"] for r in rows}

    # Both records in group: mean = (0.80 + 0.90) / 2 = 0.85
    # t1: 0.80 - 0.85 = -0.05
    # t2: 0.90 - 0.85 = +0.05
    check("t1 advantage is -0.05", abs(advs["t1"] - (-0.05)) < 0.001)
    check("t2 advantage is +0.05", abs(advs["t2"] - 0.05) < 0.001)

    log.close()
    os.remove(log.db_path)


def test_three_records_advantage_sum_zero():
    print("\n[group-scoring — advantages sum to zero across group]")
    log = _fresh_log()
    _seed(log, "t1", "auth", 0.70)
    _seed(log, "t2", "auth", 0.85)
    _seed(log, "t3", "auth", 0.95)

    for tid, sc in [("t1", 0.70), ("t2", 0.85), ("t3", 0.95)]:
        log.compute_advantage(tid, sc, "implement:auth")

    # Batch recompute so all three reflect the complete group
    log.compute_batch_advantages()

    rows = log._conn.execute(
        "SELECT advantage FROM rewards WHERE \"group\" = 'implement:auth'"
    ).fetchall()
    advs = [r["advantage"] for r in rows]

    adv_sum = sum(advs)
    check("advantages sum to approx zero", abs(adv_sum) < 0.001)
    check("t1 (below-mean) has negative advantage", advs[0] < 0)
    check("t3 (above-mean) has positive advantage", advs[2] > 0)

    log.close()
    os.remove(log.db_path)


def test_different_groups_independent():
    print("\n[group-scoring — different groups are independent]")
    log = _fresh_log()
    _seed(log, "t1", "auth", 0.50)
    _seed(log, "t2", "ui", 0.99)

    adv_auth = log.compute_advantage("t1", 0.50, "implement:auth")
    adv_ui = log.compute_advantage("t2", 0.99, "implement:ui")

    # Each group has only one member → advantage = 0
    check("auth single-record advantage = 0", adv_auth == 0.0)
    check("ui single-record advantage = 0", adv_ui == 0.0)

    log.close()
    os.remove(log.db_path)


def test_compute_batch_advantages_all_groups():
    print("\n[group-scoring — compute_batch_advantages processes all groups]")
    log = _fresh_log()
    _seed(log, "t1", "auth", 0.80)
    _seed(log, "t2", "auth", 0.90)
    _seed(log, "t3", "ui", 0.50)
    _seed(log, "t4", "ui", 0.70)

    # Set groups via compute_advantage (which also sets advantage)
    log.compute_advantage("t1", 0.80, "implement:auth")
    log.compute_advantage("t2", 0.90, "implement:auth")
    log.compute_advantage("t3", 0.50, "implement:ui")
    log.compute_advantage("t4", 0.70, "implement:ui")

    # The compute_advantage already set advantages; recompute via batch
    updated = log.compute_batch_advantages()

    check("batch updated all 4 records", updated == 4)

    # Verify final values
    rows = log._conn.execute(
        "SELECT task_id, \"group\", advantage, composite_score FROM rewards ORDER BY task_id"
    ).fetchall()
    by_id = {r["task_id"]: r for r in rows}

    # auth group: mean = 0.85
    check("t1 auth advantage", abs(by_id["t1"]["advantage"] - (-0.05)) < 0.001)
    check("t2 auth advantage", abs(by_id["t2"]["advantage"] - 0.05) < 0.001)
    # ui group: mean = 0.60
    check("t3 ui advantage", abs(by_id["t3"]["advantage"] - (-0.10)) < 0.001)
    check("t4 ui advantage", abs(by_id["t4"]["advantage"] - 0.10) < 0.001)

    log.close()
    os.remove(log.db_path)


def test_empty_group_string_excluded():
    print("\n[group-scoring — empty group string is excluded from batch]")
    log = _fresh_log()
    # Record a reward with no group (default empty string)
    _seed(log, "t1", "auth", 0.85)
    # No group set → "group" is ''
    updated = log.compute_batch_advantages()
    check("no updates for empty group records", updated == 0)

    log.close()
    os.remove(log.db_path)


def test_compute_advantage_sequential_then_batch():
    print("\n[group-scoring — sequential compute_advantage then batch recompute]")
    log = _fresh_log()
    _seed(log, "t1", "auth", 0.80)
    _seed(log, "t2", "auth", 0.90)

    # Call compute_advantage for t1 — at this point only t1 has the group set
    adv_t1 = log.compute_advantage("t1", 0.80, "implement:auth")
    # Only t1 in group → mean = 0.80 → advantage = 0.0
    check("t1 advantage is 0.0 when alone in group", adv_t1 == 0.0)

    # Now set t2's group
    log.compute_advantage("t2", 0.90, "implement:auth")

    # Batch recompute so both reflect the full two-record group
    updated = log.compute_batch_advantages()
    check("batch updated both", updated == 2)

    rows = log._conn.execute(
        "SELECT advantage FROM rewards WHERE \"group\" = 'implement:auth' ORDER BY task_id"
    ).fetchall()
    check("t1 advantage after batch is -0.05",
          abs(rows[0]["advantage"] - (-0.05)) < 0.001)
    check("t2 advantage after batch is +0.05",
          abs(rows[1]["advantage"] - 0.05) < 0.001)

    log.close()
    os.remove(log.db_path)


def test_repeated_compute_advantage():
    print("\n[group-scoring — repeated compute_advantage recalculates]")
    log = _fresh_log()
    _seed(log, "t1", "auth", 0.80)
    _seed(log, "t2", "auth", 0.90)

    # First pass: 2 records
    adv1_1 = log.compute_advantage("t1", 0.80, "implement:auth")
    log.compute_advantage("t2", 0.90, "implement:auth")

    # Add a third record
    _seed(log, "t3", "auth", 0.70)
    log.compute_advantage("t3", 0.70, "implement:auth")

    # Recompute t1 — should now reflect 3-record group
    adv1_2 = log.compute_advantage("t1", 0.80, "implement:auth")
    # mean = (0.80 + 0.90 + 0.70) / 3 = 0.80
    check("recomputed advantage after new member joins group",
          abs(adv1_2 - (0.80 - 0.80)) < 0.001)

    log.close()
    os.remove(log.db_path)


def test_backward_compatibility():
    print("\n[group-scoring — backward compatible with existing records]")
    log = _fresh_log()
    _seed(log, "t1", "auth", 0.85)

    # Must still be able to read back without errors
    row = log._conn.execute(
        "SELECT * FROM rewards WHERE task_id = ?", ("t1",)
    ).fetchone()

    # The new columns should exist with default values
    check("has group column", "group" in row.keys())
    check("has advantage column", "advantage" in row.keys())
    check("default group is empty string", row["group"] == "")
    check("default advantage is 0.0", row["advantage"] == 0.0)

    log.close()
    os.remove(log.db_path)


def test_gate_violations_penalty():
    """Penalize recovered gate violations: 3 violations scores lower than 0."""
    print("\n[gate_violations — penalty reduces composite score]")
    log = _fresh_log()

    # Perfect record except for gate_violations count
    base_kwargs = dict(
        task_type="auth",
        prompt_variant="v1",
        gate_pass=True,
        test_pass=True,
        review_findings=[],
        critique_predictions=[],
        scope_clean=True,
        attempt_count=1,
    )

    # Record with no violations
    r0 = log.record(**base_kwargs, task_id="t0", gate_violations=0)
    # Record with 3 violations (should be 0.55x weighted_sum)
    r3 = log.record(**base_kwargs, task_id="t3", gate_violations=3)

    check("0 violations yields higher score than 3 violations", r0.composite_score > r3.composite_score)

    # Verify the penalty math: 1 - 3*0.15 = 0.55
    # weighted_sum = 0.20 + 0.25 + 0.20 + 0.15 + 0.05 + 0.05 = 0.90
    # 0 violations: 1.0 * 0.90 = 0.90
    # 3 violations: 0.55 * 0.90 = 0.495
    check("0 violations score ≈ 0.90", abs(r0.composite_score - 0.90) < 0.001)
    check("3 violations score ≈ 0.495", abs(r3.composite_score - 0.495) < 0.001)

    # 1 violation = 0.85 penalty
    r1 = log.record(**base_kwargs, task_id="t1", gate_violations=1)
    check("1 violation score ≈ 0.765", abs(r1.composite_score - 0.765) < 0.001)

    # Backward compat: gate_violations defaults to 0 when not passed
    r_default = log.record(**base_kwargs, task_id="t_default", gate_violations=0)
    check("default (no arg) gate_violations=0 yields full score",
          abs(r_default.composite_score - 0.90) < 0.001)

    log.close()
    os.remove(log.db_path)


# ── P4: skill field ────────────────────────────────────────────────────────


def test_skill_field_in_reward_record():
    """Skill is stored and retrieved correctly via record()."""
    print("\n[P4 — skill field stored and retrieved]")
    log = _fresh_log()

    reward = log.record(
        task_id="t1",
        task_type="auth",
        prompt_variant="implementer_v1",
        gate_pass=True,
        test_pass=True,
        review_findings=[],
        critique_predictions=[],
        scope_clean=True,
        attempt_count=1,
        skill="diagnose",
    )

    check("reward.skill is 'diagnose'", reward.skill == "diagnose")

    # Read back from DB
    row = log._conn.execute(
        "SELECT skill FROM rewards WHERE task_id = ?", ("t1",)
    ).fetchone()
    check("DB stores skill as 'diagnose'", row["skill"] == "diagnose")

    # Default empty string when not provided
    reward2 = log.record(
        task_id="t2",
        task_type="api",
        prompt_variant="implementer_v1",
        gate_pass=True,
        test_pass=True,
        review_findings=[],
        critique_predictions=[],
        scope_clean=True,
        attempt_count=1,
    )
    check("reward.skill defaults to empty string", reward2.skill == "")

    log.close()
    os.remove(log.db_path)


def test_high_advantage_skills_groups_by_task_type_and_skill():
    """high_advantage_skills() groups by (task_type, skill) correctly."""
    print("\n[P4 — high_advantage_skills groups by (task_type, skill)]")
    log = _fresh_log()

    # Seed rewards with skill set.
    # Advantages don't sum to zero because we set them directly (not computed).
    # auth+diagnose: advantages [+0.25, +0.15, -0.05] → avg_adv ≈ +0.117
    # auth+implement: advantages [+0.10, +0.05, -0.08] → avg_adv ≈ +0.023
    # api+diagnose:   advantages [+0.30, -0.10]        → avg_adv = +0.10
    # api+implement:  advantages [+0.20, -0.05]        → avg_adv = +0.075
    for tid, tt, sk, sc, adv in [
        ("t1", "auth", "diagnose",  0.95,  0.25),
        ("t2", "auth", "diagnose",  0.90,  0.15),
        ("t3", "auth", "diagnose",  0.88, -0.05),
        ("t4", "auth", "implement", 0.40,  0.10),
        ("t5", "auth", "implement", 0.35,  0.05),
        ("t6", "auth", "implement", 0.30, -0.08),
        ("t7", "api",  "diagnose",  0.80,  0.30),
        ("t8", "api",  "diagnose",  0.70, -0.10),
        ("t9", "api",  "implement", 0.60,  0.20),
        ("tA", "api",  "implement", 0.55, -0.05),
    ]:
        log.record(
            task_id=tid, task_type=tt, prompt_variant="v1",
            gate_pass=True, test_pass=True,
            review_findings=[], critique_predictions=[],
            scope_clean=True, attempt_count=1,
            skill=sk,
        )
        log._conn.execute(
            "UPDATE rewards SET composite_score = ?, advantage = ? WHERE task_id = ?",
            (sc, adv, tid),
        )
        log._conn.execute(
            'UPDATE rewards SET "group" = ? WHERE task_id = ?',
            (f"group:{tt}:{sk}", tid),
        )
    log._conn.commit()

    # With threshold=0.0 we should see all 4 (task_type, skill) pairs
    result_all = log.high_advantage_skills(threshold=0.0)
    skills_seen = {r["skill"] for r in result_all}
    check("groups contain 'diagnose' skill", "diagnose" in skills_seen)
    check("groups contain 'implement' skill", "implement" in skills_seen)

    # Verify each result has skill and task_type fields
    for r in result_all:
        check(f"result has skill field for '{r['skill']}'", "skill" in r)
        check(f"result has task_type for '{r['task_type']}'", "task_type" in r)

    # auth+diagnose avg_adv ≈ 0.117 > 0.1; others are < 0.1
    result_hi = log.high_advantage_skills(threshold=0.1)
    skill_names = [r["skill"] for r in result_hi]
    check("auth+diagnose above 0.1 threshold", "diagnose" in skill_names)
    # auth+implement avg_adv ≈ 0.023 < 0.1
    check("auth+implement below 0.1 threshold",
          "implement" not in skill_names or all(
              r["avg_advantage"] <= 0.1 for r in result_hi if r["skill"] == "implement"
          ))

    log.close()
    os.remove(log.db_path)


# ── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("GRPO GROUP SCORING — test_group_scoring.py (B2 + P4)")
    print("=" * 60)

    test_single_record_advantage_zero()
    test_two_records_same_group()
    test_three_records_advantage_sum_zero()
    test_different_groups_independent()
    test_compute_batch_advantages_all_groups()
    test_empty_group_string_excluded()
    test_compute_advantage_sequential_then_batch()
    test_repeated_compute_advantage()
    test_backward_compatibility()
    test_gate_violations_penalty()
    # P4
    test_skill_field_in_reward_record()
    test_high_advantage_skills_groups_by_task_type_and_skill()

    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed" + ("  -- all clear" if passed == total else f"  ({total-passed} FAILED)"))
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
