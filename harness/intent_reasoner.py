"""
intent_reasoner.py — semantic reasoning layer for intent verification.

Layer 3 of the intent reasoning system.

The LLM gets a structured summary of FACTS (from diff_parser.py),
not raw diff text. Small context → cheap model → excellent deductions.

The prompt forces chain-of-thought BEFORE the verdict:
  1. Parse the task into concrete requirements
  2. Read what the diff actually built
  3. Match requirements to evidence
  4. Reach a verdict

This catches "passes all gates but implements the wrong thing" —
the class of errors that syntactic and structural layers cannot see.

Requires: ANTHROPIC_API_KEY
Falls back to structural-only reasoning if no API key.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from diff_parser import DiffSummary


@dataclass
class IntentVerdict:
    verdict: str              # MATCH | PARTIAL | MISMATCH
    confidence: float         # 0.0-1.0
    reason: str               # one sentence
    deductions: list[str]     # concrete reasoning steps
    layer: str                # heuristic | structural | semantic
    raw_score: float = 0.0    # heuristic layer score for comparison


# ─── System prompt ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a code intent verifier. You receive a task description and a \
structured summary of what a diff actually does (exports added, functions \
changed, files touched, imports). Your job is to deduce — not guess — \
whether the diff implements the task.

Rules:
- Reason from EVIDENCE, not assumptions
- Name specific exports/functions/files in your deductions
- MATCH = diff clearly implements what was asked
- PARTIAL = diff does part of it but something is missing or wrong
- MISMATCH = diff implements something different from what was asked
- If evidence is insufficient, lean toward PARTIAL not MATCH
"""

USER_TEMPLATE = """\
Task: {task}

What the diff actually did:
{diff_summary}

Reason step by step:
1. What concrete things does the task require? (list them)
2. What concrete things did the diff build? (read the summary above)
3. Which requirements are satisfied by the evidence?
4. Which requirements have no evidence?

Then output EXACTLY this format (no other text after):
VERDICT: MATCH | PARTIAL | MISMATCH
CONFIDENCE: 0.0-1.0
REASON: one sentence
DEDUCTIONS:
- deduction 1
- deduction 2
- deduction 3
"""


# ─── Structural fallback (no LLM) ───────────────────────────────────────────

def _structural_verdict(task: str, diff_summary: DiffSummary) -> IntentVerdict:
    """
    Layer 2 reasoning — no LLM, purely structural.
    Better than keyword matching, worse than semantic.

    Rules:
    - No files changed → MISMATCH (nothing built)
    - New component export matches task noun → likely MATCH
    - Files changed are unrelated file type → MISMATCH
    - Something added → PARTIAL (conservative default)
    """
    if diff_summary.is_empty:
        return IntentVerdict(
            verdict="MISMATCH",
            confidence=0.9,
            reason="Diff is empty — nothing was built.",
            deductions=["No files changed", "Task cannot be implemented without changes"],
            layer="structural",
        )

    task_lower = task.lower()
    deductions: list[str] = []

    # Check export names against task
    matched_exports = [
        e for e in diff_summary.all_exports_added
        if any(word in e.lower() for word in task_lower.split() if len(word) > 3)
    ]

    # Check file types against task context
    file_types = {f.file_type for f in diff_summary.files}
    new_files = [f for f in diff_summary.files if f.is_new]

    if matched_exports:
        deductions.append(f"Export(s) named to match task: {', '.join(matched_exports[:3])}")

    if new_files:
        deductions.append(
            f"New file(s) created: {', '.join(f.path for f in new_files[:3])}"
        )

    if diff_summary.all_imports_added:
        deductions.append(
            f"Imports added: {', '.join(diff_summary.all_imports_added[:3])}"
        )

    deductions.append(
        f"Dominant change type: {diff_summary.dominant_type} "
        f"({len(diff_summary.files)} file(s), "
        f"+{diff_summary.total_added}/-{diff_summary.total_removed} lines)"
    )

    # Score
    score = 0.0
    if matched_exports:
        score += 0.5
    if new_files and any("component" in f.file_type or "page" in f.file_type
                         for f in new_files):
        score += 0.3
    if diff_summary.total_added > 0:
        score += 0.2

    if score >= 0.7:
        verdict, confidence, reason = (
            "MATCH", min(0.75, score),
            f"Structural evidence supports task: {', '.join(matched_exports[:2]) or 'changes present'}"
        )
    elif score >= 0.3:
        verdict, confidence, reason = (
            "PARTIAL", 0.5,
            "Some structural evidence supports task but full match is unconfirmed without semantic analysis"
        )
    else:
        verdict, confidence, reason = (
            "MISMATCH", 0.6,
            "Structural evidence does not align with task requirements"
        )

    return IntentVerdict(
        verdict=verdict,
        confidence=confidence,
        reason=reason,
        deductions=deductions,
        layer="structural",
        raw_score=score,
    )


