"""
driver.py — the host-driven RUNNER that makes Techne's pipeline actually run.

conductor.Pipeline is a turn-by-turn state machine: every phase exposes a `*_prompt()`
and a `submit_*()` that runs the REAL gates. But nothing drove it — Techne "does not
call a model", so the gates / reviewer / reward never fired on their own; a host had to
step it by hand (see tests/test_conductor.py::drive_pipeline). This is the missing
driver: it walks a task through IMPLEMENT → VERIFY → REVIEW → RETRO, pulling each agent
artifact from an injected `model` and feeding it back through the gates.

The model is INJECTED (a callable), not imported, on purpose:
  - the whole loop is unit-tested deterministically with a fake model (no tokens), and
  - the real backend (Anthropic SDK, headless `claude -p`, …) is a thin adapter you
    plug in, decided separately from the loop logic. See make_*_model adapters below
    once a backend is chosen.

IMPORTANT — VERIFY runs REAL tests, never the model. The SHA gate exists to reject
faked test output; asking a model to "return stdout" would defeat it. So `run_tests`
must actually execute the suite and return its real stdout.

Usage (with a real backend wired into `model`):
    from driver import run_task
    res = run_task("add sale badge to product page", model=my_model, run_tests=my_tests)
    if res.completed:
        print(res.report.format_report())
    else:
        print(f"halted at {res.halted_phase}: {res.halt_feedback}")
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from conductor import Pipeline, MAX_RETRIES, ROOT

# A model call for one agent phase: (system, user, phase) -> raw text artifact.
#   phase is "implement" | "review" | "retro" so an adapter can pick model/temp per role.
ModelFn = Callable[[str, str, str], str]
# A real test run: () -> full stdout (it gets hashed by the SHA gate, so it must be real).
TestFn = Callable[[], str]


@dataclass
class RunResult:
    task: str
    halted_phase: Optional[str]   # None when the run completed every phase
    halt_feedback: str
    report: object                # EvalReport when finalized, else None
    retries_used: int = 0

    @property
    def completed(self) -> bool:
        return self.halted_phase is None


def run_task(
    task: str,
    model: ModelFn,
    run_tests: TestFn,
    *,
    max_attempts: int = MAX_RETRIES,
) -> RunResult:
    """Drive one task through the full pipeline.

    Calls `model` for the IMPLEMENT/REVIEW/RETRO artifacts and `run_tests` for VERIFY.
    Returns a RunResult; on a HALT, `halted_phase` names where it stopped and no
    EvalReport is produced (the gate refused to let the run be called done).
    """
    p = Pipeline.start(task)

    # ── IMPLEMENT — retry loop. implement_prompt() folds in the gate feedback on a
    #    retry, so the model gets told exactly what to fix. The Pipeline HALTs itself
    #    at MAX_RETRIES; the attempts guard is a backstop for a lower max_attempts.
    attempts = 0
    while True:
        ap = p.implement_prompt()
        diff = model(ap.system, ap.user, "implement")
        res = p.submit_implementation(diff)
        if res.status == "PASS":
            break
        if res.status == "HALT":
            return RunResult(task, "IMPLEMENT", res.feedback, None, p.retries_used)
        # RETRY
        attempts += 1
        if attempts > max_attempts:
            return RunResult(task, "IMPLEMENT", res.feedback, None, p.retries_used)

    # ── VERIFY — REAL tests, not the model (the SHA gate rejects faked output) ──
    res = p.submit_verification(run_tests())
    if res.status != "PASS":
        return RunResult(task, "VERIFY", res.feedback, None, p.retries_used)

    # ── REVIEW ──────────────────────────────────────────────────────────────────
    ap = p.review_prompt()
    p.submit_review(model(ap.system, ap.user, "review"))

    # ── RETRO ───────────────────────────────────────────────────────────────────
    ap = p.retro_prompt()
    p.submit_retro(model(ap.system, ap.user, "retro"))

    return RunResult(task, None, "", p.finalize(), p.retries_used)


# ── Multi-task: drive the full OrchestratorLoop RL pipeline ───────────────────

@dataclass
class TaskRun:
    task_id: str
    title: str
    status: str            # DONE | FAILED | BLOCKED | HALTED | INCOMPLETE
    detail: str = ""
    options: Optional[list] = None

    @property
    def done(self) -> bool:
        return self.status == "DONE"


@dataclass
class PlanResult:
    tasks: list           # list[TaskRun]
    evolution: dict       # post_run_evolve summary (staged prompt/gate proposals)
    summary: str          # loop.summary() dashboard

    @property
    def all_done(self) -> bool:
        return bool(self.tasks) and all(t.done for t in self.tasks)


def _drive_task(loop, task, model: ModelFn, run_tests: TestFn, on_hitl, max_steps: int):
    """Walk ONE task through the orchestrator's phases until terminal.

    Driven by each submit's `outcome.phase` (the handler tells us the next phase to run),
    not by next_phase() — outcome.phase is always correct, including RETRY (→IMPLEMENT).
    """
    from orchestrator_loop import LoopAction

    tid = task.id
    phase = loop.next_phase(tid)                       # fresh task → IMPLEMENT
    for _ in range(max_steps):
        # VERIFY runs REAL tests; EVAL is the deterministic score (no model); every
        # other phase asks the model.
        if phase == "VERIFY":
            artifact = run_tests()
        elif phase == "EVAL":
            artifact = ""  # computed from captured signals; no prompt/model needed
        else:
            prompt = loop.get_prompt(tid, phase)
            artifact = model(prompt["system"], prompt["user"], phase)
        outcome = loop.submit(tid, phase, artifact)
        action = outcome.action
        if action == LoopAction.DONE:
            return TaskRun(tid, task.title, "DONE")
        if action == LoopAction.FAILED:
            return TaskRun(tid, task.title, "FAILED", outcome.message)
        if action == LoopAction.BLOCK_HITL:
            if on_hitl is None:                        # no human → stop this task safely
                return TaskRun(tid, task.title, "BLOCKED", outcome.question, outcome.options)
            loop.unblock(tid, on_hitl(outcome))        # human/policy decided → resume
            phase = loop.next_phase(tid)               # resume at the correct phase
            continue
        # RUN_PHASE / RETRY (/ ESCALATE) → the handler set the next phase to run
        phase = outcome.phase
    return TaskRun(tid, task.title, "HALTED", f"exceeded {max_steps} steps")


def run_plan(
    tasks,
    model: ModelFn,
    run_tests: TestFn,
    *,
    db=None,
    reward_log=None,
    on_hitl=None,
    prepare_context: bool = True,
    project_root: Path = ROOT,
    evolve: bool = True,
    max_steps_per_task: int = 40,
) -> PlanResult:
    """Drive a GROUP of tasks through the full OrchestratorLoop RL pipeline.

    Step 0 (amortized, ONCE): build/refresh the .techne/context pack so workers don't
    re-derive the repo. Then each task runs IMPLEMENT→CONTEXT_GUARD→CRITIQUE→REVIEW→
    VERIFY→DONE — model artifacts per phase, REAL tests at VERIFY. After all tasks, RL
    proposals are STAGED via post_run_evolve (prompts + gates, gated behind ratify —
    never auto-promoted). `on_hitl(outcome) -> decision` resolves a BLOCK_HITL; the
    default (None) stops that task safely instead of auto-approving.

    `tasks` is a list of strings (titles) or {"title","description"} dicts.
    """
    from task_db import TaskDB
    from orchestrator_loop import OrchestratorLoop

    # RECALL bookend (once, amortized): serve a hot context pack to every task/phase.
    if prepare_context:
        from context_build import ensure_context
        ensure_context(project_root)

    db = db or TaskDB()
    loop = OrchestratorLoop(db, reward_log=reward_log)

    runs = []
    for spec in tasks:
        if isinstance(spec, str):
            task = db.create_task(spec)
        else:
            task = db.create_task(spec["title"], description=spec.get("description", ""))
        runs.append(_drive_task(loop, task, model, run_tests, on_hitl, max_steps_per_task))

    evolution = loop.post_run_evolve() if evolve else {}

    # CONCLUDE bookend: refresh the derived context so docs/.techne/context stay HOT
    # for the next run (the deterministic half; prose docs/ are the context agent's job).
    if prepare_context:
        from context_build import conclude_context
        conclude_context(project_root)

    return PlanResult(runs, evolution, loop.summary())


if __name__ == "__main__":
    import argparse
    import sys

    from model_backends import make_model, providers, command_test_runner

    ap = argparse.ArgumentParser(
        description="Drive a Techne pipeline run end-to-end with any model provider.",
    )
    ap.add_argument("task", nargs="?", help="a single task (omit if using --plan)")
    ap.add_argument("--plan", metavar="FILE",
                    help="run a GROUP of tasks (one per line) through the full RL pipeline")
    ap.add_argument("--provider", choices=providers(), default="claude-cli",
                    help="model provider (default: headless Claude Code CLI, no API key)")
    ap.add_argument("--model", default=None,
                    help="model id (provider default if omitted)")
    ap.add_argument("--base-url", default=None,
                    help="OpenAI-compatible endpoint for --provider openai "
                         "(OpenRouter/Groq/Together/Ollama/…) — reaches any model")
    ap.add_argument("--test-cmd", default="python -m pytest -q",
                    help="REAL command run for VERIFY (its stdout is SHA-gated)")
    args = ap.parse_args()

    if not args.task and not args.plan:
        ap.error("provide a task or --plan FILE")

    model = make_model(args.provider, model=args.model, base_url=args.base_url)
    run_tests = command_test_runner(args.test_cmd)

    if args.plan:
        tasks = [l.strip() for l in Path(args.plan).read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.startswith("#")]
    else:
        tasks = [args.task]

    # The orchestrator RL pipeline: context-preflight (once) → multi-task loop → evolve.
    plan = run_plan(tasks, model=model, run_tests=run_tests)
    print(plan.summary)
    for t in plan.tasks:
        print(f"  [{t.status:9}] {t.title}" + (f"  — {t.detail}" if t.detail else ""))
    prop = plan.evolution
    if prop:
        print(f"\nstaged: {len(prop.get('prompts_proposed', []))} prompt + "
              f"{len(prop.get('gates_proposed', []))} gate proposal(s) (awaiting ratify)")
    sys.exit(0 if plan.all_done else 1)
