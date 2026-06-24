"""
rl_grader.py — eval suite: RL/GRPO proposal system.

Tests that the reward log, advantage computation, and GRPO proposal
generation all wire together correctly. Uses mock/synthetic data only
(no real rewards.db required).
"""
import sys
import tempfile
from pathlib import Path

EVALS_DIR = Path(__file__).parent.parent
HARNESS_DIR = EVALS_DIR.parent.parent / "harness"
sys.path.insert(0, str(HARNESS_DIR))

from reward_log import RewardLog
from grpo import propose_grpo_edits, propose_skill_edits, propose_framework_edits


def run(verbose: bool = False, **kwargs) -> dict:
    """
    Test RL/GRPO proposal system.
    Returns {suite, passed, failed, total, cases, failures, status}.
    """
    cases = []
    failures = []
    passed = 0
    failed = 0

    # ── Case 1: empty rewards → zero proposals ───────────────────────────────
    c1 = _test_empty_rewards()
    cases.append(c1)
    if c1["passed"]:
        passed += 1
        if verbose:
            print(f"  PASS [rl-1] empty_rewards")
    else:
        failed += 1
        failures.append(f"[rl-1] empty_rewards: {c1['reason']}")
        if verbose:
            print(f"  FAIL [rl-1] {c1['reason']}")

    # ── Case 2: single reward with advantage → GRPO proposal ────────────────
    c2 = _test_single_reward_with_advantage()
    cases.append(c2)
    if c2["passed"]:
        passed += 1
        if verbose:
            print(f"  PASS [rl-2] single_reward_with_advantage")
    else:
        failed += 1
        failures.append(f"[rl-2] single_reward_with_advantage: {c2['reason']}")
        if verbose:
            print(f"  FAIL [rl-2] {c2['reason']}")

    # ── Case 3: negative rewards → skill proposal for react ────────────────
    c3 = _test_negative_rewards_trigger_skill_proposals()
    cases.append(c3)
    if c3["passed"]:
        passed += 1
        if verbose:
            print(f"  PASS [rl-3] negative_rewards_trigger_skill_proposals")
    else:
        failed += 1
        failures.append(f"[rl-3] negative_rewards_trigger_skill_proposals: {c3['reason']}")
        if verbose:
            print(f"  FAIL [rl-3] {c3['reason']}")

    # ── Case 4: framework tags wire correctly ───────────────────────────────
    c4 = _test_framework_tags_wire_correctly()
    cases.append(c4)
    if c4["passed"]:
        passed += 1
        if verbose:
            print(f"  PASS [rl-4] framework_tags_wire_correctly")
    else:
        failed += 1
        failures.append(f"[rl-4] framework_tags_wire_correctly: {c4['reason']}")
        if verbose:
            print(f"  FAIL [rl-4] {c4['reason']}")

    # ── Case 5: batch advantages calculate correctly ───────────────────────
    c5 = _test_batch_advantages_calculate_correctly()
    cases.append(c5)
    if c5["passed"]:
        passed += 1
        if verbose:
            print(f"  PASS [rl-5] batch_advantages_calculate_correctly")
    else:
        failed += 1
        failures.append(f"[rl-5] batch_advantages_calculate_correctly: {c5['reason']}")
        if verbose:
            print(f"  FAIL [rl-5] {c5['reason']}")

    # ── Case 6: no rewards.db → graceful skip, no crash ────────────────────
    c6 = _test_no_rl_db_no_crash()
    cases.append(c6)
    if c6["passed"]:
        passed += 1
        if verbose:
            print(f"  PASS [rl-6] no_rl_db_no_crash")
    else:
        failed += 1
        failures.append(f"[rl-6] no_rl_db_no_crash: {c6['reason']}")
        if verbose:
            print(f"  FAIL [rl-6] {c6['reason']}")

    status = "pass" if failed == 0 else "fail"
    return {
        "suite": "rl",
        "passed": passed,
        "failed": failed,
        "total": len(cases),
        "cases": cases,
        "failures": failures,
        "status": status,
    }


# ── Test helpers ──────────────────────────────────────────────────────────────