# ─── Semantic reasoning (LLM) ───────────────────────────────────────────────

def _parse_llm_response(text: str) -> dict:
    """Parse the structured LLM output."""
    verdict = "PARTIAL"
    confidence = 0.5
    reason = ""
    deductions = []

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("VERDICT:"):
            v = line.split(":", 1)[1].strip().upper()
            if v in ("MATCH", "PARTIAL", "MISMATCH"):
                verdict = v
        elif line.startswith("CONFIDENCE:"):
            try:
                confidence = float(line.split(":", 1)[1].strip())
                confidence = max(0.0, min(1.0, confidence))
            except ValueError:
                pass
        elif line.startswith("REASON:"):
            reason = line.split(":", 1)[1].strip()
        elif line.startswith("- "):
            deductions.append(line[2:].strip())

    return {
        "verdict": verdict,
        "confidence": confidence,
        "reason": reason or "(no reason given)",
        "deductions": deductions or ["(no deductions)"],
    }


def _semantic_verdict(task: str, diff_summary: DiffSummary) -> IntentVerdict:
    """
    Layer 3 — small LLM reasoning on structured diff summary.
    Uses cheapest model (Haiku). Small context, high accuracy.
    """
    try:
        import anthropic
    except ImportError:
        return _structural_verdict(task, diff_summary)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _structural_verdict(task, diff_summary)

    client = anthropic.Anthropic(api_key=api_key)

    user_message = USER_TEMPLATE.format(
        task=task,
        diff_summary=diff_summary.to_structured_text(),
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",  # cheapest — focused reasoning task
        max_tokens=512,                       # tight budget, structured output only
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text
    parsed = _parse_llm_response(raw)

    return IntentVerdict(
        verdict=parsed["verdict"],
        confidence=parsed["confidence"],
        reason=parsed["reason"],
        deductions=parsed["deductions"],
        layer="semantic",
    )


# ─── Public interface ────────────────────────────────────────────────────────

def reason_about_intent(
    task: str,
    diff_summary: DiffSummary,
    use_llm: bool = True,
) -> IntentVerdict:
    """
    Entry point for intent reasoning.

    use_llm=True  → tries semantic (L3), falls back to structural (L2)
    use_llm=False → structural only (L2), no API call
    """
    if use_llm and os.environ.get("ANTHROPIC_API_KEY"):
        return _semantic_verdict(task, diff_summary)
    return _structural_verdict(task, diff_summary)


def verdict_to_gate(verdict: "IntentVerdict | dict", task: str) -> None:
    """
    Raise GateViolation if verdict is MISMATCH with high confidence.
    PARTIAL → warning only (logged, not halted).

    Accepts both IntentVerdict dataclass and plain dict (from full_intent_check).
    """
    from gates import GateViolation

    # Accept dict (from full_intent_check) or IntentVerdict dataclass
    if isinstance(verdict, dict):
        v_verdict     = verdict.get("verdict", "PARTIAL")
        v_confidence  = verdict.get("confidence", 0.5)
        v_reason      = verdict.get("reason", "")
        v_layer       = verdict.get("layer", "unknown")
        v_deductions  = verdict.get("deductions", [])
    else:
        v_verdict    = verdict.verdict
        v_confidence = verdict.confidence
        v_reason     = verdict.reason
        v_layer      = verdict.layer
        v_deductions = verdict.deductions

    if v_verdict == "MISMATCH" and v_confidence >= 0.7:
        raise GateViolation(
            f"INTENT GATE [{v_layer}]: MISMATCH (confidence {v_confidence:.0%})\n"
            f"Task: {task}\n"
            f"Reason: {v_reason}\n"
            f"Deductions:\n" +
            "\n".join(f"  - {d}" for d in v_deductions[:4])
        )

    if v_verdict == "PARTIAL":
        print(
            f"[INTENT] PARTIAL ({v_layer}, confidence {v_confidence:.0%}): "
            f"{v_reason}"
        )

    if v_verdict == "MATCH":
        print(
            f"[INTENT] MATCH ({v_layer}, confidence {v_confidence:.0%}): "
            f"{v_reason}"
        )
