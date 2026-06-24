"""
intent_reasoner.py — intent verification layers (harness-native).

L2 (structural) runs here deterministically — no model, no network.

L3 (semantic) is a HOST hook, not a model call. Techne never calls a model:
  - build_semantic_prompt(task, summary) returns the prompt for the host to run
  - the host executes it as its own turn
  - parse_semantic_response(text) turns the host's reply into an IntentVerdict
  - the host passes that verdict into reason_about_intent(..., semantic_verdict=v)

The semantic prompt forces chain-of-thought BEFORE the verdict:
  1. Parse the task into concrete requirements
  2. Read what the diff actually built
  3. Match requirements to evidence
  4. Reach a verdict

This catches "passes all gates but implements the wrong thing" — the class of
errors that syntactic and structural layers cannot see — without Techne ever
needing an API key.
"""

from __future__ import annotations

from dataclasses import dataclass

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


# ─── Semantic layer (L3) — host hook, no model call ─────────────────────────

def build_semantic_prompt(task: str, diff_summary: DiffSummary) -> dict:
    """
    Build the L3 semantic prompt for the HOST to run as its own turn.

    Returns {"system": ..., "user": ...}. The host runs this, then feeds the
    reply to parse_semantic_response() and passes the verdict into
    reason_about_intent(..., semantic_verdict=...). Techne makes no call here.
    """
    return {
        "system": SYSTEM_PROMPT,
        "user": USER_TEMPLATE.format(
            task=task,
            diff_summary=diff_summary.to_structured_text(),
        ),
    }


def parse_semantic_response(text: str) -> IntentVerdict:
    """Parse a host's structured L3 reply into an IntentVerdict (layer=semantic)."""
    verdict = "PARTIAL"
    confidence = 0.5
    reason = ""
    deductions: list[str] = []

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("VERDICT:"):
            v = line.split(":", 1)[1].strip().upper()
            if v in ("MATCH", "PARTIAL", "MISMATCH"):
                verdict = v
        elif line.startswith("CONFIDENCE:"):
            try:
                confidence = max(0.0, min(1.0, float(line.split(":", 1)[1].strip())))
            except ValueError:
                pass
        elif line.startswith("REASON:"):
            reason = line.split(":", 1)[1].strip()
        elif line.startswith("- "):
            deductions.append(line[2:].strip())

    return IntentVerdict(
        verdict=verdict,
        confidence=confidence,
        reason=reason or "(no reason given)",
        deductions=deductions or ["(no deductions)"],
        layer="semantic",
    )


def _coerce_verdict(v: "IntentVerdict | dict") -> IntentVerdict:
    """Accept a host-supplied verdict as an IntentVerdict or a plain dict."""
    if isinstance(v, IntentVerdict):
        return v
    return IntentVerdict(
        verdict=v.get("verdict", "PARTIAL"),
        confidence=v.get("confidence", 0.5),
        reason=v.get("reason", ""),
        deductions=v.get("deductions", []),
        layer=v.get("layer", "semantic"),
        raw_score=v.get("raw_score", 0.0),
    )


# ─── Public interface ────────────────────────────────────────────────────────

def reason_about_intent(
    task: str,
    diff_summary: DiffSummary,
    semantic_verdict: "IntentVerdict | dict | None" = None,
) -> IntentVerdict:
    """
    Entry point for intent reasoning.

    semantic_verdict given → host ran the L3 semantic check; use it.
    semantic_verdict None  → deterministic L2 structural verdict (no model).
    """
    if semantic_verdict is not None:
        return _coerce_verdict(semantic_verdict)
    return _structural_verdict(task, diff_summary)


def verdict_to_gate(verdict: "IntentVerdict | dict", task: str) -> None:
    """
    Raise GateViolation if verdict is MISMATCH with high confidence.
    PARTIAL → warning only (logged, not halted).

    Accepts both IntentVerdict dataclass and plain dict (from full_intent_check).
    """
    from harness.gates import GateViolation

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
