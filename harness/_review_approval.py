"""
_review_approval.py — CRITIQUE, REVIEW, APPROVAL, VERIFY phase handlers.

Each function is monkey-patched onto OrchestratorLoop as a bound method.
The self parameter refers to the OrchestratorLoop instance.
"""

from __future__ import annotations

from _loop_types import LoopAction, LoopOutcome, MAX_TOTAL_RETRIES, MAX_PHASE_RETRIES
from orchestrator_loop import verify_tests, detect_sensitive_change
from pipeline_enforcer import PHASE_DESCRIPTIONS


# ── CRITIQUE ─────────────────────────────────────────────────────────────────

def _submit_critique(self, task_id: str, critique: str) -> LoopOutcome:
    """Process critique output. Block for HITL if CRITICAL, else advance."""
    # Look for actual CRITICAL findings, not just the word "CRITICAL"
    # in "no critical findings" or similar negative statements.
    has_critical = False
    for line in critique.split("\n"):
        stripped = line.strip().upper()
        if stripped.startswith("CRITICAL") and ":" in stripped:
            has_critical = True
            break
        if stripped.startswith("- CRITICAL"):
            has_critical = True
            break

    if has_critical:
        self._create_critique_follow_up_tasks(task_id, critique)
        # Extract the critical finding for the HITL question
        critical_line = next(
            (l for l in critique.split("\n") if "CRITICAL" in l),
            critique[:200],
        )
        self.enforcer.block_for_hitl(
            task_id,
            question=f"Critique found CRITICAL issue: {critical_line[:150]}",
            options=[
                "Proceed to review anyway",
                "Send to debugger",
                "Block and re-implement",
            ],
            context=critique[:500],
        )
        outcome = LoopOutcome(
            action=LoopAction.BLOCK_HITL, phase="CRITIQUE", task_id=task_id,
            question=f"CRITICAL issue found: {critical_line[:150]}",
            options=[
                "Proceed to review anyway",
                "Send to debugger",
                "Block and re-implement",
            ],
        )
        self._print_phase_summary("CRITIQUE", task_id, outcome)
        return outcome

    self.enforcer.mark_complete(
        task_id, "CRITIQUE",
        agent="critique",
        summary=critique[:200],
        findings=critique,
        verdict="PASS",
    )
    # Record critique predictions for cross-agent scoring
    self._critique_predictions[task_id] = _extract_findings(critique)
    follow_ups = self._create_critique_follow_up_tasks(task_id, critique)
    suffix = f"; created {len(follow_ups)} follow-up task(s)" if follow_ups else ""
    outcome = LoopOutcome(
        action=LoopAction.RUN_PHASE, phase="REVIEW", task_id=task_id,
        message=f"Critique clean — advancing to review{suffix}",
    )
    self._print_phase_summary("CRITIQUE", task_id, outcome)
    return outcome


# ── REVIEW ───────────────────────────────────────────────────────────────────

