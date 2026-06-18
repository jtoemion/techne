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
        """
        from pipeline_enforcer import PHASES

        # A reset task (PENDING, e.g. after a debugger/re-implement unblock) resumes at
        # IMPLEMENT even though stale completed-phase events linger in history.
        task = self.db.get_task(task_id)
        if task and task.status == "PENDING":
            return "IMPLEMENT"

        last = self.enforcer.get_phase(task_id)
        if last is None:
            return "IMPLEMENT"
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

        if phase == "IMPLEMENT":
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

    # ── Phase submission handlers ────────────────────────────────────────

    def _submit_implement(self, task_id: str, diff: str) -> LoopOutcome:
        """Process implementer output. Check gates, retry or advance."""
        task = self.db.get_task(task_id)

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

        return LoopOutcome(
            action=LoopAction.RUN_PHASE, phase="CONTEXT_GUARD", task_id=task_id,
            message="Implementation complete — advancing to context-guard",
        )

    def _submit_context_guard(self, task_id: str, audit: str) -> LoopOutcome:
        """Process context-guard output. Record and advance."""
        self.enforcer.mark_complete(
            task_id, "CONTEXT_GUARD",
            agent="context-guard",
            summary=audit[:200],
            findings=audit,
        )
        return LoopOutcome(
            action=LoopAction.RUN_PHASE, phase="CRITIQUE", task_id=task_id,
            message="Audit complete — advancing to critique",
        )

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
            return LoopOutcome(
                action=LoopAction.BLOCK_HITL, phase="CRITIQUE", task_id=task_id,
                question=f"CRITICAL issue found: {critical_line[:150]}",
                options=[
                    "Proceed to review anyway",
                    "Send to debugger",
                    "Block and re-implement",
                ],
            )

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
        return LoopOutcome(
            action=LoopAction.RUN_PHASE, phase="REVIEW", task_id=task_id,
            message=f"Critique clean — advancing to review{suffix}",
        )

    def _submit_review(self, task_id: str, review: str) -> LoopOutcome:
        """Process review output. Retry on HARD_FAIL, else advance."""
        is_hard_fail = "HARD_FAIL" in review.upper()

        if is_hard_fail:
            self._retry_counts[task_id] = self._retry_counts.get(task_id, 0) + 1

            if self._retry_counts[task_id] >= MAX_TOTAL_RETRIES:
                return self._escalate_to_debugger(task_id, "reviewer HARD_FAIL after max retries")

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
            return LoopOutcome(
                action=LoopAction.BLOCK_HITL, phase="REVIEW", task_id=task_id,
                question=f"Review failed: {review[:150]}",
                options=[
                    "Retry implementation",
                    "Send to debugger",
                    "Override and proceed",
                ],
            )

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
        return LoopOutcome(
            action=LoopAction.RUN_PHASE, phase="VERIFY", task_id=task_id,
            message="Review passed — advancing to verify",
        )

    def _submit_verify(self, task_id: str, test_output: str) -> LoopOutcome:
        """Process test output. Done if the SHA gate passes, retry/escalate if not."""
        # Real verification — the SHA gate confirms tests actually ran (no fakes,
        # unique hash, pass indicators present), the same gate conductor uses.
        verify = verify_tests(test_output)
        self._test_pass[task_id] = verify.passed

        if not verify.passed:
            self._retry_counts[task_id] = self._retry_counts.get(task_id, 0) + 1

            if self._retry_counts[task_id] >= MAX_TOTAL_RETRIES:
                return self._escalate_to_debugger(task_id, "tests failing after max retries")

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
            return LoopOutcome(
                action=LoopAction.BLOCK_HITL, phase="VERIFY", task_id=task_id,
                question=f"Tests failing: {test_output[:150]}",
                options=[
                    "Retry implementation",
                    "Send to debugger",
                    "Override and proceed",
                ],
            )

        self.enforcer.mark_complete(
            task_id, "VERIFY",
            agent="verifier",
            summary=f"Tests passed",
            test_output_hash=hash(test_output).__repr__(),
        )

        # Tests passed — score the run (EVAL) before reflecting (RETRO).
        return LoopOutcome(
            action=LoopAction.RUN_PHASE, phase="EVAL", task_id=task_id,
            message="Verified — advancing to eval (deterministic score)",
        )

    def _submit_eval(self, task_id: str, _ignored: str = "") -> LoopOutcome:
        """EVAL phase — the deterministic 100-point score. No model: computed from the
        real signals captured during the run (_run_eval also records the phase).
        Advances to RETRO so reflection has the objective score to reason about."""
        report = self._run_eval(task_id)   # computes the score AND marks EVAL complete
        return LoopOutcome(
            action=LoopAction.RUN_PHASE, phase="RETRO", task_id=task_id,
            message=f"Scored {report.total}/100 ({report.grade}) — advancing to retro",
        )

    def _submit_retro(self, task_id: str, reflection: str) -> LoopOutcome:
        """RETRO phase — record the run's reflection, then close.

        The retro agent (agents/retro.md) answers the structured questions, reflects on
        the EVAL score + per-skill recurrence, and STAGES skill-edit proposals
        (ratify-gated, never auto-applied). Here we record it, mark DONE, and record the
        RL reward — so reflection + learning happen on EVERY run, not never.
        """
        self.enforcer.mark_complete(
            task_id, "RETRO", agent="retro",
            summary=reflection[:200], findings=reflection,
        )
        self.enforcer.mark_complete(task_id, "DONE", agent="orchestrator")
        self._record_reward(task_id)

        report = self._eval.get(task_id)
        total = report.total if report else 0
        return LoopOutcome(
            action=LoopAction.DONE, phase="DONE", task_id=task_id,
            message=f"All phases complete — eval {total}/100",
        )

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
        )

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
            return self._escalate_to_debugger(
                task_id, f"'{name}' failing after max retries"
            )
        return LoopOutcome(
            action=LoopAction.RETRY, phase="IMPLEMENT", task_id=task_id,
            message=f"[{name}] failed (attempt {self._impl_retry_counts[task_id]}): {reason[:120]}",
        )

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
            "IMPLEMENT": "implementer",
            "CONTEXT_GUARD": "context-guard",
            "CRITIQUE": "critique",
            "REVIEW": "reviewer",
            "VERIFY": "verifier",
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

        if prior:
            lines.append("")
            lines.append("COMPLETED PHASES:")
            for e in prior:
                lines.append(f"  {e.action}: {e.summary[:100]}")

        return "\n".join(lines)

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
