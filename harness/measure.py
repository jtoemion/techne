"""
measure.py — behavioral measurement stack for pipeline runs.

Three layers of intent reasoning:

  L1 Syntactic  (this file)  keyword overlap, file count, line count
                              → fast, free, always runs

  L2 Structural (diff_parser) parse what the diff ACTUALLY DOES:
                              exports, functions, imports, component names
                              → fast, free, deterministic

  L3 Semantic   (intent_reasoner) small LLM (Haiku) reasons on
                              structured L2 output — NOT raw diff
                              → cheap, accurate, catches logic mismatches

The LLM never sees noise. It sees structured facts and reasons like a
detective: what does the task require? what did the diff build? do they match?
"""

from __future__ import annotations

import re
from pathlib import Path

# ─── Diff parsing helpers ────────────────────────────────────────────────────

def extract_changed_files(diff: str) -> list[str]:
    """Parse '+++ b/...' headers to get list of files touched by the diff."""
    files = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            if path and path != "/dev/null":
                files.append(path)
    return list(dict.fromkeys(files))  # deduplicate, preserve order


def count_added_lines(diff: str) -> int:
    """Count lines starting with '+' that aren't headers."""
    return sum(
        1 for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def count_removed_lines(diff: str) -> int:
    """Count lines starting with '-' that aren't headers."""
    return sum(
        1 for line in diff.splitlines()
        if line.startswith("-") and not line.startswith("---")
    )


# ─── Task keyword extraction ─────────────────────────────────────────────────

_STOPWORDS = {
    "a", "an", "the", "to", "in", "on", "at", "of", "for", "and", "or",
    "with", "this", "that", "add", "fix", "update", "change", "make",
    "create", "remove", "delete", "is", "was", "be", "by", "it", "as",
    "from", "into", "should", "will", "new", "the", "use", "using",
}


def extract_task_keywords(task: str) -> list[str]:
    """Extract meaningful nouns/paths from a task description."""
    words = re.findall(r"[\w/\.\-\[\]]+", task.lower())
    # Preserve path-like tokens (contain / or .) and long meaningful words
    keywords = []
    for w in words:
        if "/" in w or "." in w:
            keywords.append(w)
        elif len(w) > 3 and w not in _STOPWORDS:
            keywords.append(w)
    return list(dict.fromkeys(keywords))


# ─── Measurement functions ───────────────────────────────────────────────────

def measure_diff_focus(diff: str, task: str = "") -> tuple[bool, str]:
    """
    Is the diff focused? Returns (focused: bool, reason: str).

    Heuristic:
    - > 200 added lines for tasks < 15 words → likely unfocused
    - > 8 files touched → likely scope creep
    """
    added = count_added_lines(diff)
    files = extract_changed_files(diff)
    task_words = len(task.split()) if task else 10

    if len(files) > 8:
        return False, f"{len(files)} files touched (>8 suggests scope creep)"
    if added > 200 and task_words < 15:
        return False, f"{added} lines added for a {task_words}-word task"
    if added == 0 and not diff.strip():
        return False, "empty diff"

    return True, f"{added} lines added across {len(files)} file(s)"


def measure_scope_creep(task: str, diff: str) -> tuple[bool, str]:
    """
    Did the diff touch files unrelated to the task?
    Returns (scope_crept: bool, reason: str).

    Heuristic: check if changed file paths share keywords with the task.
    If 0 files share ANY keyword with the task, it's suspicious.
    """
    if not diff.strip():
        return False, "no diff"

    files = extract_changed_files(diff)
    if not files:
        return False, "no file headers in diff"

    task_keywords = extract_task_keywords(task)
    if not task_keywords:
        return False, "task too vague to measure"

    # How many changed files share at least one keyword with the task?
    related = 0
    for f in files:
        f_lower = f.lower()
        if any(kw in f_lower for kw in task_keywords):
            related += 1

    if len(files) > 0 and related == 0:
        return True, (
            f"0/{len(files)} changed files share keywords with task. "
            f"Files: {files[:4]}. Task keywords: {task_keywords[:6]}"
        )

    unrelated = len(files) - related
    if unrelated > 3:
        return True, f"{unrelated}/{len(files)} files appear unrelated to task"

    return False, f"{related}/{len(files)} files match task keywords"


def measure_intent(task: str, diff: str) -> dict:
    """
    Heuristic intent check: does the diff look like it implements the task?

    Returns:
      score:    0.0-1.0 (1.0 = strong match, 0.0 = no match)
      matched:  keywords found in diff content
      missing:  keywords NOT found in diff content
      files:    changed files
      warning:  human-readable summary
    """
    if not diff.strip():
        return {"score": 0.0, "matched": [], "missing": [], "files": [], "warning": "empty diff"}

    task_keywords = extract_task_keywords(task)
    if not task_keywords:
        return {"score": 0.5, "matched": [], "missing": [], "files": [],
                "warning": "task too vague to measure intent"}

    files = extract_changed_files(diff)
    diff_lower = diff.lower()

    matched = [kw for kw in task_keywords if kw in diff_lower]
    missing = [kw for kw in task_keywords if kw not in diff_lower]

    score = len(matched) / len(task_keywords) if task_keywords else 0.5

    if score >= 0.7:
        warning = f"intent: MATCH ({len(matched)}/{len(task_keywords)} keywords in diff)"
    elif score >= 0.4:
        warning = (
            f"intent: PARTIAL ({len(matched)}/{len(task_keywords)} keywords). "
            f"Missing: {missing[:4]}"
        )
    else:
        warning = (
            f"intent: LOW MATCH ({len(matched)}/{len(task_keywords)} keywords). "
            f"Missing: {missing[:6]}. Verify diff implements the task."
        )

    return {
        "score": round(score, 2),
        "matched": matched,
        "missing": missing,
        "files": files,
        "warning": warning,
    }


def gate_intent(task: str, diff: str, threshold: float = 0.3) -> None:
    """
    Raises GateViolation if intent score is below threshold.

    Default threshold 0.3 is lenient — catches only clear mismatches
    (diff has almost nothing to do with the task). Raise to 0.5 once
    the gate has been calibrated against real runs.
    """
    from harness.gates import GateViolation

    result = measure_intent(task, diff)
    if result["score"] < threshold:
        raise GateViolation(
            f"INTENT GATE FAIL: diff score {result['score']:.2f} < {threshold}.\n"
            f"{result['warning']}\n"
            f"Task: {task}\n"
            f"Files changed: {result['files']}"
        )


# ─── Full layered intent check ───────────────────────────────────────────────

def full_intent_check(task: str, diff: str, semantic_verdict=None) -> dict:
    """
    Run the intent reasoning stack.

    L1 → syntactic heuristic (keyword overlap)        — deterministic
    L2 → structural parse (what the diff actually built) — deterministic
    L3 → semantic verdict, supplied by the host (optional). When the host
         passes semantic_verdict, it overrides L2; otherwise L2 is used.

    Returns a unified dict with all layer results for the eval report.
    """
    from diff_parser import parse_diff
    from intent_reasoner import reason_about_intent

    # L1: syntactic
    l1 = measure_intent(task, diff)

    # L2 structural (or host-supplied L3 semantic verdict)
    diff_summary = parse_diff(diff)
    verdict = reason_about_intent(task, diff_summary, semantic_verdict=semantic_verdict)

    return {
        "verdict": verdict.verdict,
        "confidence": verdict.confidence,
        "reason": verdict.reason,
        "deductions": verdict.deductions,
        "layer": verdict.layer,
        "l1_score": l1["score"],
        "l1_warning": l1["warning"],
        "diff_summary": diff_summary,
        "warning": (
            f"[{verdict.layer}] {verdict.verdict} ({verdict.confidence:.0%}): {verdict.reason}"
        ),
    }


# ─── Convenience: run all measurements ──────────────────────────────────────

def run_measurements(task: str, diff: str, semantic_verdict=None) -> dict:
    """
    Run all measurements on a task+diff pair.
    Returns a dict ready to merge into orchestrator eval_metrics.
    `semantic_verdict` (optional) is a host-supplied L3 verdict.
    """
    focused, focus_reason = measure_diff_focus(diff, task)
    crept, creep_reason = measure_scope_creep(task, diff)

    # Layered intent check (L1 + L2, optional host L3)
    intent = full_intent_check(task, diff, semantic_verdict=semantic_verdict)

    return {
        "diff_focused": focused,
        "scope_creep": crept,
        "_focus_reason": focus_reason,
        "_creep_reason": creep_reason,
        "_intent": intent,
        # backward compat — old callers expect "score" and "warning"
        "_intent_score": intent["l1_score"],
        "_intent_warning": intent["warning"],
    }
