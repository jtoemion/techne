"""
apply_retro.py — consume retro proposals and close the learning loop.

Reads memory/retro_proposals.md, shows what would change,
applies on approval, marks proposals as APPLIED.

The retro agent proposes. A human approves. This script applies.
That's the missing step Megumi identified.

Usage:
    python harness/apply_retro.py           # interactive review
    python harness/apply_retro.py --dry-run # show proposals, apply nothing
    python harness/apply_retro.py --auto    # apply all (no confirmation)
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
MEMORY_DIR = ROOT / "memory"
PROPOSALS_FILE = MEMORY_DIR / "retro_proposals.md"
SKILLS_DIR = ROOT / "skills"


# ─── Proposal parsing ────────────────────────────────────────────────────────

def parse_proposals(content: str) -> list[dict]:
    """
    Parse PROPOSE ADD / PROPOSE DELETE / PROPOSE RESOLVE entries.

    Returns list of:
      {"type": "ADD"|"DELETE"|"RESOLVE", "target": str,
       "text": str, "raw": str, "applied": bool}
    """
    proposals = []

    # Match each ## Retro block
    retro_blocks = re.split(r"^## Retro —", content, flags=re.MULTILINE)

    for block in retro_blocks[1:]:  # skip preamble
        lines = block.strip().splitlines()
        date = lines[0].strip() if lines else "unknown"

        # Find PROPOSE ADD entries
        for m in re.finditer(
            r"### PROPOSE ADD to ([\w/\.]+)\n(.*?)(?=###|\Z)",
            block, re.DOTALL
        ):
            target = m.group(1).strip()
            text = m.group(2).strip()
            if text and "NO CHANGE" not in text:
                proposals.append({
                    "type": "ADD",
                    "date": date,
                    "target": target,
                    "text": text,
                    "raw": m.group(0),
                    "applied": "APPLIED" in m.group(0),
                })

        # Find PROPOSE DELETE entries
        for m in re.finditer(
            r"### PROPOSE DELETE from ([\w/\.]+)\s*\nEntry: \"([^\"]+)\"",
            block
        ):
            target = m.group(1).strip()
            entry_first_line = m.group(2).strip()
            proposals.append({
                "type": "DELETE",
                "date": date,
                "target": target,
                "entry_first_line": entry_first_line,
                "raw": m.group(0),
                "applied": "APPLIED" in m.group(0),
            })

        # Find PROPOSE RESOLVE entries
        for m in re.finditer(
            r"### PROPOSE RESOLVE mistake\s*\nDate: \"([^\"]+)\"\s*\nReason: (.+)",
            block
        ):
            proposals.append({
                "type": "RESOLVE",
                "date": date,
                "mistake_date": m.group(1).strip(),
                "reason": m.group(2).strip(),
                "raw": m.group(0),
                "applied": "APPLIED" in m.group(0),
            })

    return proposals


# ─── Apply actions ───────────────────────────────────────────────────────────

def _resolve_target(target: str) -> Path:
    """Resolve a proposal target to a real path.

    retro emits repo-root-relative targets ("skills/foo.md",
    "skills/tdd/mocking.md"). Older/bare targets ("foo.md") resolve under skills/.
    """
    t = target.strip().replace("\\", "/")
    if t.startswith("skills/"):
        return ROOT / t
    return SKILLS_DIR / t


def _validate_edit(path: Path, old_text: str, new_text: str) -> tuple[bool, str]:
    """Gap 3: self-improvement must obey the same structure gates as hand-written
    skills. Only blocks edits that INTRODUCE/worsen a violation — pre-existing
    issues don't cause false rejects. Capability bundles (SKILL.md) are exempt.
    """
    if path.name == "SKILL.md":
        return True, "capability bundle — cap-exempt"
    try:
        rel = path.relative_to(ROOT).as_posix()
    except ValueError:
        rel = path.name
    is_sub = rel.count("/") >= 2                 # skills/<name>/<topic>.md
    cap = 150 if is_sub else 100
    old_n, new_n = len(old_text.splitlines()), len(new_text.splitlines())

    problems = []
    if new_n > cap and new_n > old_n:
        problems.append(f"edit grows file to {new_n} lines (> {cap}-line cap)")
    if "## Next Steps" in old_text and "## Next Steps" not in new_text:
        problems.append("edit removed the ## Next Steps chain")
    return (False, "; ".join(problems)) if problems else (True, "ok")


def apply_add(proposal: dict) -> tuple[bool, str]:
    """Append text to target skill file — rejected if it breaks the structure gates."""
    target_path = _resolve_target(proposal["target"])

    if not target_path.exists():
        return False, f"Target file not found: {target_path}"

    current = target_path.read_text(encoding="utf-8")
    new_content = current + "\n" + proposal["text"].strip() + "\n"

    ok, reason = _validate_edit(target_path, current, new_content)
    if not ok:
        return False, f"REJECTED — edit would break {proposal['target']}: {reason}"

    target_path.write_text(new_content, encoding="utf-8")
    return True, f"Appended {len(proposal['text'].splitlines())} lines to {proposal['target']}"


def apply_delete(proposal: dict) -> tuple[bool, str]:
    """Remove the entry starting with entry_first_line from target skill file."""
    target_path = _resolve_target(proposal["target"])

    if not target_path.exists():
        return False, f"Target file not found: {target_path}"

    current = target_path.read_text(encoding="utf-8")
    first_line = proposal["entry_first_line"]

    if first_line not in current:
        return False, f"Entry not found: '{first_line}'"

    # Find the entry block: from first_line to the next ## or EOF
    pattern = re.compile(
        r"\n## " + re.escape(first_line) + r".*?(?=\n## |\Z)",
        re.DOTALL
    )
    if pattern.search(current):
        new_content = pattern.sub("", current)
        action = f"Removed entry starting with '{first_line}'"
    else:
        lines = current.splitlines(keepends=True)
        new_content = "".join(l for l in lines if first_line not in l)
        action = f"Removed line containing '{first_line}'"

    ok, reason = _validate_edit(target_path, current, new_content)
    if not ok:
        return False, f"REJECTED — edit would break {proposal['target']}: {reason}"

    target_path.write_text(new_content, encoding="utf-8")
    return True, action


def apply_resolve(proposal: dict) -> tuple[bool, str]:
    """Mark a mistake entry as RESOLVED."""
    from mistakes import mark_resolved
    success = mark_resolved(proposal["mistake_date"])
    if success:
        return True, f"Resolved mistake from {proposal['mistake_date']}"
    return False, f"No ACTIVE mistake found for date {proposal['mistake_date']}"


def _latest_eval_total() -> int | None:
    """Most recent pipeline eval score, or None if no history yet."""
    try:
        from evaluator import load_eval_history
        hist = load_eval_history()
        return hist[-1]["total"] if hist else None
    except Exception:
        return None


def mark_applied(proposal: dict, reason: str) -> None:
    """Mark a proposal as APPLIED, tagged with the eval score at apply time (Gap 4)."""
    if not PROPOSALS_FILE.exists():
        return
    content = PROPOSALS_FILE.read_text(encoding="utf-8")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    eval_at = _latest_eval_total()
    eval_part = f" | eval@apply={eval_at}" if eval_at is not None else ""
    applied_tag = f"\n<!-- APPLIED: {ts}{eval_part} — {reason} -->"
    new_content = content.replace(proposal["raw"], proposal["raw"] + applied_tag, 1)
    PROPOSALS_FILE.write_text(new_content, encoding="utf-8")


def check_regressions() -> list[dict]:
    """Gap 4: flag applied skill edits the eval trend has REGRESSED below.

    For each applied proposal tagged with eval@apply, compare against the latest
    eval score. If the score dropped, the edit may have hurt — flag for revert.
    """
    if not PROPOSALS_FILE.exists():
        return []
    eval_now = _latest_eval_total()
    if eval_now is None:
        return []
    content = PROPOSALS_FILE.read_text(encoding="utf-8")
    flags = []
    for p in parse_proposals(content):
        if not p["applied"]:
            continue
        m = re.search(r"eval@apply=(\d+)", p["raw"])
        if not m:
            continue
        at = int(m.group(1))
        if eval_now < at:
            flags.append({
                "target": p.get("target", p.get("type", "?")),
                "eval_at_apply": at,
                "eval_now": eval_now,
                "delta": eval_now - at,
            })
    return flags


def format_regressions(flags: list[dict]) -> str:
    """ASCII-safe render of regression flags."""
    if not flags:
        return ""
    lines = ["SELF-IMPROVEMENT REGRESSIONS (eval dropped since edit -> consider revert):"]
    for f in flags:
        lines.append(
            f"  [REGRESSED] {f['target']}: {f['eval_at_apply']} -> {f['eval_now']} ({f['delta']:+d})"
        )
    return "\n".join(lines)


# ─── Interactive review ──────────────────────────────────────────────────────

def review_and_apply(dry_run: bool = False, auto: bool = False) -> dict:
    """
    Main loop: show proposals, ask for approval, apply.
    Returns summary: {"reviewed": N, "applied": N, "skipped": N}
    """
    if not PROPOSALS_FILE.exists():
        print("No retro_proposals.md found — nothing to apply.")
        return {"reviewed": 0, "applied": 0, "skipped": 0}

    content = PROPOSALS_FILE.read_text(encoding="utf-8")
    proposals = parse_proposals(content)

    pending = [p for p in proposals if not p["applied"]]

    if not pending:
        print("No pending proposals — retro_proposals.md is clean.")
        return {"reviewed": 0, "applied": 0, "skipped": 0}

    print(f"\n{'=' * 60}")
    print(f"RETRO APPLY — {len(pending)} pending proposal(s)")
    print(f"{'=' * 60}")

    applied = skipped = 0

    for i, proposal in enumerate(pending, 1):
        ptype = proposal["type"]
        target = proposal.get("target", "")
        date = proposal.get("date", "?")

        print(f"\n[{i}/{len(pending)}] {ptype} → {target} (from {date})")

        if ptype == "ADD":
            print(f"  Text to add:\n  {proposal['text'][:200]}")
        elif ptype == "DELETE":
            print(f"  Entry to delete: \"{proposal['entry_first_line']}\"")
        elif ptype == "RESOLVE":
            print(f"  Resolve mistake: {proposal['mistake_date']}")
            print(f"  Reason: {proposal.get('reason', '?')}")

        if dry_run:
            print("  [DRY RUN — skipped]")
            skipped += 1
            continue

        if not auto:
            answer = input("  Apply? [y/n/q]: ").strip().lower()
            if answer == "q":
                print("Aborted.")
                break
            if answer != "y":
                skipped += 1
                continue

        # Apply
        if ptype == "ADD":
            ok, reason = apply_add(proposal)
        elif ptype == "DELETE":
            ok, reason = apply_delete(proposal)
        elif ptype == "RESOLVE":
            ok, reason = apply_resolve(proposal)
        else:
            ok, reason = False, f"unknown proposal type: {ptype}"

        if ok:
            mark_applied(proposal, reason)
            print(f"  Applied: {reason}")
            applied += 1
        else:
            print(f"  Failed: {reason}")
            skipped += 1

    print(f"\n{'=' * 60}")
    print(f"Applied: {applied}  Skipped: {skipped}  Total: {len(pending)}")
    print(f"{'=' * 60}")

    flags = check_regressions()
    if flags:
        print("\n" + format_regressions(flags))

    return {"reviewed": len(pending), "applied": applied, "skipped": skipped}


# ─── Check for unapplied proposals (called by conductor) ─────────────────────

def has_pending_proposals() -> int:
    """Return count of unapplied proposals. 0 = clean."""
    if not PROPOSALS_FILE.exists():
        return 0
    content = PROPOSALS_FILE.read_text(encoding="utf-8")
    proposals = parse_proposals(content)
    return sum(1 for p in proposals if not p["applied"])


def auto_apply_pending() -> dict:
    """
    Apply all pending proposals without confirmation.
    Returns summary dict. Used by the conductor's retro phase.
    """
    return review_and_apply(auto=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apply retro proposals to skill files")
    parser.add_argument("--dry-run", action="store_true", help="Show proposals, apply nothing")
    parser.add_argument("--auto",    action="store_true", help="Apply all without confirmation")
    args = parser.parse_args()

    review_and_apply(dry_run=args.dry_run, auto=args.auto)