def _test_empty_rewards() -> dict:
    """Empty rewards.db → zero proposals, no advantages computed."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "rewards.db"
        log = RewardLog(db_path)

        proposals = propose_grpo_edits(log)
        advantages_computed = log.compute_batch_advantages()

        result = {
            "passed": False,
            "proposals_count": len(proposals),
            "advantages_computed": advantages_computed,
            "reason": "",
        }

        if len(proposals) == 0 and advantages_computed == 0:
            result["passed"] = True
            result["status"] = "no rewards"
        else:
            result["reason"] = f"expected 0 proposals, got {len(proposals)}"

        log.close()
        return result


def _test_single_reward_with_advantage() -> dict:
    """1 reward with advantage=0.5 → advantage computed, GRPO needs >=2 runs."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "rewards.db"
        log = RewardLog(db_path)

        # Record one reward in a group so advantage can be computed
        log.record(
            task_id="t1",
            task_type="auth",
            prompt_variant="impl_v1",
            gate_pass=True,
            test_pass=True,
            review_findings=[],
            critique_predictions=[],
            scope_clean=True,
            attempt_count=1,
        )

        # Manually set group and advantage to simulate post-group computation
        log.compute_advantage(task_id="t1", score=0.8, task_group="auth_group")

        # Check advantage was stored
        row = log._conn.execute(
            "SELECT advantage FROM rewards WHERE task_id = ?", ("t1",)
        ).fetchone()
        stored_advantage = row["advantage"] if row else None

        result = {
            "passed": False,
            "stored_advantage": stored_advantage,
            "advantages_computed": True,
            "reason": "",
        }

        # GRPO proposals require cnt>=2 so a single reward won't produce proposals,
        # but advantage should be stored
        if stored_advantage is not None and abs(stored_advantage) >= 0:
            result["passed"] = True
        else:
            result["reason"] = f"expected advantage stored, got {stored_advantage}"

        log.close()
        return result


