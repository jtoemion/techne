"""
_recall_implement.py — RECALL, IMPLEMENT, CONTEXT_GUARD, DEBUG phase handlers.

Each function is monkey-patched onto OrchestratorLoop as a bound method.
The self parameter refers to the OrchestratorLoop instance.
"""

from __future__ import annotations

from _loop_types import LoopAction, LoopOutcome, MAX_PHASE_RETRIES
from orchestrator_loop import (
    run_gates, measure_scope, validate_mode_fit,
    _compute_diff_stats, _log_mode_override,
    check_honcho_logged,
)


# ── RECALL ─────────────────────────────────────────────────────────────────

def _submit_recall(self, task_id: str, result: str) -> LoopOutcome:
    """Process RECALL phase output.

    Full-mode recall must name both the durable Honcho context and the
    workshop retrieval artifact used to ground IMPLEMENT.
    """
    task = self.db.get_task(task_id)
    if not result or len(result.strip()) < 20:
        if self._bump_retry(task_id, "RECALL"):
            outcome = LoopOutcome(
                action=LoopAction.FAILED, phase="RECALL", task_id=task_id,
                message=f"RECALL failed after {MAX_PHASE_RETRIES['RECALL']} attempts. Escalating.",
            )
        else:
            outcome = LoopOutcome(
                action=LoopAction.RETRY, phase="RECALL", task_id=task_id,
                message=(
                    "RECALL produced no usable context. Include HONCHO_CONTEXT and "
                    "WORKSHOP_CONTEXT lines backed by real recall output."
                ),
            )
        self._print_phase_summary("RECALL", task_id, outcome)
        return outcome

    recall_lower = result.lower()
    conclusion_id = check_honcho_logged()
    has_honcho = conclusion_id is not None
    has_workshop = "workshop_context:" in recall_lower
    if not has_honcho:
        if self._bump_retry(task_id, "RECALL"):
            outcome = LoopOutcome(
                action=LoopAction.FAILED, phase="RECALL", task_id=task_id,
                message=f"RECALL failed after {MAX_PHASE_RETRIES['RECALL']} attempts. Escalating.",
            )
        else:
            outcome = LoopOutcome(
                action=LoopAction.RETRY, phase="RECALL", task_id=task_id,
                message=(
                    "RECALL missing HONCHO_CONTEXT line. Return structured proof like "
                    "'HONCHO_CONTEXT: <durable context>'."
                ),
            )
        self._print_phase_summary("RECALL", task_id, outcome)
        return outcome
    if task and task.phase_mode != "fast" and not has_workshop:
        if self._bump_retry(task_id, "RECALL"):
            outcome = LoopOutcome(
                action=LoopAction.FAILED, phase="RECALL", task_id=task_id,
                message=f"RECALL failed after {MAX_PHASE_RETRIES['RECALL']} attempts. Escalating.",
            )
        else:
            outcome = LoopOutcome(
                action=LoopAction.RETRY, phase="RECALL", task_id=task_id,
                message=(
                    "RECALL missing WORKSHOP_CONTEXT line. Run the workshop retrieval "
                    "packet and name the context docs/files you used."
                ),
            )
        self._print_phase_summary("RECALL", task_id, outcome)
        return outcome

    self._reset_phase_retry(task_id, "RECALL")
    self.enforcer.mark_complete(
        task_id, "RECALL",
        agent="recaller",
        summary=f"Recall artifact: {result[:150]}",
        findings=result,
    )

    outcome = LoopOutcome(
        action=LoopAction.RUN_PHASE, phase="IMPLEMENT", task_id=task_id,
        message="Context recalled — advancing to implement",
    )
    self._print_phase_summary("RECALL", task_id, outcome)
    return outcome


# ── IMPLEMENT ───────────────────────────────────────────────────────────────

