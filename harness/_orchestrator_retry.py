"""
_orchestrator_retry.py — Retry logic and miscellaneous helpers.

Contains:
- MAX_PHASE_RETRIES (re-exported)
- _bump_retry
- _reset_phase_retry
- _impl_retry_or_escalate
- _escalate_to_debugger
- _read_agent_body
- _diff_stats
- summarize_incomplete

Each function is monkey-patched onto OrchestratorLoop as a bound method
(except MAX_PHASE_RETRIES which is a module-level constant).
The self parameter refers to the OrchestratorLoop instance.
"""

from __future__ import annotations

from _loop_types import LoopAction, LoopOutcome, MAX_TOTAL_RETRIES, AGENTS_DIR, MAX_PHASE_RETRIES


# ── Retry helpers ───────────────────────────────────────────────────────────

def _bump_retry(self, task_id: str, phase: str) -> bool:
    """Increment retry counter for a phase. Returns True if budget exhausted."""
    if task_id not in self._phase_retry_counts:
        self._phase_retry_counts[task_id] = {}
    self._phase_retry_counts[task_id][phase] = (
        self._phase_retry_counts[task_id].get(phase, 0) + 1
    )
    max_retries = MAX_PHASE_RETRIES.get(phase, 3)
    return self._phase_retry_counts[task_id][phase] >= max_retries


def _reset_phase_retry(self, task_id: str, phase: str) -> None:
    """Reset retry counter for a phase on successful completion."""
    if task_id in self._phase_retry_counts:
        self._phase_retry_counts[task_id].pop(phase, None)


# ── Escalation ───────────────────────────────────────────────────────────────

def _impl_retry_or_escalate(self, task_id: str, name: str, reason: str) -> LoopOutcome:
    """
    Shared IMPLEMENT-failure handling: bump the retry counters and either
    ask the host to retry, or escalate once the total-retry budget is spent.
    """
    self._impl_retry_counts[task_id] = self._impl_retry_counts.get(task_id, 0) + 1
    total = self._retry_counts.get(task_id, 0) + 1
    self._retry_counts[task_id] = total
    if total >= MAX_TOTAL_RETRIES:
        outcome = self._escalate_to_debugger(
            task_id, f"'{name}' failing after max retries"
        )
        self._print_phase_summary("IMPLEMENT", task_id, outcome)
        return outcome
    outcome = LoopOutcome(
        action=LoopAction.RETRY, phase="IMPLEMENT", task_id=task_id,
        message=f"[{name}] failed (attempt {self._impl_retry_counts[task_id]}): {reason[:120]}",
    )
    self._print_phase_summary("IMPLEMENT", task_id, outcome)
    return outcome


def _escalate_to_debugger(self, task_id: str, reason: str) -> LoopOutcome:
    """
    Escalate to debugger after retries are exhausted. Records the failed
    attempt as a negative reward (the loop must learn from losses too) and
    blocks for a human decision.
    """
    self._record_reward(task_id)
    self.enforcer.block_for_hitl(
        task_id,
        question=f"Needs debugger: {reason}",
        options=[
            "Dispatch debugger",
            "Manual fix",
            "Abandon task",
        ],
        context=reason,
    )
    return LoopOutcome(
        action=LoopAction.BLOCK_HITL, phase="IMPLEMENT", task_id=task_id,
        question=f"Needs debugger: {reason}",
        options=["Dispatch debugger", "Manual fix", "Abandon task"],
    )


# ── Agent body reader ────────────────────────────────────────────────────────

def _read_agent_body(self, phase: str) -> str:
    """Read the agent .md file for a phase, return body (frontmatter stripped)."""
    agent_map = {
        "RECALL": "recaller",
        "IMPLEMENT": "implementer",
        "CONTEXT_GUARD": "context-guard",
        "CRITIQUE": "critique",
        "REVIEW": "reviewer",
        "VERIFY": "verifier",
        "CONCLUDE": "concluder",
        "DEBUG": "debugger",
    }
    agent_name = agent_map.get(phase, phase.lower())
    path = AGENTS_DIR / f"{agent_name}.md"
    if not path.exists():
        return f"No agent definition for {agent_name}"
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        _, _, body = text.partition("---\n")
        _, _, body = body.partition("---\n")
        return body.strip()
    return text.strip()


# ── Diff helpers ─────────────────────────────────────────────────────────────

def _diff_stats(self, diff: str) -> str:
    """Generate +N -M stats from a unified diff."""
    added = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
    return f"+{added} -{removed}"


# ── Completion indicator ─────────────────────────────────────────────────────

def summarize_incomplete(self, task_id: str) -> str:
    """
    Human-readable completion indicator for a task.

    ✓ TASK COMPLETE: <id> — RECALL → ... → DONE (N/N phases)
    ⚠ TASK INCOMPLETE: <id>
    Completed: RECALL → IMPLEMENT → ...
    Stuck at: REVIEW (BLOCK_HITL — escalated after 3 retries)
    Never reached: VERIFY, EVAL, RETRO, CONCLUDE, REFRESH_CONTEXT, DONE

    Respects phase_mode so skipped phases don't appear in "Never reached".
    """
    from pipeline_enforcer import PHASES

    task = self.db.get_task(task_id)
    history = self.db.get_task_history(task_id)

    # Completed phases: exclude HARD_FAIL verdicts (those phases were attempted but failed)
    completed = [
        e.action for e in history
        if e.action in PHASES and e.verdict not in ("HARD_FAIL",)
    ]
    # Deduplicate in order of first completion
    seen: set[str] = set()
    unique_completed: list[str] = []
    for p in completed:
        if p not in seen:
            seen.add(p)
            unique_completed.append(p)

    expected = self._expected_phases(task_id)

    # Is the task done?
    if task and task.status == "DONE":
        completed_str = " → ".join(unique_completed) if unique_completed else "none"
        total = len(expected)
        return f"✓ TASK COMPLETE: {task_id} — {completed_str} ({total}/{total} phases)"

    # Not done — figure out where it got stuck
    # The stuck phase is the last completed phase (or "none")
    stuck_at = unique_completed[-1] if unique_completed else "none"

    # Count retries on the stuck phase to build the reason string
    retry_count = 0
    if stuck_at != "none":
        retry_count = sum(
            1 for e in history
            if e.action == stuck_at and e.verdict in ("SOFT_FAIL", "HARD_FAIL")
        )

    # Check if there's a HITL block recorded (hitl_request events have verdict='BLOCK')
    hitl_block = next(
        (e for e in reversed(history) if e.action == "hitl_request" and e.verdict == "BLOCK"),
        None,
    )
    if hitl_block is not None:
        reason = f"{stuck_at} (BLOCK_HITL — escalated after {retry_count} retries)"
    elif stuck_at != "none":
        reason = stuck_at
    else:
        reason = "none"

    never_reached = [p for p in expected if p not in set(unique_completed)]
    never_str = ", ".join(never_reached) if never_reached else "none"

    completed_str = " → ".join(unique_completed) if unique_completed else "none"
    lines = [
        f"⚠ TASK INCOMPLETE: {task_id}",
        f"Completed: {completed_str}",
        f"Stuck at: {reason}",
        f"Never reached: {never_str}",
    ]
    return "\n".join(lines)