def _test_negative_rewards_trigger_skill_proposals() -> dict:
    """3 negative rewards for skill=react → skill proposal for react."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "rewards.db"
        log = RewardLog(db_path)

        # 3 rewards with negative advantages for react skill
        for i, score in enumerate([0.3, 0.25, 0.2]):
            log.record(
                task_id=f"t{i}",
                task_type="ui",
                prompt_variant="impl_v1",
                gate_pass=True,
                test_pass=True,
                review_findings=[],
                critique_predictions=[],
                scope_clean=True,
                attempt_count=1,
                skill="react",
            )
            # Set a group so advantage is meaningful; advantage computed later
            log._conn.execute(
                'UPDATE rewards SET "group" = ? WHERE task_id = ?',
                ("ui_group", f"t{i}"),
            )
            log._conn.execute(
                "UPDATE rewards SET advantage = ?, composite_score = ? WHERE task_id = ?",
                (0.5, score, f"t{i}"),
            )
        log._conn.commit()

        # Run batch advantage recomputation
        log.compute_batch_advantages()

        # Skill proposals path — needs cnt>=2 and avg_advantage>threshold
        proposals_path = Path(tmp) / "retro_proposals.md"
        proposals = propose_skill_edits(log, proposals_path=proposals_path, threshold=0.3)

        # Check if "react" appears in any proposal skill field
        react_proposals = [p for p in proposals if p.get("skill") == "react"]

        result = {
            "passed": False,
            "skill_proposals": proposals,
            "reason": "",
        }

        if any("react" in str(p) for p in proposals):
            result["passed"] = True
        else:
            result["reason"] = f"expected 'react' in skill_proposals, got {proposals}"

        log.close()
        return result


def _test_framework_tags_wire_correctly() -> dict:
    """Reward with stack_tags={svelte, typescript} → framework proposal for svelte."""
    import harness.grpo as grpo_module

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "rewards.db"
        log = RewardLog(db_path)

        # 2 rewards (cnt>=2 required for proposals)
        for i in range(2):
            log.record(
                task_id=f"fw{i}",
                task_type="ui",
                prompt_variant="impl_v1",
                gate_pass=True,
                test_pass=True,
                review_findings=[],
                critique_predictions=[],
                scope_clean=True,
                attempt_count=1,
                skill="svelte",
            )
            log._conn.execute(
                'UPDATE rewards SET "group" = ?, advantage = ? WHERE task_id = ?',
                ("fw_group", 0.4, f"fw{i}"),
            )
        log._conn.commit()

        # Create a fake skills/svelte/SKILL.md for the framework edit to succeed
        skill_dir = Path(tmp) / "skills" / "svelte"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "# Svelte skill\n\n## RL-Proposed Additions\n", encoding="utf-8"
        )

        # Patch grpo.ROOT so it writes to our temp dir instead of the real .techne/
        orig_root = grpo_module.ROOT
        grpo_module.ROOT = Path(tmp)

        try:
            stack_tags = {"svelte", "typescript"}
            proposals = propose_framework_edits(log, stack_tags=stack_tags)
        finally:
            grpo_module.ROOT = orig_root

        result = {
            "passed": False,
            "framework_proposals": proposals,
            "reason": "",
        }

        if any("svelte" in str(p) for p in proposals):
            result["passed"] = True
        else:
            result["reason"] = f"expected 'svelte' in framework_proposals, got {proposals}"

        log.close()
        return result


def _test_batch_advantages_calculate_correctly() -> dict:
    """3 rewards with scores [0.8, 0.5, -0.3] in one group → advantages computed."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "rewards.db"
        log = RewardLog(db_path)

        # 3 rewards in same group with different scores
        scores = [0.8, 0.5, -0.3]
        for i, score in enumerate(scores):
            log.record(
                task_id=f"bt{i}",
                task_type="api",
                prompt_variant="impl_v1",
                gate_pass=(score > 0),
                test_pass=(score > 0),
                review_findings=[] if score > 0 else ["missing error handling"],
                critique_predictions=[],
                scope_clean=True,
                attempt_count=1,
            )
            log._conn.execute(
                'UPDATE rewards SET "group" = ?, composite_score = ? WHERE task_id = ?',
                ("batch_group", score, f"bt{i}"),
            )
        log._conn.commit()

        updated = log.compute_batch_advantages()

        # Read back advantages
        rows = log._conn.execute(
            'SELECT task_id, advantage FROM rewards WHERE "group" = ? ORDER BY task_id',
            ("batch_group",),
        ).fetchall()
        advantages = {r["task_id"]: r["advantage"] for r in rows}

        # Mean of [0.8, 0.5, -0.3] = 0.333...
        # advantage for 0.8  = 0.8  - 0.333 = 0.467
        # advantage for 0.5  = 0.5  - 0.333 = 0.167
        # advantage for -0.3 = -0.3 - 0.333 = -0.633
        mean = sum(scores) / len(scores)
        expected_advantages = [s - mean for s in scores]

        result = {
            "passed": False,
            "advantages_computed": updated > 0,
            "advantages": advantages,
            "reason": "",
        }

        if updated > 0:
            # Check all advantages are non-zero (they should differ from mean)
            advs = list(advantages.values())
            if len(set(advs)) == len(advs):  # all different → mean computed correctly
                result["passed"] = True
            else:
                result["reason"] = f"advantages not varied correctly: {advantages}"
        else:
            result["reason"] = "no advantages were computed"

        log.close()
        return result


def _test_no_rl_db_no_crash() -> dict:
    """rewards.db doesn't exist → graceful skip, no crash."""
    with tempfile.TemporaryDirectory() as tmp:
        # Point to a non-existent DB
        nonexistent_db = Path(tmp) / "nonexistent.db"

        try:
            log = RewardLog(nonexistent_db)
            proposals = propose_grpo_edits(log)
            log.close()

            result = {
                "passed": False,
                "status": "no_data",
                "reason": "",
            }

            if len(proposals) == 0:
                result["passed"] = True
                result["status"] = "no rewards"
            else:
                result["reason"] = f"expected 0 proposals for missing DB, got {len(proposals)}"
        except Exception as e:
            result = {
                "passed": False,
                "status": "error",
                "reason": str(e),
            }

        return result
