"""
pipeline_enforcer.py — State machine that enforces the multi-agent pipeline order.

The pipeline phases are:
  RECALL → IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → EVAL → RETRO → CONCLUDE → REFRESH_CONTEXT → DONE
                                                  ↘ BLOCKED → DEBUG → IMPLEMENT (retry)

The enforcer:
  - Tracks phase state per task in the task_db
  - Validates transitions (can't skip phases)
  - Records every transition as an event
  - Rejects out-of-order submissions

Usage:
    from pipeline_enforcer import PipelineEnforcer

    enforcer = PipelineEnforcer(db)

    # Before each phase:
    enforcer.can_enter(task_id, "RECALL")       # True if task is PENDING or BLOCKED
    enforcer.can_enter(task_id, "IMPLEMENT")    # True if RECALL is complete
    enforcer.can_enter(task_id, "REVIEW")       # False — context-guard hasn't run yet

    # After each phase:
    enforcer.mark_complete(task_id, "RECALL", agent="recaller", summary="...")
    enforcer.mark_complete(task_id, "IMPLEMENT", agent="implementer", summary="...")
    enforcer.mark_complete(task_id, "CONTEXT_GUARD", agent="context-guard", summary="...")

    # Dashboard:
    print(enforcer.status(task_id))
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import os
from pathlib import Path
from typing import Optional

from task_db import TaskDB, Task


# ── Memory directory and override log ──────────────────────────────────────

_HARNESS_DIR = Path(__file__).parent
_ROOT = _HARNESS_DIR.parent
MEMORY_DIR = _ROOT / ".techne" / "memory"
OVERRIDES_LOG = MEMORY_DIR / "mode_overrides.log"
_MAX_LOG_LINES = 1000

# ── Learning loop state ─────────────────────────────────────────────────────
_LEARNING_COUNTER = 0          # total override entries ever logged
_LAST_ANALYZED_COUNT = 0       # counter value at last auto-analysis
_AUTO_ANALYSIS_THRESHOLD = 20  # trigger analysis every N new entries
_CLASSIFIER_INSIGHTS_LOG = MEMORY_DIR / "classifier_insights.log"


def _reset_learning_state() -> None:
    """Reset learning loop counters. For testing only."""
    global _LEARNING_COUNTER, _LAST_ANALYZED_COUNT
    _LEARNING_COUNTER = 0
    _LAST_ANALYZED_COUNT = 0


# ── Phase definitions ────────────────────────────────────────────────────

PHASES = [
    "RECALL",
    "IMPLEMENT",
    "CONTEXT_GUARD",
    "CRITIQUE",
    "REVIEW",
    "APPROVAL",
    "VERIFY",
    "EVAL",
    "RETRO",
    "CONCLUDE",
    "REFRESH_CONTEXT",
    "DONE",
]

# Valid transitions: from_state -> allowed next states
# The pipeline is strict: you can only go forward, or to BLOCKED/DEBUG from any point.
TRANSITIONS = {
    None:           ["RECALL"],                              # fresh task → recall context
    "PENDING":      ["RECALL"],                              # ready to start → recall first
    "BLOCKED":      ["IMPLEMENT", "DEBUG", "VERIFY", "REVIEW", "EVAL"],  # retry after block
    "DEBUG":        ["IMPLEMENT"],                           # debug fixes, then re-implement
    "RECALL":       ["IMPLEMENT", "BLOCKED", "FAILED"],      # recall done → implement
    "IMPLEMENT":    ["CONTEXT_GUARD", "BLOCKED", "FAILED"],  # impl done → audit, or fail
    "CONTEXT_GUARD":["CRITIQUE", "BLOCKED", "FAILED"],       # audit done → critique, or fail
    "CRITIQUE":     ["REVIEW", "BLOCKED", "FAILED"],         # critique done → review, or fail
    "REVIEW":       ["VERIFY", "BLOCKED", "IMPLEMENT", "FAILED"],  # review: pass→verify, hardfail→re-implement
    "APPROVAL":     ["VERIFY", "BLOCKED", "IMPLEMENT", "FAILED"],  # approval: approve→verify, reject→failed, modify→re-implement
    "VERIFY":       ["EVAL", "BLOCKED", "IMPLEMENT", "FAILED"],    # verify: pass→eval(score), fail→re-implement
    "EVAL":         ["RETRO", "FAILED"],                     # deterministic 100-pt score → reflect
    "RETRO":        ["CONCLUDE", "FAILED"],                  # reflect on the score → conclude
    "CONCLUDE":     ["REFRESH_CONTEXT", "FAILED"],           # durable write-back → refresh context
    "REFRESH_CONTEXT": ["DONE", "FAILED"],                   # refresh complete → done
    "DONE":         [],                                      # terminal
    "FAILED":       [],                                      # terminal
}

# Heavy-mode transitions: full pipeline with APPROVAL HITL between REVIEW and VERIFY
HEAVY_TRANSITIONS = {
    None:           ["RECALL"],
    "PENDING":      ["RECALL"],
    "BLOCKED":      ["IMPLEMENT", "DEBUG", "VERIFY", "REVIEW", "APPROVAL", "EVAL"],
    "DEBUG":        ["IMPLEMENT"],
    "RECALL":       ["IMPLEMENT", "BLOCKED", "FAILED"],
    "IMPLEMENT":    ["CONTEXT_GUARD", "BLOCKED", "FAILED"],
    "CONTEXT_GUARD":["CRITIQUE", "BLOCKED", "FAILED"],
    "CRITIQUE":     ["REVIEW", "BLOCKED", "FAILED"],
    "REVIEW":       ["APPROVAL", "BLOCKED", "IMPLEMENT", "FAILED"],  # review → APPROVAL (not directly to VERIFY)
    "APPROVAL":     ["VERIFY", "BLOCKED", "IMPLEMENT", "FAILED"],    # approval: approve→verify, reject→failed, modify→re-implement
    "VERIFY":       ["EVAL", "BLOCKED", "IMPLEMENT", "FAILED"],
    "EVAL":         ["RETRO", "FAILED"],
    "RETRO":        ["CONCLUDE", "FAILED"],
    "CONCLUDE":     ["REFRESH_CONTEXT", "FAILED"],
    "REFRESH_CONTEXT": ["DONE", "FAILED"],
    "DONE":         [],
    "FAILED":       [],
}

# Human-readable phase descriptions (for subagent prompts)
PHASE_DESCRIPTIONS = {
    "RECALL": "Recall durable context from Honcho for this task title and tags. Run honcho_search or honcho_context and return the excerpts.",
    "IMPLEMENT": "Write code (TDD: test first, minimal diff)",
    "CONTEXT_GUARD": "Scan changes, record audit trail (file inventory, scope check)",
    "CRITIQUE": "Predict emergent bugs from the implementation diff",
    "REVIEW": "Security/correctness/gate compliance review",
    "APPROVAL": "Human approval required for sensitive changes (auth/billing/data migration). Review changes and approve, reject, or request modifications.",
    "VERIFY": "Run tests, capture real output",
    "EVAL": "Score the run deterministically (100-point eval report)",
    "RETRO": "Reflect on the run — lessons, recurrence, skill-edit proposals",
    "CONCLUDE": "Write durable facts back to Honcho (conclusion IDs as proof)",
    "REFRESH_CONTEXT": "Rebuild generated workshop artifacts and flag stale authored docs for the touched subsystems.",
    "DONE": "Task complete",
    "BLOCKED": "Task blocked — needs human input or debugger",
    "FAILED": "Task terminal failure",
    "DEBUG": "Debugger diagnosing root cause",
}

# Logic keywords that indicate a non-trivial change (used by validate_micro_mode)
_LOGIC_KEYWORDS = frozenset([
    "if", "for", "while", "switch", "function",
    "import", "export", "try", "except", "finally",
    "return", "yield", "with", "async", "await",
    "def ", "class ",
])

# FAST-mode keywords — tasks that are review/audit/documentation-only
_FAST_KEYWORDS = frozenset([
    "review", "audit", "verify", "check", "inspect",
    "document", "readme", "comment", "typo",
])

# HEAVY-mode keywords — sensitive changes that require explicit human approval
_HEAVY_KEYWORDS = frozenset([
    "auth", "billing", "payment", "migration",
    "password", "role", "permission", "credential",
    "secret", "token",
])

# Per-mode cost estimates (agent API calls per task)
_MODE_COST_ESTIMATES = {
    "micro": {"api_calls": 4, "notes": "IMPLEMENT → CG → VERIFY → EVAL"},
    "fast": {"api_calls": 7, "notes": "IMPLEMENT → CG → CRITIQUE → REVIEW → VERIFY → EVAL → RETRO"},
    "full": {"api_calls": 11, "notes": "RECALL → IMPLEMENT → CG → CRITIQUE → REVIEW → VERIFY → EVAL → RETRO → CONCLUDE → REFRESH → DONE"},
    "heavy": {"api_calls": 12, "notes": "RECALL → IMPLEMENT → CG → CRITIQUE → REVIEW → APPROVAL → VERIFY → EVAL → RETRO → CONCLUDE → REFRESH → DONE"},
}


# ── Mode-override telemetry ─────────────────────────────────────────────────

def _log_mode_override(
    task_id: str,
    chosen_mode: str,
    suggested_mode: str,
    diff_stats: dict,
) -> None:
    """Record a mode override event to the telemetry log.

    Appends a JSON line to ``.techne/memory/mode_overrides.log``.
    Auto-rotates when the log exceeds ``_MAX_LOG_LINES`` (keeps last 1000).
    Triggers auto-analysis of override patterns every 20 new entries.
    """
    global _LEARNING_COUNTER

    from datetime import datetime, timezone

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_id": task_id,
        "chosen_mode": chosen_mode,
        "suggested_mode": suggested_mode,
        "diff_lines": diff_stats.get("diff_lines", 0),
        "file_count": diff_stats.get("file_count", 0),
        "has_logic": diff_stats.get("has_logic", False),
    }

    log_path = Path(OVERRIDES_LOG)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, separators=(",", ":")) + "\n")

    # Auto-rotate: keep only the last _MAX_LOG_LINES
    with open(log_path, "r", encoding="utf-8") as fh:
        lines = fh.readlines()
    if len(lines) > _MAX_LOG_LINES:
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.writelines(lines[-_MAX_LOG_LINES:])

    # Learning loop: increment counter and trigger auto-analysis at threshold
    _LEARNING_COUNTER += 1
    _auto_analysis_if_needed()


def get_mode_overrides(limit: int = 20) -> list[dict]:
    """Return the most recent N override entries from the telemetry log.

    Each entry is a dict with keys: timestamp, task_id, chosen_mode,
    suggested_mode, diff_lines, file_count, has_logic.
    """
    log_path = Path(OVERRIDES_LOG)
    if not log_path.exists():
        return []

    with open(log_path, "r", encoding="utf-8") as fh:
        all_lines = fh.readlines()

    recent = all_lines[-limit:] if limit > 0 else all_lines
    entries = []
    for line in recent:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return entries


def _file_count_bucket(file_count: int) -> str:
    """Bucket file_count into small/medium/large."""
    if file_count <= 1:
        return "single_file"
    if file_count <= 3:
        return "few_files"
    return "many_files"


def analyze_override_patterns(limit: int = 200) -> list[dict]:
    """Analyze override log for recurring patterns.

    Returns a list of pattern dicts sorted by frequency:
    [
        {
            "pattern": "micro->full (logic keywords in clean diff)",
            "count": 12,
            "pct": 60.0,
            "suggested_action": "Add 'test' to _FAST_KEYWORDS exclusion list",
            "sample_tasks": ["fix test assertion", "add test coverage"],
        },
        ...
    ]

    Detection rules:
    - If chosen==full and suggested==micro and has_logic==True:
        pattern = "logic keywords in micro-mode diff"
        suggested_action = "Strict micro rules are correct, no adjustment needed"
    - If chosen==full and suggested==micro and has_logic==False and lines>3:
        pattern = "diff-too-large for micro"
        suggested_action = "Classifier working correctly, no adjustment needed"
    - If chosen==full and suggested==fast and "review" in task title:
        pattern = "review task choosing full over fast"
        suggested_action = "Consider adding to _FAST_KEYWORDS"
    - Group by (suggested_mode, chosen_mode, has_logic, file_count_bucket)
    - Return sorted by count descending
    """
    entries = get_mode_overrides(limit=limit)
    if not entries:
        return []

    from collections import defaultdict
    from datetime import datetime, timezone

    # We need task titles to detect "review" keyword pattern.
    # entries from _log_mode_override don't include titles, so we reconstruct
    # from the override log.  Fall back to the group key only when no title.
    # A separate field "task_title" is NOT yet in _log_mode_override's entry,
    # so we use file_count_bucket for grouping only.
    #
    # Override patterns we detect:
    # 1. chosen=full, suggested=micro, has_logic=True  → classifier correct, no action
    # 2. chosen=full, suggested=micro, has_logic=False, diff_lines>3 → classifier correct
    # 3. chosen=full, suggested=fast, file_count>1     → needs investigation
    # 4. chosen=micro, suggested=full, has_logic=True  → classifier correct (strict)
    # 5. chosen=micro, suggested=full, has_logic=False, diff_lines>3 → classifier correct
    # 6. chosen=micro, suggested=full, has_logic=False, diff_lines<=3, file_count=1 → consider micro relax

    groups: dict[tuple, dict] = defaultdict(lambda: {
        "count": 0,
        "sample_tasks": [],
    })

    for entry in entries:
        chosen = entry.get("chosen_mode", "")
        suggested = entry.get("suggested_mode", "")
        has_logic = entry.get("has_logic", False)
        diff_lines = entry.get("diff_lines", 0)
        file_count = entry.get("file_count", 0)
        task_id = entry.get("task_id", "")
        task_title = entry.get("task_title", task_id)

        fb = _file_count_bucket(file_count)

        if chosen == "full" and suggested == "micro" and has_logic:
            key = ("full->micro", "has_logic", "classifier_correct")
            groups[key]["count"] += 1
            if len(groups[key]["sample_tasks"]) < 3:
                groups[key]["sample_tasks"].append(task_title)
        elif chosen == "full" and suggested == "micro" and not has_logic and diff_lines > 3:
            key = ("full->micro", "no_logic_large_diff", "classifier_correct")
            groups[key]["count"] += 1
            if len(groups[key]["sample_tasks"]) < 3:
                groups[key]["sample_tasks"].append(task_title)
        elif chosen == "full" and suggested == "fast" and file_count > 1:
            key = ("full->fast", "multi_file_review", "consider_fast_keyword")
            groups[key]["count"] += 1
            if len(groups[key]["sample_tasks"]) < 3:
                groups[key]["sample_tasks"].append(task_title)
        elif chosen == "micro" and suggested == "full" and has_logic:
            key = ("micro->full", "has_logic", "strict_micro_correct")
            groups[key]["count"] += 1
            if len(groups[key]["sample_tasks"]) < 3:
                groups[key]["sample_tasks"].append(task_title)
        elif chosen == "micro" and suggested == "full" and not has_logic and diff_lines > 3:
            key = ("micro->full", "large_diff", "strict_micro_correct")
            groups[key]["count"] += 1
            if len(groups[key]["sample_tasks"]) < 3:
                groups[key]["sample_tasks"].append(task_title)
        elif chosen == "micro" and suggested == "full" and not has_logic and diff_lines <= 3 and file_count == 1:
            key = ("micro->full", "small_clean", "relax_micro_candidate")
            groups[key]["count"] += 1
            if len(groups[key]["sample_tasks"]) < 3:
                groups[key]["sample_tasks"].append(task_title)
        else:
            key = ("other", "misc", "needs_review")
            groups[key]["count"] += 1
            if len(groups[key]["sample_tasks"]) < 3:
                groups[key]["sample_tasks"].append(task_title)

    # Build result sorted by count descending
    total = len(entries)
    results = []

    # Pattern label map
    pattern_labels: dict[tuple, str] = {
        ("full->micro", "has_logic", "classifier_correct"):
            "full mode overriding micro recommendation with logic keywords",
        ("full->micro", "no_logic_large_diff", "classifier_correct"):
            "full mode overriding micro recommendation on large diff (no logic)",
        ("full->fast", "multi_file_review", "consider_fast_keyword"):
            "full mode overriding fast recommendation on multi-file review",
        ("micro->full", "has_logic", "strict_micro_correct"):
            "micro mode overriding full recommendation with logic keywords",
        ("micro->full", "large_diff", "strict_micro_correct"):
            "micro mode overriding full on large diff (no logic keywords)",
        ("micro->full", "small_clean", "relax_micro_candidate"):
            "micro mode overriding full on small clean diff — candidate for micro relaxation",
        ("other", "misc", "needs_review"):
            "miscellaneous override pattern",
    }

    # Suggested action map
    suggested_actions: dict[tuple, str] = {
        ("full->micro", "has_logic", "classifier_correct"):
            "Classifier working correctly — strict micro rules are appropriate",
        ("full->micro", "no_logic_large_diff", "classifier_correct"):
            "Classifier working correctly — large diff without logic still needs full pipeline",
        ("full->fast", "multi_file_review", "consider_fast_keyword"):
            "Consider adding multi-file review pattern to _FAST_KEYWORDS exclusion",
        ("micro->full", "has_logic", "strict_micro_correct"):
            "Strict micro rules are correct — no adjustment needed for logic keywords",
        ("micro->full", "large_diff", "strict_micro_correct"):
            "Strict micro rules are correct — no adjustment needed for large diffs",
        ("micro->full", "small_clean", "relax_micro_candidate"):
            "Consider relaxing micro rules to allow this pattern (small clean diff)",
        ("other", "misc", "needs_review"):
            "Review this pattern manually for classifier tuning opportunity",
    }

    for (key_tuple), data in groups.items():
        pattern = pattern_labels.get(key_tuple, f"override pattern: {key_tuple[0]}")
        suggested_action = suggested_actions.get(key_tuple, "No suggested action")
        pct = round(data["count"] / total * 100, 1) if total > 0 else 0.0
        results.append({
            "pattern": pattern,
            "count": data["count"],
            "pct": pct,
            "suggested_action": suggested_action,
            "sample_tasks": data["sample_tasks"],
        })

    results.sort(key=lambda x: x["count"], reverse=True)
    return results


def suggest_classifier_updates(threshold: int = 3) -> list[str]:
    """Suggest classifier rule updates based on override patterns.

    Only returns suggestions for patterns that appear >= threshold times.
    Suggestions are human-readable strings like:
    - "Add '_debug' to logic keywords list (3 overrides from debug tasks)"
    - "Add 'migration' to _FAST_KEYWORDS exclusion (5 overrides)"
    """
    patterns = analyze_override_patterns(limit=200)
    suggestions = []

    for p in patterns:
        if p["count"] < threshold:
            continue
        action = p["suggested_action"]
        # Only surface actionable suggestions (not "classifier correct")
        if "no adjustment needed" in action.lower() or "working correctly" in action.lower():
            continue
        if "needs_review" in p["pattern"].lower():
            continue
        suggestions.append(f"{action} ({p['count']} overrides)")

    return suggestions


def _auto_analysis_if_needed() -> None:
    """Check if enough new overrides have been logged; run analysis if so.

    Writes results to ``.techne/memory/classifier_insights.log`` when triggered.
    This is called automatically after each _log_mode_override().
    """
    global _LEARNING_COUNTER, _LAST_ANALYZED_COUNT

    new_entries = _LEARNING_COUNTER - _LAST_ANALYZED_COUNT
    if new_entries >= _AUTO_ANALYSIS_THRESHOLD:
        _LAST_ANALYZED_COUNT = _LEARNING_COUNTER
        patterns = analyze_override_patterns(limit=200)
        suggestions = suggest_classifier_updates(threshold=3)

        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).isoformat()

        insights_path = Path(_CLASSIFIER_INSIGHTS_LOG)
        insights_path.parent.mkdir(parents=True, exist_ok=True)

        with open(insights_path, "a", encoding="utf-8") as fh:
            fh.write(f"\n=== Auto-analysis @ {timestamp} ({new_entries} new entries) ===\n")
            fh.write(f"Patterns found: {len(patterns)}\n")
            for p in patterns:
                fh.write(
                    f"  [{p['count']}x, {p['pct']}%] {p['pattern']} — {p['suggested_action']}\n"
                )
            fh.write(f"Actionable suggestions: {len(suggestions)}\n")
            for s in suggestions:
                fh.write(f"  • {s}\n")


def get_classifier_insights(threshold: int = 3) -> list[str]:
    """Return actionable classifier update suggestions.

    This is the public API for reading learning loop output.
    """
    return suggest_classifier_updates(threshold=threshold)


def get_cost_estimate(phase_mode: str) -> dict:
    """Return cost estimate dict for a phase mode."""
    return _MODE_COST_ESTIMATES.get(phase_mode.lower(), _MODE_COST_ESTIMATES["full"])


def classify_phase_mode(title: str, description: str = "", diff_text: str = "") -> str:
    """Classify the appropriate phase mode for a task.

    Rules:
    - MICRO: Change is <=3 lines, single file, no logic keywords
      (if, for, while, switch, function, class, import, export, return, async, await, try, catch)
    - FAST: Task is review-only, audit-only, verification-only, or documentation-only
      (keywords: review, audit, verify, check, inspect, document, README, comment, typo in title)
    - HEAVY: Sensitive changes — auth, billing, payment, migration, password, role, permission,
      credential, secret, token (in title or description) — requires explicit human approval
    - FULL: Everything else — code changes with logic, multi-file, complex work
    """
    combined = f"{title} {description}".lower()

    # Check fast-mode indicators first
    for kw in _FAST_KEYWORDS:
        if kw in combined:
            return "fast"

    # Check heavy-mode (sensitive) indicators — overrides other modes
    for kw in _HEAVY_KEYWORDS:
        if kw in combined:
            return "heavy"

    # If no diff to analyze yet, default to full
    if not diff_text or not diff_text.strip():
        return "full"

    lines = diff_text.splitlines()

    # Count changed lines
    added = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    changed_lines = added + removed

    # Count unique files
    files: set[str] = set()
    for l in lines:
        if l.startswith("+++ b/") or l.startswith("--- a/"):
            path = l[6:].strip()
            if path and path != "/dev/null":
                files.add(path)

    # Check for logic keywords (word-boundary for plain words, trailing-space for def/class)
    diff_lower = diff_text.lower()
    has_logic = False
    for kw in _LOGIC_KEYWORDS:
        if kw.endswith(" "):
            # def / class — match as prefix (def foo, class Bar)
            if kw.rstrip() in diff_lower:
                has_logic = True
                break
        else:
            # Word boundary: \b keyword \b
            if re.search(r"\b" + re.escape(kw) + r"\b", diff_lower):
                has_logic = True
                break

    # MICRO: ≤3 lines, 1 file, no logic
    if changed_lines <= 3 and len(files) <= 1 and not has_logic:
        return "micro"

    return "full"


def detect_sensitive_change(files_changed: list[str], diff_text: str = "") -> tuple[bool, list[str]]:
    """Detect if a change touches sensitive files/subsystems.

    Returns (is_sensitive, matched_files) where matched_files lists the
    files from files_changed that match heavy keywords (in filename or path).
    """
    matched: list[str] = []
    diff_lower = diff_text.lower() if diff_text else ""

    for f in files_changed:
        f_lower = f.lower()
        for kw in _HEAVY_KEYWORDS:
            if kw in f_lower:
                matched.append(f)
                break

    # Also check diff content for heavy keywords in changed file names
    if diff_text:
        for l in diff_text.splitlines():
            if l.startswith("+++ b/") or l.startswith("--- a/"):
                path = l[6:].strip()
                if path:
                    for kw in _HEAVY_KEYWORDS:
                        if kw in path.lower():
                            if path not in matched:
                                matched.append(path)
                            break

    return bool(matched), matched


def _compute_diff_stats(diff_text: str) -> dict:
    """Compute diff statistics: changed_lines, file_count, has_logic."""
    lines = diff_text.splitlines()
    added = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    changed_lines = added + removed
    files: set[str] = set()
    for l in lines:
        if l.startswith("+++ b/") or l.startswith("--- a/"):
            path = l[6:].strip()
            if path and path != "/dev/null":
                files.add(path)
    diff_lower = diff_text.lower()
    kw_check = []
    for kw in _LOGIC_KEYWORDS:
        if kw.endswith(" "):
            if kw.rstrip() in diff_lower:
                kw_check.append(kw)
                break
        else:
            if re.search(r"\b" + re.escape(kw) + r"\b", diff_lower):
                kw_check.append(kw)
                break
    return {
        "diff_lines": changed_lines,
        "file_count": len(files),
        "has_logic": bool(kw_check),
    }


def validate_mode_fit(
    phase_mode: str, diff_text: str = "", file_count: int = 0, task_id: str = ""
) -> tuple[bool, str, str]:
    """Returns (valid, reason, suggested_mode).

    - If micro is chosen but diff >3 lines: return (False, "...", "fast" or "full")
    - If micro is chosen but >1 file: return (False, "...", "fast" or "full")
    - If micro is chosen but logic keywords found: return (False, "...", "full")
    - If full is chosen but diff <=3 lines, 1 file, no logic: return (False, "...", "micro")
    - If full is chosen but title suggests review/audit: return (False, "...", "fast")
    """
    mode = phase_mode.lower()

    if mode == "micro":
        # Empty diff is only valid if file_count is 0 (pre-implement check)
        if not diff_text or not diff_text.strip():
            if file_count == 0:
                return True, "", ""
            diff_stats = _compute_diff_stats("")
            _log_mode_override(task_id, mode, "full", diff_stats)
            return False, "Empty diff but files already touched", "full"

        diff_stats = _compute_diff_stats(diff_text)
        changed_lines = diff_stats["diff_lines"]

        if changed_lines > 3:
            cost_micro = get_cost_estimate("micro")["api_calls"]
            cost_full = get_cost_estimate("full")["api_calls"]
            _log_mode_override(task_id, mode, "full", diff_stats)
            return False, f"micro mode requires <=3 changed lines (got {changed_lines}) — full mode ({cost_full} API calls) recommended", "full"

        files: set[str] = set()
        for l in diff_text.splitlines():
            if l.startswith("+++ b/") or l.startswith("--- a/"):
                path = l[6:].strip()
                if path and path != "/dev/null":
                    files.add(path)
        if len(files) > 1:
            cost_micro = get_cost_estimate("micro")["api_calls"]
            cost_full = get_cost_estimate("full")["api_calls"]
            _log_mode_override(task_id, mode, "full", diff_stats)
            return False, f"micro mode requires <=1 file (got {len(files)}) — full mode ({cost_full} API calls) recommended", "full"
        if len(files) == 0:
            _log_mode_override(task_id, mode, "full", diff_stats)
            return False, "No file paths found in diff", "full"

        diff_lower = diff_text.lower()
        kw_check = []
        for kw in _LOGIC_KEYWORDS:
            if kw.endswith(" "):
                if kw.rstrip() in diff_lower:
                    kw_check.append(kw)
                    break
            else:
                if re.search(r"\b" + re.escape(kw) + r"\b", diff_lower):
                    kw_check.append(kw)
                    break
        has_logic = bool(kw_check)
        if has_logic:
            cost_micro = get_cost_estimate("micro")["api_calls"]
            cost_full = get_cost_estimate("full")["api_calls"]
            _log_mode_override(task_id, mode, "full", diff_stats)
            return False, f"micro mode cannot contain logic keywords (if/for/while/class/etc) — full mode ({cost_full} API calls) recommended", "full"

        return True, "", ""

    if mode == "full":
        # Empty diff — nothing to validate yet (pre-implement check)
        if not diff_text or not diff_text.strip():
            return True, "", ""

        diff_stats = _compute_diff_stats(diff_text)
        changed_lines = diff_stats["diff_lines"]
        file_count = diff_stats["file_count"]
        has_logic = diff_stats["has_logic"]

        # If it looks like it should be micro, suggest it
        if changed_lines <= 3 and file_count <= 1 and not has_logic:
            cost_micro = get_cost_estimate("micro")["api_calls"]
            cost_full = get_cost_estimate("full")["api_calls"]
            _log_mode_override(task_id, mode, "micro", diff_stats)
            return False, f"full mode ({cost_full} API calls) applied to trivial change ({changed_lines} lines, {file_count} file) — micro mode ({cost_micro} API calls) suggested", "micro"

        return True, "", ""

    # fast mode is always valid — it's just a subset, never over-specified
    return True, "", ""


def validate_micro_mode(diff_text: str) -> tuple[bool, str]:
    """Validate that micro mode is appropriate for this diff.

    Returns (is_valid, rejection_reason).
    Micro mode is valid only if:
    - Diff is ≤3 lines changed (added + removed)
    - Diff touches only 1 file
    - Diff doesn't contain logic keywords (if, for, while, switch, function, class, import, export)
    """
    if not diff_text or not diff_text.strip():
        return False, "Empty diff — not a valid micro-mode change"

    lines = diff_text.splitlines()

    # Count changed lines (+ and -, but not hunk headers or file paths)
    added = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    changed_lines = added + removed

    if changed_lines > 3:
        return False, f"Diff has {changed_lines} changed lines (max 3 for micro mode)"

    # Count unique file paths touched
    files = set()
    for l in lines:
        if l.startswith("+++ b/") or l.startswith("--- a/"):
            path = l[6:].strip()
            if path and path != "/dev/null":
                files.add(path)
    if len(files) > 1:
        return False, f"Diff touches {len(files)} files (max 1 for micro mode)"
    if not files:
        return False, "No file paths found in diff — not a valid unified diff"

    # Check for logic keywords
    diff_lower = diff_text.lower()
    for kw in _LOGIC_KEYWORDS:
        if kw in diff_lower:
            return False, f"Diff contains logic keyword '{kw}' — not a trivial change"

    return True, ""


@dataclass
class PhaseTransition:
    """Result of a phase transition attempt."""
    allowed: bool
    current_phase: str | None
    target_phase: str
    reason: str = ""
    task: Optional[Task] = None


class PipelineEnforcer:
    """
    Enforces pipeline phase ordering for tasks in the task_db.

    This is the deterministic spine — agents can't skip phases because
    the enforcer rejects out-of-order submissions.
    """

    def __init__(self, db: TaskDB):
        self.db = db

    def get_phase(self, task_id: str) -> str | None:
        """
        Determine the current phase of a task from its event log.
        Returns the last completed phase, or None if no phases completed.
        """
        history = self.db.get_task_history(task_id)
        completed_phases = [
            e.action for e in history
            if e.action in PHASES and e.verdict not in ("HARD_FAIL",)
        ]
        if not completed_phases:
            return None
        return completed_phases[-1]

    def can_enter(self, task_id: str, target_phase: str) -> PhaseTransition:
        """
        Check if a task can enter the target phase.
        Returns a PhaseTransition with allowed=True/False.
        """
        task = self.db.get_task(task_id)
        if not task:
            return PhaseTransition(
                allowed=False, current_phase=None, target_phase=target_phase,
                reason=f"Task {task_id} not found",
            )

        current = self.get_phase(task_id)

        # When a task is reset to PENDING (e.g. after unblock(debugger)), the phase
        # state machine needs to allow re-entry.  The old bandaid (PENDING + not RECALL
        # → reset to None) worked for one case but was fragile: it would reset even
        # when CONTEXT_GUARD or other phases had been genuinely completed, losing that
        # information.
        #
        # General fix: check whether the *target* phase has already been completed in
        # history.  RECALL and IMPLEMENT are always valid re-entry points for a reset
        # pipeline; every other completed phase is blocked from re-entry.
        if task.status == "PENDING":
            history = self.db.get_task_history(task_id)
            completed = {
                e.action for e in history
                if e.action in PHASES and e.verdict not in ("HARD_FAIL",)
            }
            if target_phase in ("RECALL", "IMPLEMENT"):
                # RECALL and IMPLEMENT are the only valid re-entry points after a
                # debugger-unblock → PENDING reset.  Allow them unconditionally.
                return PhaseTransition(
                    allowed=True, current_phase=current,
                    target_phase=target_phase, task=task,
                )
            if target_phase in completed:
                return PhaseTransition(
                    allowed=False, current_phase=current,
                    target_phase=target_phase,
                    reason=f"Phase {target_phase} already completed",
                    task=task,
                )
            # For any other uncompleted phase, reset current so the normal
            # transition logic below can find the correct chain.
            current = None

        # Check if we're in a terminal state
        if current in ("DONE", "FAILED"):
            return PhaseTransition(
                allowed=False, current_phase=current, target_phase=target_phase,
                reason=f"Task is in terminal state: {current}",
                task=task,
            )

        # Check task status for blocked/failed
        if task.status == "BLOCKED" and target_phase not in ("IMPLEMENT", "DEBUG", "VERIFY", "REVIEW", "EVAL"):
            return PhaseTransition(
                allowed=False, current_phase=current, target_phase=target_phase,
                reason=f"Task is BLOCKED — only IMPLEMENT, DEBUG, VERIFY, REVIEW, or EVAL allowed",
                task=task,
            )

        if task.status == "FAILED":
            return PhaseTransition(
                allowed=False, current_phase=current, target_phase=target_phase,
                reason=f"Task is FAILED — terminal state",
                task=task,
            )

        # Check transition validity
        # When BLOCKED, use BLOCKED transitions instead of the current phase's
        transition_source = "BLOCKED" if task.status == "BLOCKED" else current
        # Fast-mode tasks skip RECALL/CONCLUDE — allow IMPLEMENT directly from start,
        # and DONE directly from RETRO (skipping CONCLUDE)
        allowed_next = TRANSITIONS.get(transition_source, [])

        # Soft-pass re-entry: when a phase was soft-passed (HARD_FAIL verdict after
        # block), get_phase() returns that phase but it's already recorded in history.
        # Allow re-entry to that exact phase so the host can re-run it.
        if current in PHASES and target_phase == current:
            # Check if this phase was soft-passed (HARD_FAIL verdict)
            history = self.db.get_task_history(task_id)
            last_event = next((e for e in reversed(history) if e.action == current), None)
            if last_event and last_event.verdict == "SOFT_FAIL":
                return PhaseTransition(
                    allowed=True, current_phase=current,
                    target_phase=target_phase, task=task,
                )
        if task.phase_mode == "fast":
            if current is None:
                allowed_next = ["IMPLEMENT"]
            elif current == "RETRO":
                allowed_next = ["DONE", "FAILED"]
        if task.phase_mode == "micro":
            # Micro mode: IMPLEMENT → CONTEXT_GUARD → VERIFY → EVAL → DONE
            # Skip RECALL, CRITIQUE, REVIEW, RETRO, CONCLUDE, REFRESH_CONTEXT
            if current is None:
                allowed_next = ["IMPLEMENT"]
            elif current == "EVAL":
                allowed_next = ["DONE", "FAILED"]
            elif current == "VERIFY":
                allowed_next = ["EVAL"]
            elif current == "CONTEXT_GUARD":
                allowed_next = ["VERIFY"]
        if target_phase not in allowed_next:
            expected = " or ".join(allowed_next) if allowed_next else "none (terminal)"
            return PhaseTransition(
                allowed=False, current_phase=current, target_phase=target_phase,
                reason=(
                    f"Cannot go from {current or 'start'} to {target_phase}. "
                    f"Expected: {expected}"
                ),
                task=task,
            )

        return PhaseTransition(
            allowed=True, current_phase=current, target_phase=target_phase,
            task=task,
        )

    def mark_complete(
        self,
        task_id: str,
        phase: str,
        *,
        agent: str,
        summary: str = "",
        verdict: str = "PASS",
        changed_files: list[str] | None = None,
        diff_summary: str = "",
        findings: str = "",
        test_output_hash: str = "",
        mistakes_found: list[str] | None = None,
    ) -> PhaseTransition:
        """
        Mark a phase as complete for a task. Validates transition first.
        Returns PhaseTransition with allowed=True on success.
        Raises ValueError if transition is invalid.
        """
        check = self.can_enter(task_id, phase)
        if not check.allowed:
            raise ValueError(
                f"Pipeline violation: {check.reason}"
            )

        # Record the phase completion in task_db
        # We log directly to get the correct action name in the event trail.
        # complete_task/review_task/verify_task use generic action names,
        # but we need the phase name for get_phase() to work.
        if phase == "RECALL":
            self.db._log_event(
                task_id, agent, "RECALL", summary[:200],
                findings=findings, verdict=verdict,
            )
        elif phase == "IMPLEMENT":
            self.db.complete_task(
                task_id, agent=agent, summary=summary,
                changed_files=changed_files, diff_summary=diff_summary,
            )
            # Overwrite the action from "complete" to "IMPLEMENT"
            self._overwrite_last_action(task_id, "IMPLEMENT")
        elif phase == "CONTEXT_GUARD":
            self.db._log_event(
                task_id, agent, "CONTEXT_GUARD", summary,
                changed_files=changed_files or [], diff_summary=diff_summary,
            )
        elif phase == "CRITIQUE":
            self.db._log_event(
                task_id, agent, "CRITIQUE", summary[:200],
                findings=findings, verdict=verdict,
                mistakes_found=mistakes_found or [],
            )
        elif phase == "REVIEW":
            self.db.review_task(
                task_id, agent=agent, verdict=verdict,
                findings=findings, mistakes_found=mistakes_found,
            )
            self._overwrite_last_action(task_id, "REVIEW")
        elif phase == "APPROVAL":
            self.db._log_event(
                task_id, agent, "APPROVAL", summary[:200],
                findings=findings, verdict=verdict,
            )
            self._overwrite_last_action(task_id, "APPROVAL")
        elif phase == "VERIFY":
            self.db.verify_task(
                task_id, agent=agent,
                test_output_hash=test_output_hash, summary=summary,
            )
            self._overwrite_last_action(task_id, "VERIFY")
        elif phase == "RETRO":
            self.db._log_event(
                task_id, agent, "RETRO", summary[:200],
                findings=findings, verdict=verdict,
            )
        elif phase == "EVAL":
            self.db._log_event(
                task_id, agent, "EVAL", summary[:200],
                findings=findings, verdict=verdict,
            )
        elif phase == "CONCLUDE":
            self.db._log_event(
                task_id, agent, "CONCLUDE", summary[:200],
                findings=findings, verdict=verdict,
            )
        elif phase == "REFRESH_CONTEXT":
            self.db._log_event(
                task_id, agent, "REFRESH_CONTEXT", summary[:200],
                findings=findings, verdict=verdict,
            )
        elif phase == "DONE":
            self.db.done_task(task_id, agent=agent)
            self._overwrite_last_action(task_id, "DONE")
        elif phase == "BLOCKED":
            self.db.block_task(task_id, agent=agent, reason=summary)
        elif phase == "DEBUG":
            self.db._log_event(task_id, agent, "DEBUG", summary)

        return self.can_enter(task_id, phase)

    def block(self, task_id: str, *, agent: str, reason: str) -> PhaseTransition:
        """Block a task from any non-terminal phase."""
        task = self.db.get_task(task_id)
        if not task:
            return PhaseTransition(
                allowed=False, current_phase=None, target_phase="BLOCKED",
                reason=f"Task {task_id} not found",
            )
        if task.status in ("DONE", "FAILED"):
            return PhaseTransition(
                allowed=False, current_phase=task.status, target_phase="BLOCKED",
                reason=f"Task is in terminal state: {task.status}",
                task=task,
            )
        self.db.block_task(task_id, agent=agent, reason=reason)
        return PhaseTransition(
            allowed=True, current_phase=self.get_phase(task_id),
            target_phase="BLOCKED", task=task,
        )
    def _next_after_completed(self, task_id: str) -> str | None:
        """The phase that WOULD run next (i.e. the one that blocked), from history."""
        last = self.get_phase(task_id)
        if last is None:
            return "RECALL"
        try:
            return PHASES[PHASES.index(last) + 1]
        except (ValueError, IndexError):
            return None

    def unblock(self, task_id: str, *, decision: str = "proceed") -> PhaseTransition:
        """
        Unblock a task, ROUTING on the human decision (not a blind reset):
          - "proceed"/"override" → soft-pass the phase that blocked and move forward
          - anything else (debugger / re-implement / retry) → back to PENDING so the host
            re-implements (a debugger fix is re-submitted as a fresh IMPLEMENT, which
            re-runs the downstream phases on the corrected code)
        """
        task = self.db.get_task(task_id)
        if not task:
            return PhaseTransition(
                allowed=False, current_phase=None, target_phase="PENDING",
                reason=f"Task {task_id} not found",
            )
        if task.status != "BLOCKED":
            return PhaseTransition(
                allowed=False, current_phase=task.status, target_phase="PENDING",
                reason=f"Task is not BLOCKED (status: {task.status})",
                task=task,
            )
        self.db._log_event(task_id, "human", "unblock", f"Human decision: {decision}")

        d = decision.lower()
        if "proceed" in d or "override" in d:
            blocked = self._next_after_completed(task_id)
            if blocked in PHASES:
                # Record the blocked phase as soft-passed so get_phase advances past it.
                self.db._log_event(
                    task_id, "human", blocked,
                    f"HITL override: proceed past {blocked}", verdict="SOFT_FAIL",
                )
            self.db.reset_task(task_id, to_status="IN_PROGRESS")
            return PhaseTransition(
                allowed=True, current_phase=self.get_phase(task_id),
                target_phase="IN_PROGRESS", task=task,
            )

        # debugger / re-implement / retry / default → re-implement from a fresh diff
        self.db.reset_task(task_id, to_status="PENDING")
        return PhaseTransition(
            allowed=True, current_phase="PENDING", target_phase="PENDING", task=task,
        )

    def block_for_hitl(
        self,
        task_id: str,
        *,
        question: str,
        options: list[str] | None = None,
        context: str = "",
    ) -> PhaseTransition:
        """
        Block a task specifically for human-in-the-loop decision.
        Records the question and options in the event trail.
        The orchestrator should present this to the human and wait.
        """
        summary = f"HITL: {question}"
        if options:
            summary += f"\nOptions: {' | '.join(options)}"
        if context:
            summary += f"\nContext: {context}"

        result = self.block(task_id, agent="orchestrator", reason=summary)
        if result.allowed:
            self.db._log_event(
                task_id, "orchestrator", "hitl_request",
                summary,
                findings=question,
                verdict="BLOCK",
            )
        return result


    def fail(self, task_id: str, *, agent: str, reason: str) -> PhaseTransition:
        """Fail a task from any non-terminal phase."""
        self.db.fail_task(task_id, agent=agent, reason=reason)
        task = self.db.get_task(task_id)
        return PhaseTransition(
            allowed=True, current_phase="FAILED",
            target_phase="FAILED", task=task,
        )

    def _overwrite_last_action(self, task_id: str, new_action: str) -> None:
        """
        Overwrite the action of the most recent event for a task.
        Used to fix the action name when task_db methods use generic names
        (e.g., "complete") but we need phase names (e.g., "IMPLEMENT").
        """
        self.db._conn.execute("""
            UPDATE task_events SET action = ?
            WHERE id = (
                SELECT id FROM task_events
                WHERE task_id = ?
                ORDER BY timestamp DESC LIMIT 1
            )
        """, (new_action, task_id))
        self.db._conn.commit()

    def status(self, task_id: str) -> str:
        """Human-readable phase status for a task."""
        task = self.db.get_task(task_id)
        if not task:
            return f"Task {task_id}: NOT FOUND"

        current = self.get_phase(task_id)
        history = self.db.get_task_history(task_id)
        phase_events = [e for e in history if e.action in PHASES + ["DEBUG"]]

        lines = [
            f"Task [{task_id[:8]}]: {task.title}",
            f"  Status: {task.status} | Phase: {current or 'not started'} | Attempt: #{task.attempt}",
        ]

        if phase_events:
            lines.append("  Pipeline:")
            for e in phase_events:
                marker = "✓" if e.verdict not in ("HARD_FAIL",) else "✗"
                lines.append(f"    {marker} {e.action:15} — {e.summary[:60]}")

        next_allowed = TRANSITIONS.get(current, [])
        if next_allowed and next_allowed not in (["DONE"], []):
            lines.append(f"  Next allowed: {' | '.join(next_allowed)}")

        return "\n".join(lines)

    def dashboard(self) -> str:
        """Overview of all tasks and their pipeline state."""
        tasks = self.db.get_all_tasks()
        if not tasks:
            return "No tasks in DB."

        lines = [
            "=" * 60,
            "PIPELINE DASHBOARD",
            "=" * 60,
        ]

        # Group by status
        by_status = {}
        for t in tasks:
            by_status.setdefault(t.status, []).append(t)

        for status in ["IN_PROGRESS", "BLOCKED", "IMPLEMENTED", "REVIEWED",
                        "VERIFIED", "PENDING", "DONE", "FAILED"]:
            group = by_status.get(status, [])
            if not group:
                continue
            lines.append(f"\n{status} ({len(group)}):")
            for t in group:
                phase = self.get_phase(t.id)
                lines.append(
                    f"  [{t.id[:8]}] {t.title[:40]:40s}  "
                    f"phase={phase or 'start':15s}  attempt=#{t.attempt}"
                )

        lines.append("=" * 60)
        return "\n".join(lines)


# ── Helper for subagent prompts ──────────────────────────────────────────

def get_phase_prompt(task_id: str, phase: str, db: TaskDB) -> str:
    """
    Generate the prompt for a subagent assigned to a specific phase.
    Returns the system + user prompt pair the subagent should follow.
    """
    task = db.get_task(task_id)
    if not task:
        return f"ERROR: Task {task_id} not found."

    history = db.get_task_history(task_id)
    prior_phases = [e for e in history if e.action in PHASES]

    prompt = f"PHASE: {phase}\n"
    prompt += f"TASK: {task.title}\n"
    prompt += f"DESCRIPTION: {task.description}\n"
    prompt += f"DISCIPLINE: {task.discipline}\n"
    prompt += f"ATTEMPT: #{task.attempt}\n"
    prompt += f"MAX ATTEMPTS: {task.max_attempts}\n\n"

    if prior_phases:
        prompt += "COMPLETED PHASES:\n"
        for e in prior_phases:
            prompt += f"  {e.action}: {e.summary[:100]}\n"
        prompt += "\n"

    prompt += f"YOUR INSTRUCTIONS: {PHASE_DESCRIPTIONS.get(phase, phase)}\n"

    return prompt