def _submit_implement(self, task_id: str, diff: str) -> LoopOutcome:
    """Process implementer output. Check gates, retry or advance."""
    task = self.db.get_task(task_id)

    # Enforce Honcho recall contract: IMPLEMENT requires a prior RECALL phase
    # Skip for fast-mode tasks (review-only, no RECALL/CONCLUDE)
    history = self.db.get_task_history(task_id)
    has_recall = any(e.action == "RECALL" for e in history)
    if not has_recall and (task and task.phase_mode not in ("fast", "micro")):
        outcome = LoopOutcome(
            action=LoopAction.RETRY, phase="IMPLEMENT", task_id=task_id,
            message="RECALL phase required: run honcho_search or honcho_context first to recall durable context.",
        )
        self._print_phase_summary("IMPLEMENT", task_id, outcome)
        return outcome
    if task and task.phase_mode not in ("fast", "micro"):
        latest_recall = next((e for e in reversed(history) if e.action == "RECALL"), None)
        recall_findings = (latest_recall.findings if latest_recall else "") or ""
        if "workshop_context:" not in recall_findings.lower():
            outcome = LoopOutcome(
                action=LoopAction.RETRY, phase="IMPLEMENT", task_id=task_id,
                message=(
                    "IMPLEMENT blocked: latest RECALL artifact does not reference "
                    "WORKSHOP_CONTEXT. Re-run RECALL with the workshop retrieval packet first."
                ),
            )
            self._print_phase_summary("IMPLEMENT", task_id, outcome)
            return outcome

    # Check if the result looks like a valid diff
    has_diff = bool(diff.strip()) and ("@@ " in diff or "--- " in diff)

    if not has_diff:
        return self._impl_retry_or_escalate(
            task_id, "diff", "implementer produced no valid diff"
        )

    # ── Phase-mode fit validation ───────────────────────────────────────
    # After we have a real diff, verify the chosen phase_mode matches the work.
    # Extract file count from the diff for validate_mode_fit.
    file_count = len(_extract_files(diff))
    valid, reason, suggested = validate_mode_fit(
        task.phase_mode if task else "full", diff, file_count
    )
    if not valid:
        diff_stats = _compute_diff_stats(diff)
        _log_mode_override(
            task_id,
            task.phase_mode if task else "full",
            suggested,
            diff_stats,
        )
        # Auto-switch lane: update task's phase_mode to match the diff
        if task:
            old_mode = task.phase_mode
            self.db._conn.execute("UPDATE tasks SET phase_mode = ? WHERE id = ?",
                                    (suggested, task_id))
            self.db._conn.commit()
            # Refresh task object
            task = self.db.get_task(task_id)
            print(f"[IMPLEMENT] Lane switch: {old_mode} → {suggested} ({reason})")
        outcome = LoopOutcome(
            action=LoopAction.RUN_PHASE,
            phase="CONTEXT_GUARD",
            task_id=task_id,
            message=f"Lane switch: {reason}. Continuing as {suggested} mode.",
        )
        self._print_phase_summary("IMPLEMENT", task_id, outcome)
        return outcome

    # ── Real deterministic enforcement (the merge with conductor) ──────
    # Run the same hard gates conductor runs, so the RL reward signal
    # reflects real enforcement, not hardcoded True. Scope/intent is only
    # measured once the gates pass — a rejected diff is not advanced.
    self._diff[task_id] = diff
    gate = run_gates(diff, self.registry)
    self._gate_pass[task_id] = gate.passed
    if not gate.passed:
        self._gate_violations[task_id] = self._gate_violations.get(task_id, 0) + 1
        return self._impl_retry_or_escalate(task_id, gate.gate_name, gate.violation)

    task_text = f"{task.title} {task.description}".strip()
    scope = measure_scope(task_text, diff)
    self._scope[task_id] = scope
    self._scope_clean[task_id] = scope.scope_clean
    if scope.intent_mismatch:
        return self._impl_retry_or_escalate(task_id, "intent", scope.violation)

    # Record implementation
    self.enforcer.mark_complete(
        task_id, "IMPLEMENT",
        agent="implementer",
        summary=f"Diff: {diff[:200]}",
        changed_files=_extract_files(diff),
        diff_summary=self._diff_stats(diff),
    )
    self._impl_retry_counts[task_id] = 0

    outcome = LoopOutcome(
        action=LoopAction.RUN_PHASE, phase="CONTEXT_GUARD", task_id=task_id,
        message="Implementation complete — advancing to context-guard",
    )
    self._print_phase_summary("IMPLEMENT", task_id, outcome)
    return outcome


