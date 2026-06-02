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

def apply_add(proposal: dict) -> tuple[bool, str]:
    """Append text to target skill file."""
    target_path = SKILLS_DIR / proposal["target"]

    if not target_path.exists():
        return False, f"Target file not found: {target_path}"

    current = target_path.read_text(encoding="utf-8")
    addition = "\n" + proposal["text"].strip() + "\n"
    target_path.write_text(current + addition, encoding="utf-8")

    return True, f"Appended {len(proposal['text'].splitlines())} lines to {proposal['target']}"


def apply_delete(proposal: dict) -> tuple[bool, str]:
    """Remove the entry starting with entry_first_line from target skill file."""
    target_path = SKILLS_DIR / proposal["target"]

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
    if not pattern.search(current):
        # Try plain line match
        lines = current.splitlines(keepends=True)
        new_lines = [l for l in lines if first_line not in l]
        target_path.write_text("".join(new_lines), encoding="utf-8")
        return True, f"Removed line containing '{first_line}'"

    new_content = pattern.sub("", current)
    target_path.write_text(new_content, encoding="utf-8")
    return True, f"Removed entry starting with '{first_line}'"


def apply_resolve(proposal: dict) -> tuple[bool, str]:
    """Mark a mistake entry as RESOLVED."""
    from mistakes import mark_resolved
    success = mark_resolved(proposal["mistake_date"])
    if success:
        return True, f"Resolved mistake from {proposal['mistake_date']}"
    return False, f"No ACTIVE mistake found for date {proposal['mistake_date']}"


def mark_applied(proposal: dict, reason: str) -> None:
    """Mark a proposal as APPLIED in retro_proposals.md."""
    if not PROPOSALS_FILE.exists():
        return
    content = PROPOSALS_FILE.read_text(encoding="utf-8")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    applied_tag = f"\n<!-- APPLIED: {ts} — {reason} -->"
    new_content = content.replace(proposal["raw"], proposal["raw"] + applied_tag, 1)
    PROPOSALS_FILE.write_text(new_content, encoding="utf-8")


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

    return {"reviewed": len(pending), "applied": applied, "skipped": skipped}


# ─── Check for unapplied proposals (called by conductor) ─────────────────────

def has_pending_proposals() -> int:
    """Return count of unapplied proposals. 0 = clean."""
    if not PROPOSALS_FILE.exists():
        return 0
    content = PROPOSALS_FILE.read_text(encoding="utf-8")
    proposals = parse_proposals(content)
    return sum(1 for p in proposals if not p["applied"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apply retro proposals to skill files")
    parser.add_argument("--dry-run", action="store_true", help="Show proposals, apply nothing")
    parser.add_argument("--auto",    action="store_true", help="Apply all without confirmation")
    args = parser.parse_args()

    review_and_apply(dry_run=args.dry_run, auto=args.auto)