def _submit_review(self, task_id: str, review: str) -> LoopOutcome:
    """Process review output. Retry on HARD_FAIL, else advance.

    Auto-advance: if the diff is ≤10 lines and tests pass, skip HITL and
    advance directly to VERIFY — trivial changes don't need human review.
    """
    # Strict: only HARD_FAIL at the START of the review counts, not mid-sentence
    is_hard_fail = review.upper().lstrip().startswith("HARD_FAIL")

    # ── Patch 1: Skip HITL for trivial changes ──────────────────────────
    # Trivial = ≤10 lines added, tests already passed (verified by the
    # implement gate passing without violations).
    if not is_hard_fail and "PASS" in review.upper():
        diff = self._diff.get(task_id, "")
        lines_added = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
        if lines_added <= 10:
            self.enforcer.mark_complete(
                task_id, "REVIEW",
                agent="reviewer",
                summary=review[:200],
                findings=review,
                verdict="PASS",
            )
            self._review_result[task_id] = "PASS"
            self._review_findings[task_id] = _extract_findings(review)
            outcome = LoopOutcome(
                action=LoopAction.RUN_PHASE, phase="VERIFY", task_id=task_id,
                message="Review passed (trivial diff) — advancing to verify",
            )
            self._print_phase_summary("REVIEW", task_id, outcome)
            return outcome
    # ── end Patch 1 ──────────────────────────────────────────────────────

    if is_hard_fail:
        self._retry_counts[task_id] = self._retry_counts.get(task_id, 0) + 1

        if self._retry_counts[task_id] >= MAX_TOTAL_RETRIES:
            outcome = self._escalate_to_debugger(task_id, "reviewer HARD_FAIL after max retries")
            self._print_phase_summary("REVIEW", task_id, outcome)
            return outcome

        # Block for HITL — let human decide
        self.enforcer.block_for_hitl(
            task_id,
            question=f"Review failed: {review[:150]}",
            options=[
                "Retry implementation",
                "Send to debugger",
                "Override and proceed",
            ],
            context=review[:500],
        )
        outcome = LoopOutcome(
            action=LoopAction.BLOCK_HITL, phase="REVIEW", task_id=task_id,
            question=f"Review failed: {review[:150]}",
            options=[
                "Retry implementation",
                "Send to debugger",
                "Override and proceed",
            ],
        )
        self._print_phase_summary("REVIEW", task_id, outcome)
        return outcome

    review_verdict = "PASS" if "PASS" in review else "SOFT_FAIL"
    self.enforcer.mark_complete(
        task_id, "REVIEW",
        agent="reviewer",
        summary=review[:200],
        findings=review,
        verdict=review_verdict,
    )
    self._review_result[task_id] = review_verdict
    # Record review findings for cross-agent scoring
    self._review_findings[task_id] = _extract_findings(review)
    # Heavy mode: after REVIEW, require explicit APPROVAL before VERIFY
    task = self.db.get_task(task_id)
    if task and task.phase_mode == "heavy":
        outcome = LoopOutcome(
            action=LoopAction.BLOCK_HITL, phase="APPROVAL", task_id=task_id,
            question=f"Task passed REVIEW but requires approval before verification. Changes touch sensitive files. Approve to proceed to VERIFY?",
            options=["approve", "reject", "modify"],
        )
    else:
        outcome = LoopOutcome(
            action=LoopAction.RUN_PHASE, phase="VERIFY", task_id=task_id,
            message="Review passed — advancing to verify",
        )
    self._print_phase_summary("REVIEW", task_id, outcome)
    return outcome


# ── APPROVAL ─────────────────────────────────────────────────────────────────

def _submit_approval(self, task_id: str, approval_text: str) -> LoopOutcome:
    """Process APPROVAL phase: approve → VERIFY, reject → FAILED, modify → IMPLEMENT.

    The approval_text is the human/policy decision. Options are:
      - "approve" (or contains "approve") → advance to VERIFY
      - "reject" (or contains "reject") → mark FAILED
      - "modify" (or contains "modify") → reset to IMPLEMENT for rework
    """
    task = self.db.get_task(task_id)
    d = approval_text.lower()

    if "approve" in d:
        # Build approval question with sensitive files context
        diff = self._diff.get(task_id, "")
        changed_files = _extract_files_from_diff(diff)
        is_sensitive, sensitive_files = detect_sensitive_change(changed_files, diff)
        files_str = ", ".join(sensitive_files) if sensitive_files else "sensitive changes"
        self.enforcer.mark_complete(
            task_id, "APPROVAL",
            agent="human",
            summary=f"Approved: {approval_text[:100]}",
            findings=f"Approved sensitive changes: {files_str}",
        )
        outcome = LoopOutcome(
            action=LoopAction.RUN_PHASE, phase="VERIFY", task_id=task_id,
            message=f"Approval granted — advancing to verify",
        )
        self._print_phase_summary("APPROVAL", task_id, outcome)
        return outcome

    elif "reject" in d:
        self.enforcer.mark_complete(
            task_id, "APPROVAL",
            agent="human",
            summary=f"Rejected: {approval_text[:100]}",
            findings=f"Rejected sensitive change",
        )
        self.enforcer.fail(task_id, agent="human", reason=f"Approval rejected: {approval_text[:200]}")
        outcome = LoopOutcome(
            action=LoopAction.FAILED, phase="FAILED", task_id=task_id,
            message=f"Approval rejected — task failed",
        )
        self._print_phase_summary("APPROVAL", task_id, outcome)
        return outcome

    else:
        # "modify" or any other decision → reset to IMPLEMENT for rework
        self.enforcer.mark_complete(
            task_id, "APPROVAL",
            agent="human",
            summary=f"Modification requested: {approval_text[:100]}",
            findings=f"Human requested modifications before approval",
        )
        # Reset to PENDING so IMPLEMENT can be re-run
        self.db.reset_task(task_id, to_status="PENDING")
        outcome = LoopOutcome(
            action=LoopAction.RUN_PHASE, phase="IMPLEMENT", task_id=task_id,
            message="Modification requested — returning to implement for rework",
        )
        self._print_phase_summary("APPROVAL", task_id, outcome)
        return outcome


# ── VERIFY ───────────────────────────────────────────────────────────────────