# ── CONTEXT_GUARD ───────────────────────────────────────────────────────────

def _submit_context_guard(self, task_id: str, audit: str) -> LoopOutcome:
    """Process context-guard output. Validate punch list, then advance.

    The context-guard agent MUST emit a CONCLUDE PUNCH LIST with at least
    DOCS, CONTEXT, and HONCHO entries. A lazy agent that skips it produces
    no guidance for CONCLOSE — the gate catches this.
    """
    # Validate punch list presence — requires structured prefix, not bare substring
    audit_lower = audit.lower()
    has_punch_list = "conclude punch list" in audit_lower or "docs:" in audit_lower
    if not has_punch_list:
        if self._bump_retry(task_id, "CONTEXT_GUARD"):
            outcome = LoopOutcome(
                action=LoopAction.FAILED, phase="CONTEXT_GUARD", task_id=task_id,
                message=f"CONTEXT_GUARD failed after {MAX_PHASE_RETRIES['CONTEXT_GUARD']} attempts. Escalating.",
            )
        else:
            outcome = LoopOutcome(
                action=LoopAction.RETRY, phase="CONTEXT_GUARD", task_id=task_id,
                message=(
                    "CONTEXT_GUARD output missing CONCLUDE PUNCH LIST. "
                    "Include a section with DOCS, CONTEXT, and HONCHO entries "
                    "(each with updated path or NOT_NEEDED reason). "
                    "This is required — CONCLOSE cannot close without it."
                ),
            )
        self._print_phase_summary("CONTEXT_GUARD", task_id, outcome)
        return outcome

    self._reset_phase_retry(task_id, "CONTEXT_GUARD")
    self.enforcer.mark_complete(
        task_id, "CONTEXT_GUARD",
        agent="context-guard",
        summary=audit[:200],
        findings=audit,
    )
    # Micro mode: skip CRITIQUE and REVIEW — go directly to VERIFY
    task = self.db.get_task(task_id)
    if task and task.phase_mode == "micro":
        outcome = LoopOutcome(
            action=LoopAction.RUN_PHASE, phase="VERIFY", task_id=task_id,
            message="Audit complete — advancing to verify (micro mode)",
        )
        self._print_phase_summary("CONTEXT_GUARD", task_id, outcome)
        return outcome
    outcome = LoopOutcome(
        action=LoopAction.RUN_PHASE, phase="CRITIQUE", task_id=task_id,
        message="Audit complete — advancing to critique",
    )
    self._print_phase_summary("CONTEXT_GUARD", task_id, outcome)
    return outcome


# ── DEBUG ───────────────────────────────────────────────────────────────────

def _submit_debug(self, task_id: str, diff: str) -> LoopOutcome:
    """A debugger session produced a corrected implementation. Reset to a fresh
    state and re-enter the pipeline as a new IMPLEMENT, so CONTEXT_GUARD / CRITIQUE /
    REVIEW / VERIFY all re-run on the FIXED code (the prior audits are now stale).
    This is the clean BLOCKED→DEBUG→IMPLEMENT re-entry the TRANSITIONS table promises.
    """
    self.db.reset_task(task_id, to_status="PENDING")
    return self._submit_implement(task_id, diff)


# ── Helper shared by _submit_implement ──────────────────────────────────────

def _extract_files(diff: str) -> list[str]:
    """Extract changed file paths from a unified diff."""
    files = []
    for line in diff.splitlines():
        if line.startswith("+++ b/") or line.startswith("--- a/"):
            path = line[6:].strip()
            if path and path != "/dev/null" and path not in files:
                files.append(path)
    return files
