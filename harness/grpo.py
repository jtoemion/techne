"""
grpo.py — Connect GRPO advantage scores to real skill file edits.

Reads the reward log for high-advantage prompt variants (advantage > threshold)
and writes PROPOSE ADD entries to retro_proposals.md in the format that
apply_retro.parse_proposals() expects. These proposals sit waiting for human
confirmation via review_and_apply() — the same gate already used by the retro
agent. No auto-apply path is used (B0 disabled auto_apply_pending).

Usage:
    from grpo import propose_grpo_edits
    from reward_log import RewardLog

    log = RewardLog()
    proposed = propose_grpo_edits(log)
    # proposed is a list of dicts summarising what was written
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

HARNESS_DIR = Path(__file__).parent
ROOT = HARNESS_DIR.parent
MEMORY_DIR = ROOT / ".techne" / "memory"
DEFAULT_PROPOSALS_FILE = MEMORY_DIR / "retro_proposals.md"

ADVANTAGE_THRESHOLD = 0.2
DEFAULT_SKILL_FILE = "skills/implementer.md"


def propose_grpo_edits(
    reward_log,
    proposals_path: str | Path | None = None,
    threshold: float = ADVANTAGE_THRESHOLD,
    skill_file: str = DEFAULT_SKILL_FILE,
) -> list[dict]:
    """
    Scan the reward log for high-advantage prompt variants and write
    PROPOSE ADD entries to retro_proposals.md.

    For each variant with average advantage > *threshold*:
      1. Generates a PROPOSE ADD entry targeting *skill_file*
      2. Includes a comment line with ``# weight: <advantage> | seen: Nx``
      3. The proposal text includes the variant's system_suffix and temperature
      4. Appends the entry inside a ``## Retro — <date>`` block

    Skips variants that already have an un-applied proposal in the file
    (dedup by prompt_variant name).

    Parameters
    ----------
    reward_log : RewardLog
        The reward log with advantage scores already computed
        (call ``compute_batch_advantages()`` first).
    proposals_path : str or Path, optional
        Path to the retro_proposals.md file. Defaults to
        ``.techne/memory/retro_proposals.md``.
    threshold : float, optional
        Minimum average advantage to trigger a proposal. Default 0.2.
    skill_file : str, optional
        Target skill file for proposals. Default ``skills/implementer.md``.

    Returns
    -------
    list[dict]
        List of proposal dicts that were written, each containing:
          {"task_type": str, "prompt_variant": str,
           "avg_advantage": float, "count": int}
        Empty list if nothing met the threshold.
    """
    from reward_log import RewardLog

    proposals_path = Path(proposals_path or DEFAULT_PROPOSALS_FILE)

    # 1. Scan reward log for high-advantage variants
    high_adv = reward_log.high_advantage_variants(threshold=threshold)
    if not high_adv:
        return []

    # 2. Load existing proposals to avoid duplicates
    existing_proposals = _load_existing_proposals(proposals_path)

    written: list[dict] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build the full content (new block + any existing content after the last ## Retro)
    # Actually, we append to the file. Let's read existing content.
    existing_content = ""
    if proposals_path.exists():
        existing_content = proposals_path.read_text(encoding="utf-8")

    # We'll build new entries and append them
    new_sections: list[str] = []

    for variant in high_adv:
        task_type = variant["task_type"]
        pv = variant["prompt_variant"]
        avg_adv = variant["avg_advantage"]
        count = variant["cnt"]
        avg_score = variant["avg_score"]

        # Dedup: skip if an un-applied proposal for this variant already exists
        if _variant_already_proposed(existing_proposals, pv):
            continue

        # Build the comment line and proposal text
        weight_line = f"# weight: {avg_adv:.3f} | seen: {count}x | score: {avg_score:.3f}"
        proposal_text = (
            f"GRPO Advantage-sourced edit from prompt variant **{pv}**\n\n"
            f"**Task type:** {task_type}\n"
            f"**Advantage:** {avg_adv:.3f} (above group mean)\n"
            f"**Runs:** {count}\n"
            f"**Avg score:** {avg_score:.3f}\n"
            f"**Proposed variant config:**\n"
            f"- system_suffix from variant `{pv}`\n"
            f"- temperature from variant `{pv}`\n"
        )

        proposal_entry = (
            f"## Retro — {now}\n"
            f"\n"
            f"### PROPOSE ADD to {skill_file}\n"
            f"{weight_line}\n"
            f"{proposal_text}\n"
        )

        new_sections.append(proposal_entry)
        written.append({
            "task_type": task_type,
            "prompt_variant": pv,
            "avg_advantage": avg_adv,
            "count": count,
        })

    if not new_sections:
        return []

    # 3. Write to file
    proposals_path.parent.mkdir(parents=True, exist_ok=True)

    # Prepend a header if file is new
    if not existing_content.strip():
        header = (
            "# Retro Proposals\n"
            "# Auto-generated by grpo.propose_grpo_edits()\n"
            "# Human confirmation required via review_and_apply()\n"
            "\n"
        )
        existing_content = header

    full_content = existing_content.rstrip() + "\n\n" + "\n".join(new_sections)
    proposals_path.write_text(full_content, encoding="utf-8")

    return written


# ── Helpers ────────────────────────────────────────────────────────────────────


def _dedup_skill_entries(existing: list[dict], task_type: str, skill: str) -> bool:
    """Check if a proposal for (task_type, skill) already exists and is not applied."""
    for p in existing:
        if p.get("applied", False):
            continue
        raw = p.get("raw", "")
        # Match on both task_type and skill appearing together
        if task_type in raw and skill in raw:
            return True
    return False


def _load_existing_proposals(path: Path) -> list[dict]:
    """Load proposals from an existing retro_proposals.md file.

    Uses ``apply_retro.parse_proposals()`` if available; otherwise returns
    empty list (best-effort).
    """
    if not path.exists():
        return []
    try:
        from apply_retro import parse_proposals
        content = path.read_text(encoding="utf-8")
        return parse_proposals(content)
    except (ImportError, Exception):
        return []


def _variant_already_proposed(existing: list[dict], variant_name: str) -> bool:
    """Check if a proposal for *variant_name* already exists and is not applied.

    Looks for the variant name in the raw proposal text.
    """
    for p in existing:
        if p.get("applied", False):
            continue
        raw = p.get("raw", "")
        if variant_name in raw:
            return True
    return False


# ── P4: Skill-based GRPO ───────────────────────────────────────────────────────


def propose_skill_edits(
    reward_log,
    proposals_path: str | Path | None = None,
    threshold: float = ADVANTAGE_THRESHOLD,
) -> list[dict]:
    """
    Scan the reward log for high-advantage (task_type, skill) pairs and write
    PROPOSE ADD entries to retro_proposals.md targeting ``skills/<skill>.md``.

    This is the P4 counterpart to ``propose_grpo_edits()`` — it proposes
    skill-file improvements rather than prompt-variant edits.

    Unlike ``propose_grpo_edits()`` this function NEVER writes to the
    hardcoded DEFAULT_SKILL_FILE ("skills/implementer.md"). Each entry
    targets ``f"skills/{skill}.md"`` where ``skill`` is drawn from the
    reward record.

    Parameters
    ----------
    reward_log : RewardLog
        The reward log with advantage scores already computed
        (call ``compute_batch_advantages()`` first).
    proposals_path : str or Path, optional
        Path to the retro_proposals.md file. Defaults to
        ``.techne/memory/retro_proposals.md``.
    threshold : float, optional
        Minimum average advantage to trigger a proposal. Default 0.2.

    Returns
    -------
    list[dict]
        List of proposal dicts that were written, each containing:
          {"task_type": str, "skill": str,
           "avg_advantage": float, "count": int,
           "avg_score": float}
        Empty list if nothing met the threshold.
    """
    proposals_path = Path(proposals_path or DEFAULT_PROPOSALS_FILE)

    # 1. Scan reward log for high-advantage (task_type, skill) pairs
    high_adv = reward_log.high_advantage_skills(threshold=threshold)
    if not high_adv:
        return []

    # 2. Load existing proposals to avoid duplicates
    existing_proposals = _load_existing_proposals(proposals_path)

    written: list[dict] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Load existing file content for append/prepend logic
    existing_content = ""
    if proposals_path.exists():
        existing_content = proposals_path.read_text(encoding="utf-8")

    new_sections: list[str] = []

    for row in high_adv:
        task_type = row["task_type"]
        skill = row["skill"]
        avg_adv = row["avg_advantage"]
        count = row["cnt"]
        avg_score = row["avg_score"]

        # Dedup: skip if an un-applied proposal for (task_type, skill) already exists
        if _dedup_skill_entries(existing_proposals, task_type, skill):
            continue

        # Never use the hardcoded DEFAULT_SKILL_FILE — always derive from the reward skill
        skill_file = f"skills/{skill}.md"

        # Build the comment line and proposal text
        weight_line = f"# weight: {avg_adv:.3f} | seen: {count}x | score: {avg_score:.3f}"
        proposal_text = (
            f"Skill-based GRPO edit: skill **{skill}** under task type **{task_type}**\n\n"
            f"**Task type:** {task_type}\n"
            f"**Skill:** {skill}\n"
            f"**Advantage:** {avg_adv:.3f} (above group mean)\n"
            f"**Runs:** {count}\n"
            f"**Avg score:** {avg_score:.3f}\n"
            f"**Proposed improvement:**\n"
            f"- append actionable guidance to ``{skill_file}``\n"
        )

        proposal_entry = (
            f"## Retro — {now}\n"
            f"\n"
            f"### PROPOSE ADD to {skill_file}\n"
            f"{weight_line}\n"
            f"{proposal_text}\n"
        )

        new_sections.append(proposal_entry)
        written.append({
            "task_type": task_type,
            "skill": skill,
            "avg_advantage": avg_adv,
            "count": count,
            "avg_score": avg_score,
        })

    if not new_sections:
        return []

    # 3. Write to file
    proposals_path.parent.mkdir(parents=True, exist_ok=True)

    # Prepend a header if file is new
    if not existing_content.strip():
        header = (
            "# Retro Proposals\n"
            "# Auto-generated by grpo.propose_skill_edits() (P4)\n"
            "# Human confirmation required via review_and_apply()\n"
            "\n"
        )
        existing_content = header

    full_content = existing_content.rstrip() + "\n\n" + "\n".join(new_sections)
    proposals_path.write_text(full_content, encoding="utf-8")

    return written


# ── Framework-skill GRPO (P4-FW) ──────────────────────────────────────────────


def propose_framework_edits(
    reward_log,
    stack_tags: set[str],
    threshold: float = ADVANTAGE_THRESHOLD,
) -> list[dict]:
    """
    Like propose_skill_edits but writes directly to framework skill files'
    RL-Proposed Additions section instead of retro_proposals.md.

    Only processes skills that match detected stack tags — filtering the
    high-advantage skills list to only those whose skill name appears in
    ``stack_tags``. This ensures framework-specific proposals go to the
    right skill file (e.g. react.md for a React project, svelte.md for
    a Svelte project).

    Each entry is appended to ``skills/{skill}.md`` under the
    ``## RL-Proposed Additions`` heading using the entry template that
    is already present in those files.

    Parameters
    ----------
    reward_log : RewardLog
        The reward log with advantage scores already computed
        (call ``compute_batch_advantages()`` first).
    stack_tags : set[str]
        Detected framework tags from ``detect_stack()``, e.g. {"react",
        "typescript", "vite"}. Only skills whose name is in this set
        will receive proposals.
    threshold : float, optional
        Minimum average advantage to trigger a proposal. Default 0.2.

    Returns
    -------
    list[dict]
        List of proposal dicts that were written, each containing:
          {"task_type": str, "skill": str,
           "avg_advantage": float, "count": int,
           "avg_score": float}
        Empty list if nothing met the threshold.
    """
    # 1. Scan reward log for high-advantage (task_type, skill) pairs
    high_adv = reward_log.high_advantage_skills(threshold=threshold)
    if not high_adv:
        return []

    # 2. Filter to only skills that match detected stack tags
    framework_skills = [row for row in high_adv if row["skill"] in stack_tags]
    if not framework_skills:
        return []

    written: list[dict] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for row in framework_skills:
        task_type = row["task_type"]
        skill = row["skill"]
        avg_adv = row["avg_advantage"]
        count = row["cnt"]
        avg_score = row["avg_score"]

        skill_file = ROOT / "skills" / skill / "SKILL.md"
        if not skill_file.exists():
            continue

        # 3. Read current content to find the RL-Proposed Additions section
        content = skill_file.read_text(encoding="utf-8")

        # Build the new entry using the template from the skill file:
        # ### [YYYY-MM-DD] Pitfall title
        # - **Source:** GRPO proposal from task <task_id>
        # - **Evidence:** Review finding repeated N times across M tasks
        # - **Advantage:** X.XXX
        # - **Pattern:** Description of the pitfall
        # - **Fix:** How to avoid it
        # - **Example:** Code snippet showing wrong vs correct
        entry_lines = [
            f"### [{now}] GRPO skill improvement for {task_type}",
            f"- **Source:** GRPO proposal; {count} runs observed",
            f"- **Evidence:** avg score {avg_score:.3f}, advantage {avg_adv:.3f}",
            f"- **Advantage:** {avg_adv:.3f}",
            f"- **Pattern:** High-advantage (task_type={task_type}, skill={skill}) pair",
            f"- **Fix:** Review and promote this pattern to the skill body if stable",
            "",
        ]
        entry_text = "\n".join(entry_lines)

        # 4. Append under the RL-Proposed Additions section
        section_marker = "## RL-Proposed Additions"
        if section_marker in content:
            # Insert before the closing comment or at end of section
            parts = content.split(section_marker)
            # parts[0] = before marker, parts[1] = after marker
            after_marker = parts[1]
            # Remove any trailing blank lines from the before-insert
            new_content = (
                parts[0]
                + section_marker
                + "\n"
                + entry_text
                + "\n"
                + after_marker.lstrip()
            )
        else:
            # Section not found — append at end of file
            new_content = content.rstrip() + "\n\n" + section_marker + "\n" + entry_text + "\n"

        skill_file.write_text(new_content, encoding="utf-8")

        written.append({
            "task_type": task_type,
            "skill": skill,
            "avg_advantage": avg_adv,
            "count": count,
            "avg_score": avg_score,
        })

    return written