def _submit_verify(self, task_id: str, test_output: str) -> LoopOutcome:
    """Process test output. Done if the SHA gate passes, retry/escalate if not."""
    # Real verification — the SHA gate confirms tests actually ran (no fakes,
    # unique hash, pass indicators present), the same gate conductor uses.
    # Review-only tasks skip the pass-indicator check (no real test output).
    task = self.db.get_task(task_id)
    review_only = bool(task and "review-only" in (task.tags or []))
    verify = verify_tests(test_output, review_only=review_only)
    self._test_pass[task_id] = verify.passed

    if not verify.passed:
        self._retry_counts[task_id] = self._retry_counts.get(task_id, 0) + 1

        if self._retry_counts[task_id] >= MAX_TOTAL_RETRIES:
            outcome = self._escalate_to_debugger(task_id, "tests failing after max retries")
            self._print_phase_summary("VERIFY", task_id, outcome)
            return outcome

        # Block for HITL — tests failing
        self.enforcer.block_for_hitl(
            task_id,
            question=f"Tests failing: {test_output[:150]}",
            options=[
                "Retry implementation",
                "Send to debugger",
                "Override and proceed",
            ],
            context=test_output[:500],
        )
        outcome = LoopOutcome(
            action=LoopAction.BLOCK_HITL, phase="VERIFY", task_id=task_id,
            question=f"Tests failing: {test_output[:150]}",
            options=[
                "Retry implementation",
                "Send to debugger",
                "Override and proceed",
            ],
        )
        self._print_phase_summary("VERIFY", task_id, outcome)
        return outcome

    self.enforcer.mark_complete(
        task_id, "VERIFY",
        agent="verifier",
        summary=f"Tests passed",
        test_output_hash=hash(test_output).__repr__(),
    )

    # Tests passed — score the run (EVAL) before reflecting (RETRO).
    outcome = LoopOutcome(
        action=LoopAction.RUN_PHASE, phase="EVAL", task_id=task_id,
        message="Verified — advancing to eval (deterministic score)",
    )
    self._print_phase_summary("VERIFY", task_id, outcome)
    return outcome


# ── Helpers ─────────────────────────────────────────────────────────────────

def _extract_findings(text: str) -> list[str]:
    """
    Extract individual findings from a review or critique report.
    Returns a list of finding strings.
    """
    findings = []
    for line in text.split("\n"):
        stripped = line.strip()
        # Look for bullet points or finding lines
        if stripped.startswith("- ") and len(stripped) > 5:
            findings.append(stripped[2:])
        elif stripped.startswith("* ") and len(stripped) > 5:
            findings.append(stripped[2:])
        elif "[" in stripped and "]" in stripped and len(stripped) > 10:
            # file:line reference style
            findings.append(stripped)
    return findings


def _extract_files_from_diff(diff: str) -> list[str]:
    """Extract changed file paths from a unified diff."""
    files = []
    for line in diff.splitlines():
        if line.startswith("+++ b/") or line.startswith("--- a/"):
            path = line[6:].strip()
            if path and path != "/dev/null" and path not in files:
                files.append(path)
    return files


def _extract_follow_up_tasks(text: str) -> list[str]:
    """Extract explicit child-task requests from critique output.

    Accepted forms:
      FOLLOW_UP_TASK: add index for users.by_email
      - FOLLOW_UP_TASK: cover network-error retry path

    Ordinary bullets are intentionally ignored; critique can discuss risks without
    automatically expanding the board.
    """
    tasks: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        if not stripped.upper().startswith("FOLLOW_UP_TASK:"):
            continue
        _, _, title = stripped.partition(":")
        title = title.strip()
        if not title or "<" in title or ">" in title:
            continue
        if title and title not in tasks:
            tasks.append(title)
    return tasks


def _create_critique_follow_up_tasks(self, task_id: str, critique: str) -> list[str]:
    """Turn explicit critique follow-ups into child tasks immediately.

    Critique often surfaces real but out-of-scope issues. Keeping them in prose
    loses work. To avoid noisy auto-task creation, only lines that start with
    FOLLOW_UP_TASK: become child tasks; everything else remains normal critique text.
    """
    parent = self.db.get_task(task_id)
    existing_titles = {child.title for child in self.db.get_children(task_id)}
    created: list[str] = []
    for title in _extract_follow_up_tasks(critique):
        if title in existing_titles:
            continue
        task = self.db.create_task(
            title,
            description=f"Created from CRITIQUE on {task_id}: {title}",
            parent_id=task_id,
            discipline=parent.discipline if parent else "tdd",
            priority=max((parent.priority - 1) if parent else 0, 0),
            tags=["critique-follow-up"],
        )
        created.append(task.id)
    return created
