"""
pipeline_enforcer.py — State machine that enforces the multi-agent pipeline order.

The pipeline phases are:
  RECALL → IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → EVAL → RETRO → CONCLUDE → DONE
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
from typing import Optional

from task_db import TaskDB, Task


# ── Phase definitions ────────────────────────────────────────────────────

PHASES = [
    "RECALL",
    "IMPLEMENT",
    "CONTEXT_GUARD",
    "CRITIQUE",
    "REVIEW",
    "VERIFY",
    "EVAL",
    "RETRO",
    "CONCLUDE",
    "DONE",
]

# Valid transitions: from_state -> allowed next states
# The pipeline is strict: you can only go forward, or to BLOCKED/DEBUG from any point.
TRANSITIONS = {
    None:           ["RECALL"],                              # fresh task → recall context
    "PENDING":      ["RECALL"],                              # ready to start → recall first
    "BLOCKED":      ["IMPLEMENT", "DEBUG"],                  # retry after block
    "DEBUG":        ["IMPLEMENT"],                           # debug fixes, then re-implement
    "RECALL":       ["IMPLEMENT", "BLOCKED", "FAILED"],      # recall done → implement
    "IMPLEMENT":    ["CONTEXT_GUARD", "BLOCKED", "FAILED"],  # impl done → audit, or fail
    "CONTEXT_GUARD":["CRITIQUE", "BLOCKED", "FAILED"],       # audit done → critique, or fail
    "CRITIQUE":     ["REVIEW", "BLOCKED", "FAILED"],         # critique done → review, or fail
    "REVIEW":       ["VERIFY", "BLOCKED", "IMPLEMENT", "FAILED"],  # review: pass→verify, hardfail→re-implement
    "VERIFY":       ["EVAL", "BLOCKED", "IMPLEMENT", "FAILED"],    # verify: pass→eval(score), fail→re-implement
    "EVAL":         ["RETRO", "FAILED"],                     # deterministic 100-pt score → reflect
    "RETRO":        ["CONCLUDE", "FAILED"],                  # reflect on the score → conclude
    "CONCLUDE":     ["DONE", "FAILED"],                      # durable write-back → done
    "DONE":         [],                                      # terminal
    "FAILED":       [],                                      # terminal
}

# Human-readable phase descriptions (for subagent prompts)
PHASE_DESCRIPTIONS = {
    "RECALL": "Recall durable context from Honcho for this task title and tags. Run honcho_search or honcho_context and return the excerpts.",
    "IMPLEMENT": "Write code (TDD: test first, minimal diff)",
    "CONTEXT_GUARD": "Scan changes, record audit trail (file inventory, scope check)",
    "CRITIQUE": "Predict emergent bugs from the implementation diff",
    "REVIEW": "Security/correctness/gate compliance review",
    "VERIFY": "Run tests, capture real output",
    "EVAL": "Score the run deterministically (100-point eval report)",
    "RETRO": "Reflect on the run — lessons, recurrence, skill-edit proposals",
    "CONCLUDE": "Write durable facts back to Honcho (conclusion IDs as proof)",
    "DONE": "Task complete",
    "BLOCKED": "Task blocked — needs human input or debugger",
    "FAILED": "Task terminal failure",
    "DEBUG": "Debugger diagnosing root cause",
}


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

        # A reset/fresh task (status PENDING) may (re)start at RECALL even if older
        # completed-phase events still linger in history. Without this, an unblock that
        # resets to PENDING stayed "stuck" at the last completed phase (e.g. CONTEXT_GUARD)
        # and could never re-enter RECALL — the live HITL→debugger deadlock.
        # Exception: if RECALL is already completed, don't reset to None.
        if task.status == "PENDING" and current != "RECALL":
            current = None

        # Check if we're in a terminal state
        if current in ("DONE", "FAILED"):
            return PhaseTransition(
                allowed=False, current_phase=current, target_phase=target_phase,
                reason=f"Task is in terminal state: {current}",
                task=task,
            )

        # Check task status for blocked/failed
        if task.status == "BLOCKED" and target_phase not in ("IMPLEMENT", "DEBUG"):
            return PhaseTransition(
                allowed=False, current_phase=current, target_phase=target_phase,
                reason=f"Task is BLOCKED — only IMPLEMENT or DEBUG allowed",
                task=task,
            )

        if task.status == "FAILED":
            return PhaseTransition(
                allowed=False, current_phase=current, target_phase=target_phase,
                reason=f"Task is FAILED — terminal state",
                task=task,
            )

        # Check transition validity
        # Fast-mode tasks skip RECALL/CONCLUDE — allow IMPLEMENT directly from start,
        # and DONE directly from RETRO (skipping CONCLUDE)
        allowed_next = TRANSITIONS.get(current, [])
        if task.phase_mode == "fast":
            if current is None:
                allowed_next = ["IMPLEMENT"]
            elif current == "RETRO":
                allowed_next = ["DONE", "FAILED"]
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
