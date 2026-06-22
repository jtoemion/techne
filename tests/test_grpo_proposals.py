"""
test_grpo_proposals.py — Tests for the GRPO-to-retro_proposals connector (B3).

Verifies:
  - high_advantage_variants() returns variants above threshold
  - propose_grpo_edits() writes PROPOSE ADD entries in retro_proposals.md
  - Written proposals are parseable by apply_retro.parse_proposals()
  - Dedup: same variant does not produce duplicate proposals
  - Low-advantage variants (below threshold) produce no proposals
  - Empty reward log produces no proposals

Run from tests/:  python test_grpo_proposals.py
"""

import os
import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

from reward_log import RewardLog
from grpo import (
    propose_grpo_edits, propose_skill_edits,
    ADVANTAGE_THRESHOLD, DEFAULT_SKILL_FILE,
)
import apply_retro as ar

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []


def check(label, cond):
    results.append(bool(cond))
    print(f"  {PASS if cond else FAIL} {label}")


def _fresh_log():
    """Return a RewardLog backed by a temp DB file."""
    return RewardLog(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)


def _seed_with_group(log, task_id, task_type, score, variant="v1_strict", group="implement:auth"):
    """Record a reward and set its group + composite_score."""
    reward = log.record(
        task_id=task_id,
        task_type=task_type,
        prompt_variant=variant,
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
    log._conn.execute(
        'UPDATE rewards SET "group" = ? WHERE task_id = ?',
        (group, task_id),
    )
    log._conn.commit()


def test_high_advantage_variants_empty():
    """Empty log returns empty list."""
    print("\n[grpo — high_advantage_variants with empty log]")
    log = _fresh_log()
    result = log.high_advantage_variants(threshold=0.2)
    check("returns empty list from empty log", len(result) == 0)
    log.close()
    os.remove(log.db_path)


def test_high_advantage_variants_below_threshold():
    """Variants with advantage below threshold are not returned."""
    print("\n[grpo — variants below threshold excluded]")
    log = _fresh_log()
    # Two records, same group, both close scores
    _seed_with_group(log, "t1", "auth", 0.51, variant="v1", group="implement:auth")
    _seed_with_group(log, "t2", "auth", 0.49, variant="v2", group="implement:auth")
    log.compute_batch_advantages()

    result = log.high_advantage_variants(threshold=0.2)
    # mean=0.5, advantages are tiny (+/- 0.01), well below 0.2
    check("no variants above 0.2 threshold", len(result) == 0)
    log.close()
    os.remove(log.db_path)


def test_high_advantage_variants_above_threshold():
    """Variant with high advantage is returned."""
    print("\n[grpo — variant with high advantage detected]")
    log = _fresh_log()
    # v1 scores 0.95 x2, v2 scores 0.10 → mean=0.667 → v1 advantage=+0.283 > 0.2
    _seed_with_group(log, "t1", "auth", 0.95, variant="v1", group="implement:auth")
    _seed_with_group(log, "t2", "auth", 0.95, variant="v1", group="implement:auth")
    _seed_with_group(log, "t3", "auth", 0.10, variant="v2", group="implement:auth")
    log.compute_batch_advantages()

    result = log.high_advantage_variants(threshold=0.2)
    check("v1 appears with high advantage",
          any(r["prompt_variant"] == "v1" and r["avg_advantage"] > 0.2 for r in result))
    check("v2 (low advantage) does not appear",
          not any(r["prompt_variant"] == "v2" for r in result))
    log.close()
    os.remove(log.db_path)


def test_propose_grpo_edits_writes_parseable_proposals():
    """propose_grpo_edits writes proposals parseable by apply_retro.parse_proposals()."""
    print("\n[grpo — proposals written are parseable]")
    log = _fresh_log()
    _seed_with_group(log, "t1", "auth", 0.95, variant="v1", group="implement:auth")
    _seed_with_group(log, "t2", "auth", 0.95, variant="v1", group="implement:auth")
    _seed_with_group(log, "t3", "auth", 0.10, variant="v2", group="implement:auth")
    log.compute_batch_advantages()

    tmp_proposals = tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w")
    tmp_proposals.close()
    tmp_path = Path(tmp_proposals.name)

    try:
        proposals = propose_grpo_edits(log, proposals_path=tmp_path, threshold=0.2)

        check("proposals were written", len(proposals) > 0)

        # Read back and parse
        content = tmp_path.read_text(encoding="utf-8")
        parsed = ar.parse_proposals(content)

        check("parse_proposals returns at least one proposal", len(parsed) > 0)
        check("first proposal type is ADD", parsed[0]["type"] == "ADD")
        check("first proposal target contains skills/implementer.md",
              "skills/implementer.md" in parsed[0]["target"])
        check("first proposal has text content",
              len(parsed[0]["text"].strip()) > 0)
        check("first proposal is not marked applied", not parsed[0]["applied"])

        # Verify the weight line is present in raw
        check("raw content includes # weight:",
              "# weight:" in parsed[0]["raw"])

        # Verify text includes variant name
        check("proposal text mentions prompt_variant 'v1'",
              "v1" in parsed[0]["text"])

    finally:
        log.close()
        os.remove(log.db_path)
        if tmp_path.exists():
            tmp_path.unlink()


def test_propose_grpo_edits_dedup():
    """Same variant should not produce duplicate proposals."""
    print("\n[grpo — dedup: same variant not proposed twice]")
    log = _fresh_log()
    _seed_with_group(log, "t1", "auth", 0.95, variant="v1", group="implement:auth")
    _seed_with_group(log, "t2", "auth", 0.95, variant="v1", group="implement:auth")
    _seed_with_group(log, "t3", "auth", 0.10, variant="v2", group="implement:auth")
    log.compute_batch_advantages()

    tmp_proposals = tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w")
    tmp_proposals.close()
    tmp_path = Path(tmp_proposals.name)

    try:
        # First call should write proposals
        proposals1 = propose_grpo_edits(log, proposals_path=tmp_path, threshold=0.2)
        check("first call writes proposals", len(proposals1) > 0)

        # Second call should produce no new proposals (already exists)
        proposals2 = propose_grpo_edits(log, proposals_path=tmp_path, threshold=0.2)
        check("second call produces no duplicate proposals", len(proposals2) == 0)

        # The file should have exactly one PROPOSE ADD (not two)
        content = tmp_path.read_text(encoding="utf-8")
        count_add = content.count("### PROPOSE ADD")
        check("only one PROPOSE ADD in file after dedup", count_add == 1)

    finally:
        log.close()
        os.remove(log.db_path)
        if tmp_path.exists():
            tmp_path.unlink()


def test_propose_grpo_edits_low_advantage():
    """No proposals written when no variants meet threshold."""
    print("\n[grpo — low advantage produces no proposals]")
    log = _fresh_log()
    _seed_with_group(log, "t1", "auth", 0.51, variant="v1", group="implement:auth")
    _seed_with_group(log, "t2", "auth", 0.49, variant="v2", group="implement:auth")
    log.compute_batch_advantages()

    tmp_proposals = tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w")
    tmp_proposals.close()
    tmp_path = Path(tmp_proposals.name)

    try:
        proposals = propose_grpo_edits(log, proposals_path=tmp_path, threshold=0.2)
        check("no proposals for low-advantage variants", len(proposals) == 0)

        # File should be empty (or just header)
        content = tmp_path.read_text(encoding="utf-8")
        check("no PROPOSE ADD in file", "### PROPOSE ADD" not in content)

    finally:
        log.close()
        os.remove(log.db_path)
        if tmp_path.exists():
            tmp_path.unlink()


def test_propose_grpo_edits_no_group():
    """Variants without group labels are not considered."""
    print("\n[grpo — variants without group label excluded]")
    log = _fresh_log()
    # These have empty group (default), so high_advantage_variants ignores them
    _seed_with_group(log, "t1", "auth", 0.95, variant="v1", group="")

    # Manually set empty group
    log._conn.execute(
        'UPDATE rewards SET "group" = ? WHERE task_id = ?',
        ("", "t1"),
    )
    log._conn.commit()

    # compute_batch_advantages skips empty groups
    log.compute_batch_advantages()

    result = log.high_advantage_variants(threshold=0.2)
    check("no variants without group", len(result) == 0)

    log.close()
    os.remove(log.db_path)


def test_propose_grpo_edits_requires_two_runs():
    """Single-run variant does not qualify even with high score."""
    print("\n[grpo — single-run variant excluded]")
    log = _fresh_log()
    # Only one record in this group (mean = score, advantage = 0)
    _seed_with_group(log, "t1", "auth", 0.95, variant="v1", group="implement:auth")
    log.compute_batch_advantages()

    result = log.high_advantage_variants(threshold=0.2)
    check("single-run variant not returned", len(result) == 0)

    log.close()
    os.remove(log.db_path)


def test_apply_retro_parses_grpo_format():
    """The exact format emitted by propose_grpo_edits must be parseable
    by apply_retro.parse_proposals() — this is the contract."""
    print("\n[grpo — apply_retro.parse_proposals parses the emitted format]")
    from grpo import propose_grpo_edits

    log = _fresh_log()
    _seed_with_group(log, "t1", "auth", 0.95, variant="v1_strict", group="implement:auth")
    _seed_with_group(log, "t2", "auth", 0.95, variant="v1_strict", group="implement:auth")
    _seed_with_group(log, "t3", "auth", 0.10, variant="v2_pragmatic", group="implement:auth")
    log.compute_batch_advantages()

    tmp_proposals = tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w")
    tmp_proposals.close()
    tmp_path = Path(tmp_proposals.name)

    try:
        written = propose_grpo_edits(log, proposals_path=tmp_path, threshold=0.2)
        check("proposals written", len(written) > 0)

        content = tmp_path.read_text(encoding="utf-8")
        parsed = ar.parse_proposals(content)

        check("parse_proposals returns entries", len(parsed) > 0)
        for i, p in enumerate(parsed):
            check(f"proposal {i} has type={p['type']}", p["type"] in ("ADD", "DELETE", "RESOLVE"))
            check(f"proposal {i} has non-empty target", bool(p.get("target", "")))
            if p["type"] == "ADD":
                check(f"proposal {i} has non-empty text", bool(p.get("text", "")))
            check(f"proposal {i} has date", bool(p.get("date", "")))

    finally:
        log.close()
        os.remove(log.db_path)
        if tmp_path.exists():
            tmp_path.unlink()


# ── B3: end-to-end write proof ─────────────────────────────────────────────

def test_b3_end_to_end_write():
    """Proves an approved GRPO proposal actually modifies a skills/*.md file
    — not just a new row in proposals.json or an in-memory dict."""
    print("\n[B3 — apply_add writes to real skills file + marks applied]")
    import tempfile, os, json
    from pathlib import Path

    tmpdir = tempfile.mkdtemp()
    try:
        skills_dir = Path(tmpdir) / "skills"
        skills_dir.mkdir(parents=True)
        memory_dir = Path(tmpdir) / ".techne" / "memory"
        memory_dir.mkdir(parents=True)

        # 1. Create target skill file with known content
        skill_file = skills_dir / "test.md"
        skill_file.write_text("# Test Skill\n\nExisting content.\n")

        # 2. Create proposals file with a PROPOSE ADD entry
        proposals_file = memory_dir / "retro_proposals.md"
        proposals_content = """# Retro Proposals

## Retro — 2026-01-01T00:00:00Z

### PROPOSE ADD to skills/test.md
# weight: 0.283 | seen: 2x | score: 0.950
GRPO Advantage-sourced edit from prompt variant **v1**

New content to append.
"""
        proposals_file.write_text(proposals_content)

        # 3. Monkey-patch apply_retro paths to point at temp dir
        original = {
            "ROOT": ar.ROOT,
            "SKILLS_DIR": ar.SKILLS_DIR,
            "MEMORY_DIR": ar.MEMORY_DIR,
            "PROPOSALS_FILE": ar.PROPOSALS_FILE,
        }
        try:
            ar.ROOT = Path(tmpdir)
            ar.SKILLS_DIR = skills_dir
            ar.MEMORY_DIR = memory_dir
            ar.PROPOSALS_FILE = proposals_file

            # 4. Parse proposals
            parsed = ar.parse_proposals(proposals_content)
            check("parse_proposals returns 1 proposal", len(parsed) == 1)
            proposal = parsed[0]
            check("proposal type is ADD", proposal["type"] == "ADD")
            check("proposal target is skills/test.md", "skills/test.md" in proposal["target"])
            check("proposal is NOT yet applied", not proposal["applied"])

            # 5. Call apply_add directly (bypasses human gate — fine for unit test)
            ok, reason = ar.apply_add(proposal)
            check("apply_add succeeded", ok)
            check("reason mentions appended lines", "Appended" in reason)

            # 6. Assert the skill file's content changed
            new_content = skill_file.read_text(encoding="utf-8")
            check("file now contains proposed text", "New content to append" in new_content)
            check("original content preserved", "Existing content" in new_content)

            # 7. Mark the proposal as applied
            ar.mark_applied(proposal, reason)

            # 8. Re-parse the proposals file and verify it's marked applied
            updated_content = proposals_file.read_text(encoding="utf-8")
            check("APPLIED tag present in file", "APPLIED" in updated_content)

            re_parsed = ar.parse_proposals(updated_content)
            check("proposal now marked applied in parse", len(re_parsed) > 0 and re_parsed[0]["applied"])

        finally:
            ar.ROOT = original["ROOT"]
            ar.SKILLS_DIR = original["SKILLS_DIR"]
            ar.MEMORY_DIR = original["MEMORY_DIR"]
            ar.PROPOSALS_FILE = original["PROPOSALS_FILE"]
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── P4: Skill-based GRPO ─────────────────────────────────────────────────────


def _seed_with_skill_and_adv(log, task_id, task_type, score, skill, adv, group="implement:auth"):
    """Seed a reward with skill and explicit advantage (avoids symmetric cancellation)."""
    reward = log.record(
        task_id=task_id,
        task_type=task_type,
        prompt_variant="v1",
        gate_pass=True,
        test_pass=True,
        review_findings=[],
        critique_predictions=[],
        scope_clean=True,
        attempt_count=1,
        skill=skill,
    )
    log._conn.execute(
        "UPDATE rewards SET composite_score = ?, advantage = ? WHERE task_id = ?",
        (score, adv, task_id),
    )
    log._conn.execute(
        'UPDATE rewards SET "group" = ? WHERE task_id = ?', (group, task_id)
    )
    log._conn.commit()


def test_propose_skill_edits_targets_correct_skill_file():
    """propose_skill_edits writes PROPOSE ADD targeting skills/<skill>.md."""
    print("\n[P4 — propose_skill_edits targets skills/<skill>.md]")
    log = _fresh_log()

    # Seed with explicit (non-symmetric) advantages.
    # diagnose: avg_adv ≈ (0.30 + 0.20) / 2 = 0.25 > 0.2  ✓
    # implement: avg_adv ≈ (0.05 + -0.03) / 2 ≈ 0.01 < 0.2  ✗
    _seed_with_skill_and_adv(log, "t1", "auth", 0.95, skill="diagnose",
                              adv=0.30, group="implement:auth")
    _seed_with_skill_and_adv(log, "t2", "auth", 0.90, skill="diagnose",
                              adv=0.20, group="implement:auth")
    _seed_with_skill_and_adv(log, "t3", "auth", 0.40, skill="implement",
                              adv=0.05, group="implement:auth")
    _seed_with_skill_and_adv(log, "t4", "auth", 0.35, skill="implement",
                              adv=-0.03, group="implement:auth")

    tmp_proposals = tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w")
    tmp_proposals.close()
    tmp_path = Path(tmp_proposals.name)

    try:
        written = propose_skill_edits(log, proposals_path=tmp_path, threshold=0.2)

        check("proposals were written", len(written) > 0)
        check("first proposal has skill field", "skill" in written[0])
        check("skill is 'diagnose'", written[0]["skill"] == "diagnose")

        content = tmp_path.read_text(encoding="utf-8")
        parsed = ar.parse_proposals(content)

        check("parse_proposals returns entries", len(parsed) > 0)
        check("target is skills/diagnose.md",
              any("skills/diagnose.md" in p["target"] for p in parsed))
        # implement skill should not appear (advantage below threshold)
        check("skills/implement.md NOT in targets",
              not any("skills/implement.md" in p["target"] for p in parsed))

    finally:
        log.close()
        os.remove(log.db_path)
        if tmp_path.exists():
            tmp_path.unlink()


def test_propose_skill_edits_no_hardcoded_default():
    """propose_skill_edits never writes to DEFAULT_SKILL_FILE (implementer.md)."""
    print("\n[P4 — propose_skill_edits never targets implementer.md]")
    log = _fresh_log()

    # Use a non-default skill name
    _seed_with_skill_and_adv(log, "t1", "auth", 0.95, skill="diagnose",
                              adv=0.30, group="implement:auth")
    _seed_with_skill_and_adv(log, "t2", "auth", 0.90, skill="diagnose",
                              adv=0.20, group="implement:auth")

    tmp_proposals = tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w")
    tmp_proposals.close()
    tmp_path = Path(tmp_proposals.name)

    try:
        written = propose_skill_edits(log, proposals_path=tmp_path, threshold=0.0)

        check("wrote at least one proposal", len(written) > 0)

        content = tmp_path.read_text(encoding="utf-8")

        # The hardcoded DEFAULT_SKILL_FILE must NOT appear in the written content
        check("no implementer.md in written content",
              "skills/implementer.md" not in content)
        check("diagnose.md is in written content",
              "skills/diagnose.md" in content)

        # Also verify via parse
        parsed = ar.parse_proposals(content)
        check("no proposal targets implementer.md",
              all("implementer.md" not in p.get("target", "") for p in parsed))
        check("all proposals target a skill file",
              all(p.get("target", "").startswith("skills/") for p in parsed))

    finally:
        log.close()
        os.remove(log.db_path)
        if tmp_path.exists():
            tmp_path.unlink()


def test_propose_skill_edits_dedup():
    """Same (task_type, skill) pair does not produce duplicate proposals."""
    print("\n[P4 — propose_skill_edits dedup by (task_type, skill)]")
    log = _fresh_log()

    _seed_with_skill_and_adv(log, "t1", "auth", 0.95, skill="diagnose",
                              adv=0.30, group="implement:auth")
    _seed_with_skill_and_adv(log, "t2", "auth", 0.90, skill="diagnose",
                              adv=0.20, group="implement:auth")

    tmp_proposals = tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w")
    tmp_proposals.close()
    tmp_path = Path(tmp_proposals.name)

    try:
        first = propose_skill_edits(log, proposals_path=tmp_path, threshold=0.0)
        check("first call wrote proposals", len(first) > 0)

        second = propose_skill_edits(log, proposals_path=tmp_path, threshold=0.0)
        check("second call wrote no new proposals (dedup)", len(second) == 0)

        content = tmp_path.read_text(encoding="utf-8")
        count = content.count("### PROPOSE ADD to skills/diagnose.md")
        check("only one PROPOSE ADD for diagnose", count == 1)

    finally:
        log.close()
        os.remove(log.db_path)
        if tmp_path.exists():
            tmp_path.unlink()


def test_propose_skill_edits_empty_log():
    """Empty reward log produces no proposals."""
    print("\n[P4 — empty log produces no proposals]")
    log = _fresh_log()

    tmp_proposals = tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w")
    tmp_proposals.close()
    tmp_path = Path(tmp_proposals.name)

    try:
        written = propose_skill_edits(log, proposals_path=tmp_path, threshold=0.2)
        check("empty log returns empty list", len(written) == 0)
        check("no PROPOSE ADD written",
              not tmp_path.exists() or
              "### PROPOSE ADD" not in tmp_path.read_text())

    finally:
        log.close()
        os.remove(log.db_path)
        if tmp_path.exists():
            tmp_path.unlink()


def test_propose_skill_edits_requires_two_runs():
    """Single-run skill is not proposed even with high advantage."""
    print("\n[P4 — single-run skill excluded]")
    log = _fresh_log()

    _seed_with_skill_and_adv(log, "t1", "auth", 0.99, skill="diagnose",
                              adv=0.50, group="implement:auth")

    tmp_proposals = tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w")
    tmp_proposals.close()
    tmp_path = Path(tmp_proposals.name)

    try:
        written = propose_skill_edits(log, proposals_path=tmp_path, threshold=0.2)
        check("single-run skill not proposed", len(written) == 0)

    finally:
        log.close()
        os.remove(log.db_path)
        if tmp_path.exists():
            tmp_path.unlink()


# ── Edge-case tests ───────────────────────────────────────────────────────────

def test_threshold_at_exact_value_included():
    """Advantage exactly equal to threshold (0.2) is excluded because the check
    is STRICTLY GREATER THAN (adv > 0.2)."""
    print("\n[edge — threshold at exact value: 0.2 not greater than 0.2]")
    log = _fresh_log()
    # Two records with advantage = 0.20 exactly each → mean = 0.20
    # Since the check is "advantage > threshold", 0.20 > 0.20 is False → excluded
    _seed_with_skill_and_adv(log, "t1", "auth", 0.95, skill="diagnose",
                              adv=0.20, group="implement:auth")
    _seed_with_skill_and_adv(log, "t2", "auth", 0.90, skill="diagnose",
                              adv=0.20, group="implement:auth")

    result = log.high_advantage_variants(threshold=0.2)
    check("exact-threshold advantage is NOT returned (strict >)", len(result) == 0)
    log.close()
    os.remove(log.db_path)


def test_threshold_just_below_excluded():
    """Advantage just below threshold (0.1999) is excluded."""
    print("\n[edge — advantage 0.1999 < 0.2 threshold]")
    log = _fresh_log()
    # Explicitly set advantage = 0.1999 for both records → mean ≈ 0.1999 < 0.2
    _seed_with_skill_and_adv(log, "t1", "auth", 0.95, skill="diagnose",
                              adv=0.1999, group="implement:auth")
    _seed_with_skill_and_adv(log, "t2", "auth", 0.90, skill="diagnose",
                              adv=0.1999, group="implement:auth")

    result = log.high_advantage_variants(threshold=0.2)
    check("advantage 0.1999 is below 0.2 threshold", len(result) == 0)
    log.close()
    os.remove(log.db_path)


def test_empty_reward_log_returns_empty():
    """A fresh RewardLog (no records) returns empty list from propose_grpo_edits."""
    print("\n[edge — empty log returns empty proposals]")
    log = _fresh_log()

    tmp_proposals = tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w")
    tmp_proposals.close()
    tmp_path = Path(tmp_proposals.name)

    try:
        proposals = propose_grpo_edits(log, proposals_path=tmp_path, threshold=0.2)
        check("propose_grpo_edits on empty log returns []", len(proposals) == 0)
        check("no PROPOSE ADD written to file",
              not tmp_path.exists() or "### PROPOSE ADD" not in tmp_path.read_text())
    finally:
        log.close()
        os.remove(log.db_path)
        if tmp_path.exists():
            tmp_path.unlink()


def test_propose_skill_edits_requires_advantage():
    """Skill records with advantage=0 produce no proposals even with high scores."""
    print("\n[edge — zero advantage: no skill proposals]")
    log = _fresh_log()

    # Two records with skill="diagnose" but advantage=0 → avg_adv = 0 < 0.2
    _seed_with_skill_and_adv(log, "t1", "auth", 0.95, skill="diagnose",
                              adv=0.0, group="implement:auth")
    _seed_with_skill_and_adv(log, "t2", "auth", 0.90, skill="diagnose",
                              adv=0.0, group="implement:auth")

    tmp_proposals = tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w")
    tmp_proposals.close()
    tmp_path = Path(tmp_proposals.name)

    try:
        written = propose_skill_edits(log, proposals_path=tmp_path, threshold=0.2)
        check("zero-advantage skill produces no proposals", len(written) == 0)
        check("no PROPOSE ADD written",
              not tmp_path.exists() or "### PROPOSE ADD" not in tmp_path.read_text())
    finally:
        log.close()
        os.remove(log.db_path)
        if tmp_path.exists():
            tmp_path.unlink()


def test_propose_skill_edits_high_advantage_writes_proposal():
    """Two records with skill='diagnose' and explicit adv=0.30 and 0.20
    (avg=0.25 > 0.2) → propose_skill_edits returns at least 1 entry."""
    print("\n[edge — high-advantage skill writes proposal]")
    log = _fresh_log()

    _seed_with_skill_and_adv(log, "t1", "auth", 0.95, skill="diagnose",
                              adv=0.30, group="implement:auth")
    _seed_with_skill_and_adv(log, "t2", "auth", 0.90, skill="diagnose",
                              adv=0.20, group="implement:auth")

    tmp_proposals = tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w")
    tmp_proposals.close()
    tmp_path = Path(tmp_proposals.name)

    try:
        written = propose_skill_edits(log, proposals_path=tmp_path, threshold=0.2)
        check("propose_skill_edits returns >= 1 proposal", len(written) > 0)
        check("proposal skill field is 'diagnose'",
              any(p.get("skill") == "diagnose" for p in written))

        content = tmp_path.read_text(encoding="utf-8")
        check("skills/diagnose.md appears in written content",
              "skills/diagnose.md" in content)
    finally:
        log.close()
        os.remove(log.db_path)
        if tmp_path.exists():
            tmp_path.unlink()


def test_propose_grpo_and_skill_together():
    """Seed a log with both a high-advantage variant (GRPO) and a high-advantage
    skill → both propose_grpo_edits and propose_skill_edits return results."""
    print("\n[edge — GRPO variant + skill advantage together]")
    log = _fresh_log()

    # High-advantage variant (GRPO path)
    _seed_with_group(log, "t1", "auth", 0.95, variant="v1_high", group="implement:auth")
    _seed_with_group(log, "t2", "auth", 0.95, variant="v1_high", group="implement:auth")
    _seed_with_group(log, "t3", "auth", 0.10, variant="v2_low", group="implement:auth")
    # Compute variant advantages via batch (symmetric cancellation)
    log.compute_batch_advantages()

    # High-advantage skill (P4 path — explicit advantage via SQL, no batch needed)
    _seed_with_skill_and_adv(log, "t4", "auth", 0.95, skill="diagnose",
                              adv=0.30, group="implement:auth")
    _seed_with_skill_and_adv(log, "t5", "auth", 0.90, skill="diagnose",
                              adv=0.20, group="implement:auth")

    tmp_proposals = tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w")
    tmp_proposals.close()
    tmp_path = Path(tmp_proposals.name)

    try:
        grpo_proposals = propose_grpo_edits(log, proposals_path=tmp_path, threshold=0.2)
        skill_proposals = propose_skill_edits(log, proposals_path=tmp_path, threshold=0.2)

        check("propose_grpo_edits returns variant proposal", len(grpo_proposals) > 0)
        check("propose_skill_edits returns skill proposal", len(skill_proposals) > 0)
        check("GRPO proposal mentions v1_high variant",
              any("v1_high" in p.get("text", "") or "v1_high" in str(p)
                  for p in grpo_proposals))
        check("skill proposal skill field is 'diagnose'",
              any(p.get("skill") == "diagnose" for p in skill_proposals))

        content = tmp_path.read_text(encoding="utf-8")
        check("both skill and variant content appear in file",
              "skills/diagnose.md" in content and ("v1_high" in content or "v1" in content))
    finally:
        log.close()
        os.remove(log.db_path)
        if tmp_path.exists():
            tmp_path.unlink()


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("GRPO PROPOSALS — test_grpo_proposals.py (B3 + P4)")
    print("=" * 60)

    test_high_advantage_variants_empty()
    test_high_advantage_variants_below_threshold()
    test_high_advantage_variants_above_threshold()
    test_propose_grpo_edits_writes_parseable_proposals()
    test_propose_grpo_edits_dedup()
    test_propose_grpo_edits_low_advantage()
    test_propose_grpo_edits_no_group()
    test_propose_grpo_edits_requires_two_runs()
    test_apply_retro_parses_grpo_format()
    test_b3_end_to_end_write()
    # P4
    test_propose_skill_edits_targets_correct_skill_file()
    test_propose_skill_edits_no_hardcoded_default()
    test_propose_skill_edits_dedup()
    test_propose_skill_edits_empty_log()
    test_propose_skill_edits_requires_two_runs()

    # Edge cases
    test_threshold_at_exact_value_included()
    test_threshold_just_below_excluded()
    test_empty_reward_log_returns_empty()
    test_propose_skill_edits_requires_advantage()
    test_propose_skill_edits_high_advantage_writes_proposal()
    test_propose_grpo_and_skill_together()

    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed" + ("  -- all clear" if passed == total else f"  ({total-passed} FAILED)"))
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
