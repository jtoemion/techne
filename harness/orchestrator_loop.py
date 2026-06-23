"""
orchestrator_loop.py — The pipeline loop driver (PUBLIC FACADE).

Takes a list of task IDs and drives them through the multi-agent pipeline:
  IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → DONE

This is NOT an agent. It's a state machine that generates prompts for the
host agent to execute. The host runs each prompt as its own model turn,
then feeds the result back via submit_*().

Usage:
    from orchestrator_loop import OrchestratorLoop, LoopAction, LoopOutcome
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
import time
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
from _loop_types import (
    LoopAction, LoopOutcome,
    HARNESS_DIR, ROOT, AGENTS_DIR,
    MAX_IMPLEMENT_RETRIES, MAX_TOTAL_RETRIES, DEFAULT_VARIANT_COUNT,
    MAX_PHASE_RETRIES, PHASE_TIMEOUT_SECONDS,
)
from evaluator import evaluate_pipeline_run, EvalReport
from checkpoint import check_honcho_logged
from grpo import propose_grpo_edits


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
        # Per-phase retry counters: {task_id: {phase: count}}
        self._phase_retry_counts: dict[str, dict[str, int]] = {}

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
        # Per-phase timeout tracking: {task_id: {phase: start_time}}
        self._phase_started_at: dict[str, dict[str, float]] = {}

    def has_work(self, task_id: str) -> bool:
        """Check if a task still has phases to run."""
        task = self.db.get_task(task_id)
        if not task:
            return False
        # HALT and FAILED are terminal — no more work
        if task.status in ("DONE", "FAILED", "HALT"):
            return False
        phase = self.enforcer.get_phase(task_id)
        if phase in ("DONE", "FAILED", "HALT"):
            return False
        return True

    def next_phase(self, task_id: str) -> str:
        """The next phase to RUN for a task.

        enforcer.get_phase() returns the last COMPLETED phase, so the next phase is the
        one after it in PHASES (not that phase again — that bug made the loop re-submit
        IMPLEMENT forever). EVAL runs inside VERIFY's handler, so the host never runs it.

        The PENDING short-circuit only fires when no phase has been completed yet for
        this run. The earlier code returned RECALL whenever status==PENDING, which
        trapped the loop after RECALL mark_complete (RECALL's mark_complete only logs
        an event, it doesn't change status, so the short-circuit fired forever and the
        pipeline could never advance to IMPLEMENT). Trust the enforcer's last-completed
        phase if one exists.
        """
        from pipeline_enforcer import PHASES

        task = self.db.get_task(task_id)

        # A PENDING task that has been reset (e.g. after a debugger/re-implement
        # unblock) should resume at the correct starting phase, NOT at the phase
        # after the last completed one — otherwise it gets stuck re-entering the
        # phase that originally blocked.
        if task and task.status == "PENDING":
            completed = {
                e.action for e in self.db.get_task_history(task_id)
                if e.action in PHASES and e.verdict not in ("HARD_FAIL",)
            }
            if "RECALL" not in completed:
                return "RECALL"
            return "IMPLEMENT"

        last = self.enforcer.get_phase(task_id)
        if last is None:
            return "RECALL"
        if last in ("DONE", "FAILED", "HALT"):
            return last

        try:
            return PHASES[PHASES.index(last) + 1]
        except (ValueError, IndexError):
            return "DONE"

    def recommend_mode(self, task_title: str, task_desc: str, diff: str) -> str:
        """Recommend a phase_mode based on diff characteristics.

        Returns a summary string with the recommended mode and all cost estimates.
        Kept for backward compatibility until phase_mode migration.
        """
        from pipeline_enforcer import classify_phase_mode, get_cost_estimate
        mode = classify_phase_mode(task_title, task_desc, diff)
        costs = {m: get_cost_estimate(m) for m in ("micro", "fast", "full")}
        summary = f"Recommended: {mode}. "
        summary += " ".join(
            f"{m}={c['api_calls']} calls" for m, c in costs.items()
        )
        return summary

    def get_prompt(self, task_id: str, phase: str) -> dict:
        """
        Generate the prompt for a subagent assigned to this phase.
        Returns {system: str, user: str} — the agent .md body + assembled context.
        """
        # Mark phase start for timeout tracking
        self._start_phase(task_id, phase)
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
        # Check for phase timeout before processing the result
        if self._check_phase_timeout(task_id, phase):
            outcome = LoopOutcome(
                action=LoopAction.FAILED, phase=phase, task_id=task_id,
                message=(
                    f"Phase '{phase}' timed out after {PHASE_TIMEOUT_SECONDS}s. "
                    "The phase took too long and has been marked FAILED."
                ),
            )
            self._print_phase_summary(phase, task_id, outcome)
            return outcome

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
        elif phase == "APPROVAL":
            return self._submit_approval(task_id, result)
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

    def get_mode_overrides(self, limit: int = 20) -> list[dict]:
        """Return the most recent N mode-override events from the telemetry log."""
        from pipeline_enforcer import get_mode_overrides as _get_overrides
        return _get_overrides(limit=limit)

    def get_learning_insights(self, threshold: int = 3) -> list[str]:
        """Return actionable classifier update suggestions from the learning loop.

        Analyzes the override telemetry log and surfaces patterns that appear
        >= threshold times, returning human-readable tuning suggestions.
        """
        from pipeline_enforcer import suggest_classifier_updates as _suggest
        return _suggest(threshold=threshold)

    def summary(self) -> str:
        """Human-readable summary of all task states."""
        return self.enforcer.dashboard()

    # ── Phase summary printer ─────────────────────────────────────────────

    def _print_phase_summary(self, phase: str, task_id: str, outcome: LoopOutcome) -> None:
        """Print a one-line per-phase summary with bracketed phase tag and (!) for non-clean outcomes."""
        CLEAN_ACTIONS = {LoopAction.RUN_PHASE, LoopAction.DONE}
        marker = " (!)" if outcome.action not in CLEAN_ACTIONS else ""
        print(f"[{phase}]{marker} {outcome.message} -> {outcome.action.value.upper()}")

    # ── Helper methods defined elsewhere (monkey-patched below) ────────────
    # These stubs exist only for type/checking clarity; they are replaced at import time.

    def _submit_recall(self, task_id: str, result: str) -> LoopOutcome:
        ...

    def _submit_implement(self, task_id: str, diff: str) -> LoopOutcome:
        ...

    def _submit_context_guard(self, task_id: str, audit: str) -> LoopOutcome:
        ...

    def _submit_debug(self, task_id: str, diff: str) -> LoopOutcome:
        ...

    def _submit_critique(self, task_id: str, critique: str) -> LoopOutcome:
        ...

    def _submit_review(self, task_id: str, review: str) -> LoopOutcome:
        ...

    def _submit_approval(self, task_id: str, approval_text: str) -> LoopOutcome:
        ...

    def _submit_verify(self, task_id: str, test_output: str) -> LoopOutcome:
        ...

    def _submit_eval(self, task_id: str, _ignored: str = "") -> LoopOutcome:
        ...

    def _submit_retro(self, task_id: str, reflection: str) -> LoopOutcome:
        ...

    def _submit_conclude(self, task_id: str, result: str) -> LoopOutcome:
        ...

    def _submit_refresh_context(self, task_id: str, result: str = "") -> LoopOutcome:
        ...

    def _log_retro_learn_trigger(self, task_id: str, recurrence: dict,
                                 ledger_counts: dict) -> None:
        ...

    def _validate_conclude_proof(self, result: str, task_id: str | None = None) -> str:
        ...

    def _get_uncommitted_context_files(self, touched_files: list[str] | None = None) -> list[str]:
        ...

    def _record_reward(self, task_id: str) -> None:
        ...

    def _ensure_techne_gitignore(self, project_root: str) -> None:
        ...

    def _prune_task_artifacts(self, task_id: str) -> None:
        ...

    def _build_eval_metrics(self, task_id: str) -> dict:
        ...

    def _run_eval(self, task_id: str) -> EvalReport:
        ...

    def get_eval(self, task_id: str) -> EvalReport | None:
        ...

    def _bump_retry(self, task_id: str, phase: str) -> bool:
        ...

    def _reset_phase_retry(self, task_id: str, phase: str) -> None:
        ...

    # ── Phase timeout tracking ─────────────────────────────────────────────

    def _start_phase(self, task_id: str, phase: str) -> None:
        """Record the start time of a phase for timeout tracking."""
        if task_id not in self._phase_started_at:
            self._phase_started_at[task_id] = {}
        self._phase_started_at[task_id][phase] = time.monotonic()

    def _check_phase_timeout(self, task_id: str, phase: str) -> bool:
        """Return True if the phase has exceeded PHASE_TIMEOUT_SECONDS."""
        started = self._phase_started_at.get(task_id, {}).get(phase)
        if started is None:
            return False
        elapsed = time.monotonic() - started
        return elapsed > PHASE_TIMEOUT_SECONDS

    def _impl_retry_or_escalate(self, task_id: str, name: str, reason: str) -> LoopOutcome:
        ...

    def _escalate_to_debugger(self, task_id: str, reason: str) -> LoopOutcome:
        ...

    def _read_agent_body(self, phase: str) -> str:
        ...

    def _diff_stats(self, diff: str) -> str:
        ...

    def summarize_incomplete(self, task_id: str) -> str:
        ...

    # ── Additional helpers referenced by the class but defined elsewhere ──

    def _build_user_context(self, task_id: str, phase: str) -> str:
        ...

    def _expected_phases(self, task_id: str) -> list[str]:
        ...

    def _create_critique_follow_up_tasks(self, task_id: str, critique: str) -> list[str]:
        ...

    def set_task_type(self, task_id: str, task_type: str) -> None:
        ...

    def set_variant(self, task_id: str, variant: str) -> None:
        ...

    def get_best_variant(self, task_type: str, agent: str = "implementer") -> str | None:
        ...

    def post_run_evolve(self) -> dict:
        ...

    def rl_dashboard(self) -> str:
        ...


# ── Monkey-patch: attach all implementation methods from sub-modules ────────

from _recall_implement import (
    _submit_recall, _submit_implement, _submit_context_guard, _submit_debug,
    _extract_files,
)
from _review_approval import (
    _submit_critique, _submit_review, _submit_approval, _submit_verify,
    _extract_findings, _extract_files_from_diff, _extract_follow_up_tasks,
    _create_critique_follow_up_tasks,
)
from _retro_conclude import (
    _submit_eval, _submit_retro, _submit_conclude, _submit_refresh_context,
    _log_retro_learn_trigger,
)
from _orchestrator_helpers import (
    _validate_conclude_proof, _get_uncommitted_context_files,
    _record_reward, _ensure_techne_gitignore, _prune_task_artifacts,
    _build_eval_metrics, _run_eval, get_eval,
)
from _orchestrator_context import (
    _build_user_context, _expected_phases, set_task_type, set_variant,
    get_best_variant, post_run_evolve, rl_dashboard,
)
from _orchestrator_retry import (
    _bump_retry, _reset_phase_retry, _impl_retry_or_escalate,
    _escalate_to_debugger, _read_agent_body, _diff_stats,
    summarize_incomplete, MAX_PHASE_RETRIES,
)

OrchestratorLoop._submit_recall = _submit_recall
OrchestratorLoop._submit_implement = _submit_implement
OrchestratorLoop._submit_context_guard = _submit_context_guard
OrchestratorLoop._submit_debug = _submit_debug
OrchestratorLoop._submit_critique = _submit_critique
OrchestratorLoop._submit_review = _submit_review
OrchestratorLoop._submit_approval = _submit_approval
OrchestratorLoop._submit_verify = _submit_verify
OrchestratorLoop._submit_eval = _submit_eval
OrchestratorLoop._submit_retro = _submit_retro
OrchestratorLoop._submit_conclude = _submit_conclude
OrchestratorLoop._submit_refresh_context = _submit_refresh_context
OrchestratorLoop._log_retro_learn_trigger = _log_retro_learn_trigger
OrchestratorLoop._validate_conclude_proof = _validate_conclude_proof
OrchestratorLoop._get_uncommitted_context_files = _get_uncommitted_context_files
OrchestratorLoop._record_reward = _record_reward
OrchestratorLoop._ensure_techne_gitignore = _ensure_techne_gitignore
OrchestratorLoop._prune_task_artifacts = _prune_task_artifacts
OrchestratorLoop._build_eval_metrics = _build_eval_metrics
OrchestratorLoop._run_eval = _run_eval
OrchestratorLoop.get_eval = get_eval
OrchestratorLoop._bump_retry = _bump_retry
OrchestratorLoop._reset_phase_retry = _reset_phase_retry
OrchestratorLoop._impl_retry_or_escalate = _impl_retry_or_escalate
OrchestratorLoop._escalate_to_debugger = _escalate_to_debugger
OrchestratorLoop._read_agent_body = _read_agent_body
OrchestratorLoop._diff_stats = _diff_stats
OrchestratorLoop.summarize_incomplete = summarize_incomplete
OrchestratorLoop._build_user_context = _build_user_context
OrchestratorLoop._expected_phases = _expected_phases
OrchestratorLoop.set_task_type = set_task_type
OrchestratorLoop.set_variant = set_variant
OrchestratorLoop.get_best_variant = get_best_variant
OrchestratorLoop.post_run_evolve = post_run_evolve
OrchestratorLoop.rl_dashboard = rl_dashboard
OrchestratorLoop._create_critique_follow_up_tasks = _create_critique_follow_up_tasks
