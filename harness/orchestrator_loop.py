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
        """Determine the next phase for a task."""
        return self.enforcer.get_phase(task_id) or "IMPLEMENT"

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
            self._impl_retry_counts[task_id] = self._impl_retry_counts.get(task_id, 0) + 1
            total = self._retry_counts.get(task_id, 0) + 1
            self._retry_counts[task_id] = total

            if total >= MAX_TOTAL_RETRIES:
                return self._escalate_to_debugger(task_id, "implementer produced no valid diff after max retries")

            return LoopOutcome(
                action=LoopAction.RETRY, phase="IMPLEMENT", task_id=task_id,
                message=f"Implementer produced no valid diff (attempt {self._impl_retry_counts[task_id]})",
            )

        # ── Real deterministic enforcement (the merge with conductor) ──────
        # Run the same hard gates and intent/scope measurement conductor runs,
        # so the RL reward signal reflects real enforcement, not hardcoded True.
        gate = run_gates(diff, self.registry)
        task_text = f"{task.title} {task.description}".strip()
        scope = measure_scope(task_text, diff)
        self._gate_pass[task_id] = gate.passed
        self._scope_clean[task_id] = scope.scope_clean

        if not gate.passed or scope.intent_mismatch:
            reason = gate.violation if not gate.passed else scope.violation
            name = gate.gate_name if not gate.passed else "intent"
            self._impl_retry_counts[task_id] = self._impl_retry_counts.get(task_id, 0) + 1
            total = self._retry_counts.get(task_id, 0) + 1
            self._retry_counts[task_id] = total
            if total >= MAX_TOTAL_RETRIES:
                return self._escalate_to_debugger(
                    task_id, f"gate '{name}' failing after max retries"
                )
            return LoopOutcome(
                action=LoopAction.RETRY, phase="IMPLEMENT", task_id=task_id,
                message=f"Gate [{name}] failed: {reason[:120]}",
            )

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
        return LoopOutcome(
            action=LoopAction.RUN_PHASE, phase="REVIEW", task_id=task_id,
            message="Critique clean — advancing to review",
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

        self.enforcer.mark_complete(
            task_id, "REVIEW",
            agent="reviewer",
            summary=review[:200],
            findings=review,
            verdict="PASS" if "PASS" in review else "SOFT_FAIL",
        )
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
        self.enforcer.mark_complete(
            task_id, "DONE",
            agent="orchestrator",
        )

        # ── RECORD REWARD (the RL signal) — a win ───────────────────
        self._record_reward(task_id)

        return LoopOutcome(
            action=LoopAction.DONE, phase="DONE", task_id=task_id,
            message="All phases complete — task done",
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

    # ── Escalation ───────────────────────────────────────────────────────

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
        Run after all tasks complete. Evolves prompts and gates.
        Returns summary of what evolved.
        """
        result = {
            "prompts_evolved": [],
            "gates_generated": [],
            "dashboard": "",
        }

        # Evolve prompts for each task type seen
        for task_type in self.reward_log.all_task_types():
            new_variant = self.evolution.evolve(task_type, "implementer")
            result["prompts_evolved"].append({
                "task_type": task_type,
                "new_variant": new_variant,
            })

        # Auto-evolve gates
        new_gates = self.gate_evolution.auto_evolve(min_count=3)
        result["gates_generated"] = [str(p) for p in new_gates]

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
