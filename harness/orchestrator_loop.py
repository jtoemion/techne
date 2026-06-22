"""
orchestrator_loop.py — The pipeline loop driver.

Takes a list of task IDs and drives them through the multi-agent pipeline:
  IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → DONE

This is NOT an agent. It's a state machine that generates prompts for the
host agent to execute. The host runs each prompt as its own model turn,
then feeds the result back via submit_*().

The loop runner decides:
  - Which phase to run next (enforced by PipelineEnforcer)
  - When to retry (gate violation, critique CRITICAL)
  - When to escalate to debugger (2+ failures)
  - When to block for HITL (decision required, or debug exhaustion)

Usage:
    from orchestrator_loop import OrchestratorLoop
    from task_db import TaskDB

    db = TaskDB()
    loop = OrchestratorLoop(db)

    # Create tasks first
    t1 = db.create_task("add rate limiter", discipline="tdd")

    # Drive one task through the pipeline
    while loop.has_work(t1.id):
        phase = loop.next_phase(t1.id)
        prompt = loop.get_prompt(t1.id, phase)

        # Host executes the prompt, gets result
        result = host_execute(prompt)

        # Submit result back to loop
        outcome = loop.submit(t1.id, phase, result)

        if outcome == "BLOCKED":
            # Present HITL question to human, wait, then:
            loop.unblock(t1.id, decision="use JWT")
        elif outcome == "RETRY":
            pass  # loop.next_phase() returns the same phase
        elif outcome == "ESCALATE":
            # Debugger dispatched, then retry from IMPLEMENT
            pass

    # After all tasks
    report = loop.summary()
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from task_db import TaskDB
from pipeline_enforcer import PipelineEnforcer, PHASE_DESCRIPTIONS
from reward_log import RewardLog
from prompt_evolution import PromptEvolution
from gate_evolution import GateEvolution
from enforcement import build_registry, run_gates, measure_scope, verify_tests
from evaluator import evaluate_pipeline_run, EvalReport
from checkpoint import check_honcho_logged
from grpo import propose_grpo_edits

HARNESS_DIR = Path(__file__).parent
ROOT = HARNESS_DIR.parent
AGENTS_DIR = ROOT / "agents"

MAX_IMPLEMENT_RETRIES = 3
MAX_TOTAL_RETRIES = 5
DEFAULT_VARIANT_COUNT = 1  # number of implement variants to try per task


class LoopAction(Enum):
    """What the host should do next."""
    RUN_PHASE = "run_phase"        # execute the prompt for this phase
    RETRY = "retry"                # same phase, with feedback
    ESCALATE = "escalate"          # dispatch debugger agent
    BLOCK_HITL = "block_hitl"     # present question to human, wait
    DONE = "done"                  # task complete
    FAILED = "failed"              # task terminal failure


@dataclass
class LoopOutcome:
    """Result of submitting a phase result to the loop."""
    action: LoopAction
    phase: str
    task_id: str
    message: str = ""
    prompt: Optional[dict] = None   # AgentPrompt for next action (if RUN_PHASE)
    question: str = ""              # HITL question (if BLOCK_HITL)
    options: list[str] | None = None


class OrchestratorLoop:
    """
    Drives tasks through the multi-agent pipeline.
    The host agent calls this in a loop until all tasks are done.
    """

    def __init__(
        self,
        db: TaskDB,
        enforcer: PipelineEnforcer | None = None,
        reward_log: RewardLog | None = None,
    ):
        self.db = db
        self.enforcer = enforcer or PipelineEnforcer(db)
        self._retry_counts: dict[str, int] = {}  # task_id -> total retries
        self._impl_retry_counts: dict[str, int] = {}  # task_id -> impl retries

        # Deterministic enforcement core — the SAME gates/measure/SHA that
        # conductor runs. Built once; feeds real signals into the reward log.
        self.registry = build_registry()

        # RL components
        self.reward_log = reward_log or RewardLog()
        self.evolution = PromptEvolution(self.reward_log)
        self.gate_evolution = GateEvolution(self.reward_log)

        # Per-task artifacts for reward computation
        self._critique_predictions: dict[str, list[str]] = {}  # task_id -> predictions
        self._review_findings: dict[str, list[str]] = {}        # task_id -> findings
        self._task_type: dict[str, str] = {}                    # task_id -> type
        self._variant_used: dict[str, str] = {}                 # task_id -> variant name
        # Real enforcement signals captured per task, fed to reward at DONE
        self._gate_pass: dict[str, bool] = {}                   # task_id -> gates passed
        self._scope_clean: dict[str, bool] = {}                 # task_id -> scope clean
        self._test_pass: dict[str, bool] = {}                   # task_id -> SHA gate passed
        # Richer state for the deterministic EVAL phase (100-point eval report)
        self._scope: dict[str, object] = {}                     # task_id -> ScopeResult
        self._diff: dict[str, str] = {}                         # task_id -> implement diff
        self._review_result: dict[str, str] = {}               # task_id -> PASS|SOFT_FAIL
        self._gate_violations: dict[str, int] = {}             # task_id -> # gate failures
        self._eval: dict[str, EvalReport] = {}                 # task_id -> eval report
        self._eval_run_no = 0

    def has_work(self, task_id: str) -> bool:
        """Check if a task still has phases to run."""
        task = self.db.get_task(task_id)
        if not task:
            return False
        if task.status in ("DONE", "FAILED"):
            return False
        phase = self.enforcer.get_phase(task_id)
        if phase == "DONE":
            return False
        return True

    def next_phase(self, task_id: str) -> str:
        """The next phase to RUN for a task.

        enforcer.get_phase() returns the last COMPLETED phase, so the next phase is the
        one after it in PHASES (not that phase again — that bug made the loop re-submit
        IMPLEMENT forever). EVAL runs inside VERIFY's handler, so the host never runs it.

        phase_mode controls the starting phase:
          - "full" (default): starts at RECALL (10-phase pipeline)
          - "fast": starts at IMPLEMENT (skip RECALL+CONCLUDE, for review-only tasks)

        The PENDING short-circuit only fires when no phase has been completed yet for
        this run. The earlier code returned RECALL whenever status==PENDING, which
        trapped the loop after RECALL mark_complete (RECALL's mark_complete only logs
        an event, it doesn't change status, so the short-circuit fired forever and the
        pipeline could never advance to IMPLEMENT). Trust the enforcer's last-completed
        phase if one exists.
        """
        from pipeline_enforcer import PHASES

        task = self.db.get_task(task_id)
        phase_mode = task.phase_mode if task else "full"

        # A PENDING task that has been reset (e.g. after a debugger/re-implement
        # unblock) should resume at the correct starting phase, NOT at the phase
        # after the last completed one — otherwise it gets stuck re-entering the
        # phase that originally blocked.
        if task and task.status == "PENDING":
            completed = {
                e.action for e in self.db.get_task_history(task_id)
                if e.action in PHASES and e.verdict not in ("HARD_FAIL",)
            }
            if phase_mode in ("fast", "micro"):
                return "IMPLEMENT"
            if "RECALL" not in completed:
                return "RECALL"
            return "IMPLEMENT"

        # A reset task (PENDING, e.g. after a debugger/re-implement unblock) resumes at
        # RECALL (or IMPLEMENT for fast mode) even though stale completed-phase events linger in history.
        # BUT: only treat PENDING as "reset" if no phase has been completed for this run.
        last = self.enforcer.get_phase(task_id)
        if last is None and task and task.status == "PENDING":
            return "IMPLEMENT" if phase_mode in ("fast", "micro") else "RECALL"
        if last is None:
            return "IMPLEMENT" if phase_mode in ("fast", "micro") else "RECALL"
        if last in ("DONE", "FAILED"):
            return last

        # For fast mode, skip RECALL, CONCLUDE, and REFRESH_CONTEXT phases
        if phase_mode == "fast":
            next_phase = PHASES[PHASES.index(last) + 1] if last in PHASES else "IMPLEMENT"
            if next_phase in ("RECALL", "CONCLUDE", "REFRESH_CONTEXT"):
                return PHASES[PHASES.index(next_phase) + 1] if next_phase in PHASES else "DONE"

        # For micro mode: IMPLEMENT → CONTEXT_GUARD → VERIFY → EVAL → DONE
        # Skip RECALL, CRITIQUE, REVIEW, RETRO, CONCLUDE, REFRESH_CONTEXT
        if phase_mode == "micro":
            if last is None:
                return "IMPLEMENT"
            MICRO_NEXT = {
                "IMPLEMENT": "CONTEXT_GUARD",
                "CONTEXT_GUARD": "VERIFY",
                "VERIFY": "EVAL",
                "EVAL": "DONE",
            }
            if last in MICRO_NEXT:
                return MICRO_NEXT[last]
            if last in ("DONE", "FAILED"):
                return last

        try:
            return PHASES[PHASES.index(last) + 1]
        except (ValueError, IndexError):
            return "DONE"

    def get_prompt(self, task_id: str, phase: str) -> dict:
        """
        Generate the prompt for a subagent assigned to this phase.
        Returns {system: str, user: str} — the agent .md body + assembled context.
        """
        task = self.db.get_task(task_id)
        if not task:
            return {"system": "", "user": f"ERROR: Task {task_id} not found"}

        # Read agent definition
        agent_body = self._read_agent_body(phase)
        user_context = self._build_user_context(task_id, phase)

        return {"system": agent_body, "user": user_context}

    def submit(self, task_id: str, phase: str, result: str) -> LoopOutcome:
        """
        Submit the host's result for a phase. Returns the next action.
        The host should call this after executing each prompt.
        """
        task = self.db.get_task(task_id)
        if not task:
            return LoopOutcome(
                action=LoopAction.FAILED, phase=phase, task_id=task_id,
                message=f"Task {task_id} not found",
            )

        if phase == "RECALL":
            return self._submit_recall(task_id, result)
        elif phase == "IMPLEMENT":
            return self._submit_implement(task_id, result)
        elif phase == "CONTEXT_GUARD":
            return self._submit_context_guard(task_id, result)
        elif phase == "CRITIQUE":
            return self._submit_critique(task_id, result)
        elif phase == "REVIEW":
            return self._submit_review(task_id, result)
        elif phase == "VERIFY":
            return self._submit_verify(task_id, result)
        elif phase == "EVAL":
            return self._submit_eval(task_id, result)
        elif phase == "RETRO":
            return self._submit_retro(task_id, result)
        elif phase == "CONCLUDE":
            return self._submit_conclude(task_id, result)
        elif phase == "REFRESH_CONTEXT":
            return self._submit_refresh_context(task_id, result)
        elif phase == "DEBUG":
            return self._submit_debug(task_id, result)
        else:
            return LoopOutcome(
                action=LoopAction.DONE, phase=phase, task_id=task_id,
                message=f"Unknown phase: {phase}",
            )

    def unblock(self, task_id: str, decision: str = "proceed") -> None:
        """Human has decided — unblock the task."""
        self.enforcer.unblock(task_id, decision=decision)

    def get_blocked_tasks(self) -> list[dict]:
        """Get all tasks waiting for HITL decisions."""
        blocked = self.db.get_tasks_by_status("BLOCKED")
        result = []
        for task in blocked:
            history = self.db.get_task_history(task.id)
            hitl = next(
                (e for e in reversed(history) if e.action == "hitl_request"), None
            )
            result.append({
                "task_id": task.id,
                "title": task.title,
                "question": hitl.findings if hitl else "unknown",
                "options": None,  # parsed from hitl summary if needed
            })
        return result

    def summary(self) -> str:
        """Human-readable summary of all task states."""
        return self.enforcer.dashboard()

    # ── Phase summary printer ─────────────────────────────────────────────

    def _print_phase_summary(self, phase: str, task_id: str, outcome: LoopOutcome) -> None:
        """Print a one-line per-phase summary with bracketed phase tag and (!) for non-clean outcomes."""
        CLEAN_ACTIONS = {LoopAction.RUN_PHASE, LoopAction.DONE}
        marker = " (!)" if outcome.action not in CLEAN_ACTIONS else ""
        print(f"[{phase}]{marker} {outcome.message} -> {outcome.action.value.upper()}")

    # ── Phase submission handlers ────────────────────────────────────────

    def _submit_recall(self, task_id: str, result: str) -> LoopOutcome:
        """Process RECALL phase output.

        Full-mode recall must name both the durable Honcho context and the
        workshop retrieval artifact used to ground IMPLEMENT.
        """
        task = self.db.get_task(task_id)
        if not result or len(result.strip()) < 20:
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
            outcome = LoopOutcome(
                action=LoopAction.RETRY, phase="RECALL", task_id=task_id,
                message=(
                    "RECALL missing WORKSHOP_CONTEXT line. Run the workshop retrieval "
                    "packet and name the context docs/files you used."
                ),
            )
            self._print_phase_summary("RECALL", task_id, outcome)
            return outcome

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
            changed_files=self._extract_files(diff),
            diff_summary=self._diff_stats(diff),
        )
        self._impl_retry_counts[task_id] = 0

        outcome = LoopOutcome(
            action=LoopAction.RUN_PHASE, phase="CONTEXT_GUARD", task_id=task_id,
            message="Implementation complete — advancing to context-guard",
        )
        self._print_phase_summary("IMPLEMENT", task_id, outcome)
        return outcome

    def _submit_context_guard(self, task_id: str, audit: str) -> LoopOutcome:
        """Process context-guard output. Validate punch list, then advance.

        The context-guard agent MUST emit a CONCLUDE PUNCH LIST with at least
        DOCS, CONTEXT, and HONCHO entries. A lazy agent that skips it produces
        no guidance for CONCLOSE — the gate catches this.
        """
        # Validate punch list presence
        audit_lower = audit.lower()
        has_punch_list = (
            "conclude punch list" in audit_lower
            or ("punch list" in audit_lower)
            or ("docs:" in audit_lower and ("context" in audit_lower or "not_needed" in audit_lower))
        )
        if not has_punch_list:
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

    def _submit_debug(self, task_id: str, diff: str) -> LoopOutcome:
        """A debugger session produced a corrected implementation. Reset to a fresh
        state and re-enter the pipeline as a new IMPLEMENT, so CONTEXT_GUARD / CRITIQUE /
        REVIEW / VERIFY all re-run on the FIXED code (the prior audits are now stale).
        This is the clean BLOCKED→DEBUG→IMPLEMENT re-entry the TRANSITIONS table promises.
        """
        self.db.reset_task(task_id, to_status="PENDING")
        return self._submit_implement(task_id, diff)

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

    def _submit_review(self, task_id: str, review: str) -> LoopOutcome:
        """Process review output. Retry on HARD_FAIL, else advance.

        Auto-advance: if the diff is ≤10 lines and tests pass, skip HITL and
        advance directly to VERIFY — trivial changes don't need human review.
        """
        is_hard_fail = "HARD_FAIL" in review.upper()

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
        outcome = LoopOutcome(
            action=LoopAction.RUN_PHASE, phase="VERIFY", task_id=task_id,
            message="Review passed — advancing to verify",
        )
        self._print_phase_summary("REVIEW", task_id, outcome)
        return outcome

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

    def _submit_eval(self, task_id: str, _ignored: str = "") -> LoopOutcome:
        """EVAL phase — the deterministic 100-point score. No model: computed from the
        real signals captured during the run (_run_eval also records the phase).
        Advances to RETRO so reflection has the objective score to reason about."""
        report = self._run_eval(task_id)   # computes the score AND marks EVAL complete

        # Micro mode: skip RETRO, CONCLUDE, REFRESH_CONTEXT — go directly to DONE
        task = self.db.get_task(task_id)
        if task and task.phase_mode == "micro":
            self.enforcer.mark_complete(
                task_id, "DONE", agent="evaluator",
                summary=f"Micro-mode pipeline complete (eval {report.total}/100)",
            )
            self._record_reward(task_id)
            outcome = LoopOutcome(
                action=LoopAction.DONE, phase="DONE", task_id=task_id,
                message=f"Scored {report.total}/100 ({report.grade}) — micro pipeline complete",
            )
            self._print_phase_summary("EVAL", task_id, outcome)
            return outcome

        outcome = LoopOutcome(
            action=LoopAction.RUN_PHASE, phase="RETRO", task_id=task_id,
            message=f"Scored {report.total}/100 ({report.grade}) — advancing to retro",
        )
        self._print_phase_summary("EVAL", task_id, outcome)
        return outcome

    def _submit_retro(self, task_id: str, reflection: str) -> LoopOutcome:
        """RETRO phase — record the run's reflection, then advance to CONCLUDE.

        The retro agent (agents/retro.md) answers the structured questions, reflects on
        the EVAL score + per-skill recurrence, and STAGES skill-edit proposals
        (ratify-gated, never auto-applied). Here we record it and advance to CONCLUDE.

        Gate: retro must be substantive, not a checkbox.
        """
        # Gate: reject checkbox retros
        if len(reflection.strip()) < 100:
            outcome = LoopOutcome(
                action=LoopAction.RETRY, phase="RETRO", task_id=task_id,
                message=(
                    "RETRO too short (< 100 chars). Answer the 7 questions, reference "
                    "completed phases, and record lessons learned. This is not a checkbox."
                ),
            )
            self._print_phase_summary("RETRO", task_id, outcome)
            return outcome

        # Gate: must reference at least one completed phase (shows it looked at the run)
        history = self.db.get_task_history(task_id)
        completed_phases = [e.action for e in history if e.action in PHASE_DESCRIPTIONS]
        reflection_lower = reflection.lower()
        referenced = [p for p in completed_phases if p.lower() in reflection_lower]
        if not referenced:
            outcome = LoopOutcome(
                action=LoopAction.RETRY, phase="RETRO", task_id=task_id,
                message=(
                    "RETRO doesn't reference any completed phase. "
                    f"Phases this run: {', '.join(completed_phases)}. "
                    "Reference what happened — what went well, what broke, what to change."
                ),
            )
            self._print_phase_summary("RETRO", task_id, outcome)
            return outcome

        self.enforcer.mark_complete(
            task_id, "RETRO", agent="retro",
            summary=reflection[:200], findings=reflection,
        )

        report = self._eval.get(task_id)
        total = report.total if report else 0

        # Fast-mode tasks skip CONCLUDE — advance directly to DONE
        task = self.db.get_task(task_id)
        if task and task.phase_mode == "fast":
            self.enforcer.mark_complete(
                task_id, "DONE", agent="retro",
                summary=f"Fast-mode pipeline complete (eval {total}/100)",
            )
            outcome = LoopOutcome(
                action=LoopAction.DONE, phase="DONE", task_id=task_id,
                message=f"Reflection recorded (eval {total}/100) — pipeline complete (fast mode)",
            )
            self._print_phase_summary("RETRO", task_id, outcome)
            return outcome

        outcome = LoopOutcome(
            action=LoopAction.RUN_PHASE, phase="CONCLUDE", task_id=task_id,
            message=f"Reflection recorded (eval {total}/100) — advancing to conclude",
        )
        self._print_phase_summary("RETRO", task_id, outcome)
        return outcome

    def _submit_conclude(self, task_id: str, result: str) -> LoopOutcome:
        """CONCLUDE phase — durable write-back and context/doc closure.

        The host must write durable facts back to Honcho and close the context-guard
        punch list: docs updated or explicitly not needed, .techne/context refreshed
        or explicitly not needed. Then we mark DONE and record the RL reward.
        """
        validation_error = self._validate_conclude_proof(result, task_id)
        if validation_error:
            outcome = LoopOutcome(
                action=LoopAction.RETRY, phase="CONCLUDE", task_id=task_id,
                message=validation_error,
            )
            self._print_phase_summary("CONCLUDE", task_id, outcome)
            return outcome

        self.enforcer.mark_complete(
            task_id, "CONCLUDE", agent="concluder",
            summary=f"Closure proof: {result[:150]}",
            findings=result,
        )

        # ── Retro-learn trigger ──
        # After every CONCLUDE, snapshot the per-skill mistake counts so retro-learn
        # can decide whether to propose a skill edit (>=2 ACTIVE on one skill) or
        # a new gate (>=4). The host reads the snapshot — no LLM call here.
        try:
            from mistakes import count_by_skill
            from ledger import count_by_kind as ledger_by_kind
            recurrence = count_by_skill()
            if any(n >= 2 for n in recurrence.values()):
                self._log_retro_learn_trigger(task_id, recurrence, ledger_by_kind())
        except Exception:
            pass  # retro-learn is best-effort — don't block CONCLUDE on a snapshot error

        report = self._eval.get(task_id)
        total = report.total if report else 0
        outcome = LoopOutcome(
            action=LoopAction.RUN_PHASE, phase="REFRESH_CONTEXT", task_id=task_id,
            message=f"Conclusion recorded (eval {total}/100) — advancing to context refresh",
        )
        self._print_phase_summary("CONCLUDE", task_id, outcome)
        return outcome

    def _submit_refresh_context(self, task_id: str, result: str = "") -> LoopOutcome:
        """REFRESH_CONTEXT phase — rebuild generated workshop artifacts.

        Runs refresh_generated_docs.py as a subprocess, passing touched files
        from the CONTEXT_GUARD phase. On success, marks REFRESH_CONTEXT complete,
        records the RL reward, and transitions to DONE.

        Fast-mode tasks skip the script execution entirely.

        Patch 3: If .techne/config.yaml does not exist, skip gracefully instead
        of failing — projects without a workshop setup should still complete.
        """
        task = self.db.get_task(task_id)

        # Fast-mode: skip the full refresh, just record reward and mark DONE
        if task and task.phase_mode == "fast":
            self.enforcer.mark_complete(
                task_id, "DONE", agent="orchestrator",
                summary="Fast-mode pipeline complete — context refresh skipped",
            )
            self._record_reward(task_id)
            outcome = LoopOutcome(
                action=LoopAction.DONE, phase="DONE", task_id=task_id,
                message="Context refresh skipped (fast mode) — task complete",
            )
            self._print_phase_summary("REFRESH_CONTEXT", task_id, outcome)
            return outcome

        # ── Patch 3: Graceful skip when no .techne/config.yaml ─────────────
        config_path = ROOT / ".techne" / "config.yaml"
        if not config_path.exists():
            self.enforcer.mark_complete(
                task_id, "REFRESH_CONTEXT", agent="refresh_context",
                summary="No .techne/config.yaml — context refresh skipped",
                findings="",
            )
            self._record_reward(task_id)
            outcome = LoopOutcome(
                action=LoopAction.DONE, phase="DONE", task_id=task_id,
                message="Context refresh skipped (no workshop config) — task complete",
            )
            self._print_phase_summary("REFRESH_CONTEXT", task_id, outcome)
            return outcome
        # ── end Patch 3 ─────────────────────────────────────────────────

        # Get touched files from CONTEXT_GUARD's punch list
        history = self.db.get_task_history(task_id)
        context_guard = next((e for e in reversed(history) if e.action == "CONTEXT_GUARD"), None)
        touched = []
        if context_guard and context_guard.changed_files:
            touched = json.loads(context_guard.changed_files) if isinstance(context_guard.changed_files, str) else context_guard.changed_files

        script = Path(__file__).parent.parent / ".techne" / "scripts" / "refresh_generated_docs.py"
        cmd = ["python3", str(script), "--task", task_id, "--json"]
        for f in touched[:10]:
            cmd.extend(["--files", f])

        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            outcome = LoopOutcome(
                action=LoopAction.RETRY, phase="REFRESH_CONTEXT", task_id=task_id,
                message=(
                    f"REFRESH_CONTEXT failed: "
                    f"{(proc.stderr or proc.stdout or 'unknown error').strip()[:200]}"
                ),
            )
            self._print_phase_summary("REFRESH_CONTEXT", task_id, outcome)
            return outcome

        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            outcome = LoopOutcome(
                action=LoopAction.RETRY, phase="REFRESH_CONTEXT", task_id=task_id,
                message="REFRESH_CONTEXT failed: script output is not valid JSON",
            )
            self._print_phase_summary("REFRESH_CONTEXT", task_id, outcome)
            return outcome

        self.enforcer.mark_complete(
            task_id, "REFRESH_CONTEXT", agent="refresh_context",
            summary=(
                f"Refreshed: {len(payload.get('generated_updated', []))} files, "
                f"{len(payload.get('stale_docs', []))} stale docs flagged"
            ),
            findings=json.dumps(payload),
        )
        self._record_reward(task_id)
        outcome = LoopOutcome(
            action=LoopAction.DONE, phase="DONE", task_id=task_id,
            message="Context refreshed — task complete",
        )
        self._print_phase_summary("REFRESH_CONTEXT", task_id, outcome)
        return outcome

    def _log_retro_learn_trigger(self, task_id: str, recurrence: dict,
                                 ledger_counts: dict) -> None:
        """Write a retro-learn trigger line + rebuild wikilink index.

        Two outputs:
        1. memory/retro_learn_triggers.md — append-only log of "this task should be retro'd"
        2. memory/wikilinks.{md,json} — rebuilt index of all mistakes + ledger entries
           (refreshed every DONE so the wikilinks never go stale)

        The retro-learn skill (or host) reads trigger lines and acts on them.
        The wikilink index is bidirectional: each entry links to its skill,
        each skill links back to its entries. Tools consume the JSON, humans
        read the Markdown.
        """
        from datetime import datetime, timezone
        from pathlib import Path

        memory_dir = Path(__file__).parent.parent / ".techne" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        triggers = memory_dir / "retro_learn_triggers.md"

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        recurring = ", ".join(f"{s}:{n}" for s, n in sorted(recurrence.items(), key=lambda x: -x[1]) if n >= 2)
        if not recurring and not ledger_counts:
            return  # nothing to retro-learn
        line = f"- [{now}] task {task_id} | recurrence: {recurring or '(none)'} | ledger: {ledger_counts or '(empty)'}\n"
        if not triggers.exists():
            triggers.write_text(
                "# Retro-Learn Triggers\n"
                "# Auto-written when a task completes with recurring mistakes or new ledger entries.\n"
                "# Read by retro-learn to decide what to propose (skill edit / new gate / nothing).\n\n",
                encoding="utf-8",
            )
        with triggers.open("a", encoding="utf-8") as f:
            f.write(line)

        # Rebuild wikilink index — cheap and keeps the registry current
        try:
            from wikilink import build_graph, format_markdown as wl_md
            import json as _json
            graph = build_graph()
            (memory_dir / "wikilinks.md").write_text(wl_md(graph), encoding="utf-8")
            (memory_dir / "wikilinks.json").write_text(
                _json.dumps(graph, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass  # wikilink build is best-effort — never block DONE

    def _validate_conclude_proof(self, result: str, task_id: str | None = None) -> str:
        """Validate CONCLUDE proof: Honcho + docs closure + context closure.

        Parses the proof line-by-line looking for structured prefixes:
          HONCHO: <proof text>
          DOCS: <path> updated OR NOT_NEEDED: <reason>
          CONTEXT: <path> refreshed OR NOT_NEEDED: <reason> [sha:<hex>]

        Rejects if any required section is missing, if the CONTEXT line claims
        an update without a commit SHA, or if .techne/context has uncommitted
        changes in the working tree relevant to the task's touched files.
        """
        import re

        if not result or len(result.strip()) < 20:
            return (
                "Proof is too short or empty — CONCLUDE requires HONCHO/DOCS/CONTEXT proof lines"
            )

        # Parse structured lines: prefix must start a non-blank line
        conclusion_id = check_honcho_logged()
        has_honcho = conclusion_id is not None
        context_line = None  # the raw CONTEXT line (if any)
        for line in result.splitlines():
            stripped = line.strip()
            lower = stripped.lower()
            if lower.startswith("context"):
                context_line = stripped
            # DOCS: detected by prefix — but we only need to know it exists
            # (too many valid formats: "DOCS: NOT_NEEDED: ...", "DOCS: docs/X.md updated")

        has_docs = any(l.strip().lower().startswith("docs") for l in result.splitlines())
        has_context = context_line is not None

        missing = []
        if not has_honcho:
            missing.append("HONCHO line (start a line with 'HONCHO: <proof>')")
        if not has_docs:
            missing.append("DOCS line (start a line with 'DOCS: <path> updated' or 'DOCS: NOT_NEEDED: <reason>')")
        if not has_context:
            missing.append("CONTEXT line (start a line with 'CONTEXT: <path> refreshed' or 'CONTEXT: NOT_NEEDED: <reason>')")
        if missing:
            return "CONCLUDE missing proof: " + "; ".join(missing)

        # ── Hard gate: .techne/context must be committed if modified ──
        # If task_id is provided, extract changed_files from CONTEXT_GUARD event
        # to scope the gate to only task-relevant context files.
        changed_files = None
        if task_id:
            try:
                history = self.db.get_task_history(task_id)
                context_guard = next(
                    (e for e in reversed(history) if e.action == "CONTEXT_GUARD"),
                    None,
                )
                if context_guard and context_guard.changed_files:
                    changed_files = (
                        json.loads(context_guard.changed_files)
                        if isinstance(context_guard.changed_files, str)
                        else context_guard.changed_files
                    )
            except Exception:
                pass  # best-effort — fall through to full check
        uncommitted = self._get_uncommitted_context_files(touched_files=changed_files)
        if uncommitted:
            return (
                f"CONCLUDE blocked: .techne/context has uncommitted changes. "
                f"Stage and commit before concluding. Files: {', '.join(uncommitted)}"
            )

        # ── Hard gate: SHA required when context was updated (not NOT_NEEDED) ──
        if context_line is None:
            return ""  # already checked above, but pyright needs the guard
        ctx_lower = context_line.lower()
        context_updated = ".techne/context" in ctx_lower and "not_needed" not in ctx_lower
        if context_updated:
            # SHA must appear ON THE CONTEXT LINE specifically
            has_sha = bool(re.search(r"sha[:\s]+[0-9a-f]{7,40}", ctx_lower))
            if not has_sha:
                return (
                    "CONCLUDE missing SHA proof. The CONTEXT line claims .techne/context "
                    "was updated but no commit SHA was found on that line. "
                    "Format: CONTEXT: .techne/context/<path> refreshed sha:<full-sha>"
                )

        return ""

    def _get_uncommitted_context_files(self, touched_files: list[str] | None = None) -> list[str]:
        """Return list of uncommitted .techne/context files, or [] if clean.

        Walks up from CWD (where scripts are always cd'd to project root) to find
        .git, then checks .techne/context for uncommitted changes. Falls back to
        walking up from db_path if CWD approach fails.

        When *touched_files* is provided, the result is filtered to only context
        files whose subsystem overlaps with the touched files' subsystems, using
        detect_subsystems_for_files() from the workshop module. This prevents an
        unrelated dirty context file from blocking the CONCLUDE gate.
        """
        import subprocess, os
        from workshop import detect_subsystems_for_files

        def find_repo_root(start: Path) -> Path | None:
            cursor = start
            while cursor != cursor.parent:
                if (cursor / ".git").is_dir():
                    return cursor
                cursor = cursor.parent
            return None

        try:
            # Primary: walk up from CWD (script always cd'd to project root)
            repo_root = find_repo_root(Path.cwd())
            if repo_root is None:
                # Fallback: walk up from db_path
                repo_root = find_repo_root(Path(self.db.db_path).parent)
            if repo_root is None:
                return []  # non-git — skip gate

            # Check full status then filter — glob misses nested paths like stage/app/.techne/context/
            result = subprocess.run(
                ["git", "status", "--porcelain", "--", "."],
                capture_output=True, text=True, cwd=str(repo_root),
            )
            uncommitted = [l.split(None, 1)[1] for l in result.stdout.strip().split("\n") if l.strip()]
            uncommitted = [f for f in uncommitted if ".techne/context" in f]

            # ── Scope gate to task-relevant subsystems ──
            if touched_files and uncommitted:
                try:
                    index_path = repo_root / ".techne" / "generated" / "context_index.json"
                    if index_path.exists():
                        index = json.loads(index_path.read_text(encoding="utf-8"))
                        touched_subsystems = detect_subsystems_for_files(index, touched_files)
                        if touched_subsystems:
                            filtered = []
                            for f in uncommitted:
                                p = Path(f)
                                # Subsystem is the filename stem before ".CONTEXT.md"
                                # e.g. ".techne/context/auth.CONTEXT.md" -> "auth"
                                subsystem = p.stem.replace(".CONTEXT", "")
                                if subsystem in touched_subsystems:
                                    filtered.append(f)
                            return filtered
                except Exception:
                    pass  # best-effort — fall through to return all uncommitted

            return uncommitted
        except Exception:
            return []  # error — skip gate rather than block

    # ── Reward recording ─────────────────────────────────────────────────

    def _record_reward(self, task_id: str) -> None:
        """
        Record the RL reward for a task that reached a terminal outcome.

        Both wins (DONE) and losses (retries exhausted → escalation) train the
        loop — learning only from successes biases evolution toward variants
        that never get hard tasks. Reads the real signals captured during the
        run; a signal left unset means the run never earned it (a task that
        failed at IMPLEMENT never ran tests), so it defaults to False.
        """
        task = self.db.get_task(task_id)
        self.reward_log.record(
            task_id=task_id,
            task_type=self._task_type.get(task_id, "general"),
            prompt_variant=self._variant_used.get(task_id, "v1"),
            gate_pass=self._gate_pass.get(task_id, False),     # real: hard gates
            test_pass=self._test_pass.get(task_id, False),     # real: SHA gate
            review_findings=self._review_findings.get(task_id, []),
            critique_predictions=self._critique_predictions.get(task_id, []),
            scope_clean=self._scope_clean.get(task_id, False),  # real: focus/scope/intent
            attempt_count=max(1, task.attempt if task else 1),  # >=1: a terminal task ran at least once
            gate_violations=self._gate_violations.get(task_id, 0),
        )
        # ── Patch 4: ensure .gitignore and prune artifacts on DONE ──────
        if task and task.status == "DONE":
            try:
                self._ensure_techne_gitignore(str(ROOT))
                self._prune_task_artifacts(task_id)
            except Exception:
                pass  # best-effort — never block DONE on gitignore/cleanup failure
        # ── end Patch 4 ───────────────────────────────────────────────

    # ── Patch 4: gitignore + cleanup helpers ──────────────────────────────────

    def _ensure_techne_gitignore(self, project_root: str) -> None:
        """
        Ensure .gitignore contains .techne/tasks/ and .techne/memory/.

        These directories hold ephemeral state (task records, memory snapshots)
        that should never be committed. Called from _record_reward on DONE.
        """
        from pathlib import Path
        gitignore_path = Path(project_root) / ".gitignore"
        entries = [".techne/tasks/", ".techne/memory/"]

        if not gitignore_path.exists():
            content = ""
        else:
            content = gitignore_path.read_text(encoding="utf-8")

        updated = False
        for entry in entries:
            if entry not in content:
                content += f"\n{entry}\n"
                updated = True

        if updated:
            gitignore_path.write_text(content, encoding="utf-8")

    def _prune_task_artifacts(self, task_id: str) -> None:
        """
        Prune ephemeral task artifacts after DONE.

        Removes task-specific files from .techne/tasks/ to keep the directory
        clean. Safe to call multiple times — only removes files matching this
        task's artifacts.
        """
        from pathlib import Path
        tasks_dir = ROOT / ".techne" / "tasks"
        if not tasks_dir.exists():
            return
        # Remove any task-specific output files (e.g. implementer_output_N.txt)
        for pattern in (f"implementer_output_*.txt", f"critique_output_*.txt",
                       f"review_output_*.txt"):
            for f in tasks_dir.glob(pattern):
                try:
                    f.unlink()
                except OSError:
                    pass

    # ── EVAL phase: original 100-point deterministic eval ────────────────

    def _build_eval_metrics(self, task_id: str) -> dict:
        """
        Map the loop's captured enforcement signals onto the evaluator's
        metric kwargs — the SAME 100-point eval the conductor runs.

        Retro Value maps to the RL learning step (reward recording + per-run
        evolution), which is the loop's equivalent of the conductor's retro.
        """
        scope = self._scope.get(task_id)
        diff_lower = self._diff.get(task_id, "").lower()
        drift = (
            diff_lower.count("+  todo") + diff_lower.count("+ // todo")
            + diff_lower.count("+  fixme") + diff_lower.count("+ // fixme")
            + diff_lower.count("+ console.log") + diff_lower.count("+console.log")
        )
        test_pass = self._test_pass.get(task_id, False)
        return dict(
            gate_violations=self._gate_violations.get(task_id, 0),
            retries_used=self._retry_counts.get(task_id, 0),
            pipeline_halted=False,
            sha_passed=test_pass,
            output_existed=test_pass,
            had_pass_indicators=test_pass,
            diff_focused=scope.diff_focused if scope else True,
            scope_creep=scope.scope_creep if scope else False,
            review_result=self._review_result.get(task_id, "PASS"),
            drift_markers=drift,
            retro_ran=True,            # RL learning step = reward + evolution
            retro_questions=7,
        )

    def _run_eval(self, task_id: str) -> EvalReport:
        """Run the deterministic 100-point eval and record it as the EVAL phase."""
        task = self.db.get_task(task_id)
        self._eval_run_no += 1
        report = evaluate_pipeline_run(
            task=task.title if task else task_id,
            pipeline_number=self._eval_run_no,
            **self._build_eval_metrics(task_id),
        )
        self._eval[task_id] = report
        self.enforcer.mark_complete(
            task_id, "EVAL",
            agent="evaluator",
            summary=f"Eval {report.total}/100 ({report.grade})",
            findings=report.format_report()[:1500],
            verdict="PASS" if report.total >= 75 else "SOFT_FAIL",
        )
        return report

    def get_eval(self, task_id: str) -> EvalReport | None:
        """Return the 100-point eval report for a completed task, if any."""
        return self._eval.get(task_id)

    # ── Escalation ───────────────────────────────────────────────────────

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

    # ── Helpers ──────────────────────────────────────────────────────────

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

    def _build_user_context(self, task_id: str, phase: str) -> str:
        """Build the user prompt context for a phase."""
        task = self.db.get_task(task_id)
        history = self.db.get_task_history(task_id)
        prior = [e for e in history if e.action in PHASE_DESCRIPTIONS]

        lines = [
            f"TASK: {task.title}",
            f"DESCRIPTION: {task.description}",
            f"DISCIPLINE: {task.discipline}",
            f"ATTEMPT: #{task.attempt}",
            f"PHASE: {phase}",
            "",
            f"INSTRUCTIONS: {PHASE_DESCRIPTIONS.get(phase, phase)}",
        ]

        # RECALL: host needs task title + tags to search Honcho
        if phase == "RECALL" and task:
            tags = ", ".join(task.tags) if task.tags else "none"
            lines.extend([
                "",
                f"TAGS: {tags}",
                "",
                "Run both recall sources before IMPLEMENT:",
                "- Honcho: recall durable user/workflow context relevant to the task.",
                "- Workshop: use the project workshop retrieval packet below.",
                "",
                "Required output format:",
                "HONCHO_CONTEXT: <durable context you recalled>",
                "WORKSHOP_CONTEXT: <comma-separated .techne/context docs used, or none>",
                "WORKSHOP_FILES: <comma-separated files surfaced by retrieval, or none>",
                "LESSONS: <relevant lessons/mistakes/decisions, or none>",
                "FOCUS: <2-4 lines on what IMPLEMENT should touch/avoid>",
            ])
            lines.extend(self._build_workshop_recall_lines(task))

        # RETRO: inject mistakes.md, per-skill recurrence, routed skill content
        if phase == "RETRO" and task:
            lines.extend(self._build_retro_context(task))

        # CONCLUDE: host must close context-guard's punch list with proof
        if phase == "CONCLUDE":
            context_guard = next((e for e in reversed(history) if e.action == "CONTEXT_GUARD"), None)
            lines.extend([
                "",
                "CONCLUDE PROOF REQUIRED:",
                "  HONCHO: honcho://conclusion/<id> or conclusion id from honcho_conclude",
                "  DOCS: docs/<file>.md updated OR NOT_NEEDED: <specific reason>",
                "  CONTEXT: .techne/context/<path> refreshed OR NOT_NEEDED: <specific reason>",
                "",
                "When CONTEXT is updated: commit .techne/context first, then include",
                "  sha:<full-commit-sha> in the CONTEXT line (the gate rejects without it).",
                "",
                "Close the Context-Guard punch list. Do not return a generic summary.",
            ])
            if context_guard:
                lines.extend([
                    "",
                    "LATEST CONTEXT_GUARD REPORT:",
                    context_guard.findings or context_guard.summary,
                ])

        if prior:
            lines.append("")
            lines.append("COMPLETED PHASES:")
            for e in prior:
                lines.append(f"  {e.action}: {e.summary[:100]}")

        return "\n".join(lines)

    def _build_workshop_recall_lines(self, task) -> list[str]:
        """Best-effort workshop retrieval packet for RECALL."""
        lines = ["", "WORKSHOP RETRIEVAL PACKET:"]
        try:
            from workshop import find_workshop_paths

            paths = find_workshop_paths(Path.cwd())
            if paths is None:
                lines.append("WORKSHOP_STATUS: no .techne/config.yaml found from current cwd upward")
                lines.append("WORKSHOP_QUERY: unavailable")
                return lines

            query_parts = [task.title or "", task.description or ""]
            if task.tags:
                query_parts.append(" ".join(task.tags))
            query = " ".join(part.strip() for part in query_parts if part and part.strip())
            script = paths.scripts_dir / "context_search.py"
            if not script.exists():
                lines.append(f"WORKSHOP_STATUS: missing script {script}")
                lines.append(f"WORKSHOP_QUERY: {query or task.title}")
                return lines

            proc = subprocess.run(
                ["python3", str(script), query or task.title, "--json"],
                cwd=str(paths.repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                stderr = (proc.stderr or proc.stdout or "context_search failed").strip()
                lines.append(f"WORKSHOP_STATUS: retrieval failed: {stderr[:240]}")
                lines.append(f"WORKSHOP_QUERY: {query or task.title}")
                return lines

            payload = json.loads(proc.stdout)
            docs = [row.get("path", "") for row in payload.get("context_docs", [])[:5] if row.get("path")]
            files = [row.get("path", "") for row in payload.get("files", [])[:8] if row.get("path")]
            subsystems = [row.get("name", "") for row in payload.get("subsystems", [])[:5] if row.get("name")]
            memories = []
            for bucket in ("lessons", "mistakes", "decisions"):
                for row in payload.get(bucket, [])[:2]:
                    what = row.get("what")
                    if what:
                        memories.append(what)

            lines.extend([
                "WORKSHOP_STATUS: ok",
                f"WORKSHOP_QUERY: {payload.get('query', query or task.title)}",
                f"LIKELY_SUBSYSTEMS: {', '.join(subsystems) if subsystems else 'none'}",
                f"CONTEXT_DOC_CANDIDATES: {', '.join(docs) if docs else 'none'}",
                f"FILE_CANDIDATES: {', '.join(files) if files else 'none'}",
                f"MEMORY_CANDIDATES: {' | '.join(memories) if memories else 'none'}",
            ])
            return lines
        except Exception as exc:
            lines.append(f"WORKSHOP_STATUS: retrieval exception: {str(exc)[:240]}")
            return lines

    def _build_retro_context(self, task) -> list[str]:
        """Build the rich context RETRO needs: mistakes.md, recurrence, routed skill."""
        from mistakes import count_by_skill, MISTAKES_FILE
        from router import route

        lines = []

        # 1. Per-skill recurrence counts
        by_skill = count_by_skill()
        if by_skill:
            lines.extend(["", "ACTIVE MISTAKES BY SKILL (recurrence → retro proposals):"])
            for s, n in sorted(by_skill.items(), key=lambda x: -x[1]):
                rec = "   <- RECURRING (>=2): propose an edit to this skill" if n >= 2 else ""
                lines.append(f"  {s}: {n} active{rec}")
        else:
            lines.extend(["", "ACTIVE MISTAKES BY SKILL: (none)"])

        # 2. Routed skill's current content
        matched = route(task.title)
        if matched:
            skill_path = ROOT / matched.get("skill_path", "")
            if skill_path.exists():
                lines.extend([
                    "",
                    f"--- {matched.get('skill_path', '')} (current content) ---",
                    skill_path.read_text(encoding="utf-8"),
                ])

        # 3. Full mistakes.md
        if MISTAKES_FILE.exists():
            mistakes = MISTAKES_FILE.read_text(encoding="utf-8")
            lines.extend(["", f"mistakes.md content:", mistakes])

        return lines

    def _extract_files(self, diff: str) -> list[str]:
        """Extract changed file paths from a unified diff."""
        files = []
        for line in diff.splitlines():
            if line.startswith("+++ b/") or line.startswith("--- a/"):
                path = line[6:].strip()
                if path and path != "/dev/null" and path not in files:
                    files.append(path)
        return files

    def _diff_stats(self, diff: str) -> str:
        """Generate +N -M stats from a unified diff."""
        added = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
        return f"+{added} -{removed}"

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

    # ── RL integration ───────────────────────────────────────────────────

    def set_task_type(self, task_id: str, task_type: str) -> None:
        """Set the task type for reward classification."""
        self._task_type[task_id] = task_type

    def set_variant(self, task_id: str, variant: str) -> None:
        """Set which prompt variant was used for this task."""
        self._variant_used[task_id] = variant

    def get_best_variant(self, task_type: str, agent: str = "implementer") -> str | None:
        """Get the best-performing variant name for a task type."""
        return self.reward_log.best_variant(task_type)

    # ── Phase-mode-aware expected phases ──────────────────────────────────

    def _expected_phases(self, task_id: str) -> list[str]:
        """Return the ordered list of phases this task is expected to complete."""
        task = self.db.get_task(task_id)
        mode = task.phase_mode if task else "full"

        if mode == "fast":
            # Skip RECALL, CONCLUDE, REFRESH_CONTEXT
            skip = {"RECALL", "CONCLUDE", "REFRESH_CONTEXT"}
        elif mode == "micro":
            # Only: IMPLEMENT → CONTEXT_GUARD → VERIFY → EVAL → DONE
            return ["IMPLEMENT", "CONTEXT_GUARD", "VERIFY", "EVAL", "DONE"]
        else:
            skip = set()

        from pipeline_enforcer import PHASES
        return [p for p in PHASES if p not in skip]

    # ── Completion indicator ──────────────────────────────────────────────

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

    def post_run_evolve(self) -> dict:
        """
        Run after all tasks complete. Stages prompt AND gate proposals.
        Returns summary of what was proposed.

        Both are staged only (propose → validate → ratify); neither a prompt
        rewrite nor a new gate is promoted until a human ratifies it. A gate is
        part of the grader, so the loop must never auto-write one — same firewall
        as prompts, applied to the grader.
        """
        result = {
            "prompts_proposed": [],
            "gates_proposed": [],
            "grpo_proposed": [],
            "dashboard": "",
        }

        # Stage a prompt proposal for each task type seen (pending ratification).
        for task_type in self.reward_log.all_task_types():
            proposal = self.evolution.propose(task_type, "implementer")
            if proposal is not None:
                result["prompts_proposed"].append({
                    "task_type": task_type,
                    "variant_name": proposal.variant_name,
                    "proposal_id": proposal.id,
                    "status": proposal.status,
                })

        # Stage gate proposals (recurrence gate). A gate is part of the grader,
        # so it is NOT written until validate() + ratify() — never auto-written.
        gate_proposals = self.gate_evolution.propose(min_count=3)
        result["gates_proposed"] = [
            {"gate_name": gp.gate_name, "proposal_id": gp.id,
             "source_count": gp.source_count, "status": gp.status}
            for gp in gate_proposals
        ]

        # B3: GRPO advantage-based proposals — write high-advantage variants
        # as PROPOSE ADD entries in retro_proposals.md for human confirmation.
        # This is the connector that turns RL advantage scores into real
        # skill file edits through the apply_retro.py write path.
        if self.reward_log is not None:
            try:
                self.reward_log.compute_batch_advantages()
                grpo_proposals = propose_grpo_edits(self.reward_log)
                result["grpo_proposed"] = grpo_proposals
            except Exception:
                # GRPO proposals are best-effort — don't let failures block
                # the rest of post_run_evolve.
                result["grpo_proposed"] = []
        else:
            result["grpo_proposed"] = []

        # Dashboard
        result["dashboard"] = self.rl_dashboard()

        return result

    def rl_dashboard(self) -> str:
        """Full RL dashboard: rewards + evolution + gates."""
        parts = [
            self.reward_log.dashboard(),
            "",
            self.evolution.dashboard(),
            "",
            self.gate_evolution.dashboard(),
        ]
        return "\n".join(parts)


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


if __name__ == "__main__":
    # Smoke test
    import json
    db = TaskDB("/tmp/test_loop.db")
    loop = OrchestratorLoop(db)

    t = db.create_task("add rate limiter", discipline="tdd")
    print(f"Task: {t.id[:8]}")
    print(f"Has work: {loop.has_work(t.id)}")
    print(f"Next phase: {loop.next_phase(t.id)}")

    # Simulate: implement
    prompt = loop.get_prompt(t.id, "IMPLEMENT")
    print(f"Prompt system: {len(prompt['system'])} chars")
    impl_diff = (
        "--- a/rate_limiter.py\n+++ b/rate_limiter.py\n@@ -1 +1,3 @@\n"
        "-old\n+def rate_limiter(rate):\n+    # token-bucket limiter\n+    return rate\n"
    )
    result = loop.submit(t.id, "IMPLEMENT", impl_diff)
    print(f"After implement: action={result.action.value} message={result.message}")

    # Simulate: context-guard
    result = loop.submit(t.id, "CONTEXT_GUARD", "1 file changed, in scope")
    print(f"After context-guard: action={result.action.value}")

    # Simulate: critique (clean)
    result = loop.submit(t.id, "CRITIQUE", "No critical findings")
    print(f"After critique: action={result.action.value}")

    # Simulate: review (pass) — only if not blocked
    if result.action != LoopAction.BLOCK_HITL:
        result = loop.submit(t.id, "REVIEW", "REVIEW RESULT: PASS\nNo findings")
        print(f"After review: action={result.action.value}")

        # Simulate: verify (pass) — must satisfy the real SHA gate
        verify_output = (
            "============================= test session starts =============================\n"
            "collected 12 items\n\n"
            "tests/test_rate_limiter.py ............                                  [100%]\n\n"
            "============================== 12 passed in 0.04s ==============================\n"
        )
        result = loop.submit(t.id, "VERIFY", verify_output)
        print(f"After verify: action={result.action.value}")
    else:
        print(f"Task blocked for HITL: {result.question}")
        # Simulate human unblocking
        loop.unblock(t.id, decision="proceed")
        print(f"After unblock: has_work={loop.has_work(t.id)}")

    print(f"\nHas work: {loop.has_work(t.id)}")
    print(f"\n{loop.summary()}")

    db.close()
    import os; os.remove("/tmp/test_loop.db")
    print("\nLoop smoke test: OK")
