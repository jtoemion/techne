"""
driver.py — the model-backed RUNNER that drives Techne's OrchestratorLoop RL pipeline.

orchestrator_loop.py is a state machine: each phase exposes a prompt and a `submit_*()`
that runs the REAL gates, but it never calls a model itself. This driver walks a GROUP
of tasks through the full pipeline (IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW →
VERIFY → … → DONE), pulling each phase artifact from an injected `model` and feeding it
back through the gates. It's the autonomous/RL counterpart to the host-driven loop
(where a host agent delegates each phase to a subagent instead of an injected model).

The model is INJECTED (a callable), not imported, on purpose:
  - the whole loop is unit-tested deterministically with a fake model (no tokens), and
  - the real backend (Anthropic SDK, headless `claude -p`, …) is a thin adapter you
    plug in, decided separately from the loop logic. See make_*_model adapters below
    once a backend is chosen.

IMPORTANT — VERIFY runs REAL tests, never the model. The SHA gate exists to reject
faked test output; asking a model to "return stdout" would defeat it. So `run_tests`
must actually execute the suite and return its real stdout.

Usage (with a real backend wired into `model`):
    from driver import run_plan
    plan = run_plan(["add sale badge to product page"], model=my_model, run_tests=my_tests)
    print(plan.summary)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from model_backends import default_provider

ROOT = Path(__file__).resolve().parent.parent   # techne/

# A model call for one agent phase: (system, user, phase) -> raw text artifact.
#   phase is "implement" | "review" | "retro" so an adapter can pick model/temp per role.
ModelFn = Callable[[str, str, str], str]
# A real test run: () -> full stdout (it gets hashed by the SHA gate, so it must be real).
TestFn = Callable[[], str]


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


def _drive_task(loop, task, model: ModelFn, run_tests: TestFn, on_hitl, max_steps: int,
                on_submit=None):
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
        if on_submit is not None:
            on_submit(task, phase, outcome)
        action = outcome.action
        if action == LoopAction.DONE:
            print(loop.summarize_incomplete(tid))
            return TaskRun(tid, task.title, "DONE")
        if action == LoopAction.FAILED:
            print(loop.summarize_incomplete(tid))
            return TaskRun(tid, task.title, "FAILED", outcome.message)
        if action == LoopAction.BLOCK_HITL:
            if on_hitl is None:                        # no human → stop this task safely
                print(loop.summarize_incomplete(tid))
                return TaskRun(tid, task.title, "BLOCKED", outcome.question, outcome.options)
            loop.unblock(tid, on_hitl(outcome))        # human/policy decided → resume
            phase = loop.next_phase(tid)               # resume at the correct phase
            continue
        # RUN_PHASE / RETRY (/ ESCALATE) → the handler set the next phase to run
        phase = outcome.phase
    print(loop.summarize_incomplete(tid))
    return TaskRun(tid, task.title, "HALTED", f"exceeded {max_steps} steps")


def run_plan(
    tasks,
    model: ModelFn,
    run_tests: TestFn,
    *,
    db=None,
    reward_log=None,
    on_hitl=None,
    on_submit=None,
    prepare_context: bool = True,
    project_root: Path = ROOT,
    evolve: bool = True,
    max_steps_per_task: int = 40,
    rl_batch_size: int = 1,
) -> PlanResult:
    """Drive a GROUP of tasks through the full OrchestratorLoop RL pipeline.

    Step 0 (amortized, ONCE): build/refresh the .techne/context pack so workers don't
    re-derive the repo. Then each task runs IMPLEMENT→CONTEXT_GUARD→CRITIQUE→REVIEW→
    VERIFY→DONE — model artifacts per phase, REAL tests at VERIFY. After all tasks, RL
    proposals are STAGED via post_run_evolve (prompts + gates, gated behind ratify —
    never auto-promoted). `on_hitl(outcome) -> decision` resolves a BLOCK_HITL; the
    default (None) stops that task safely instead of auto-approving.

    `tasks` is a list of strings (titles) or {"title","description"} dicts.
    `on_submit(task, phase, outcome)` runs after every loop.submit(); hosts use it for
    durable checkpoints such as Honcho after every phase submission.
    """
    from task_db import TaskDB
    from orchestrator_loop import OrchestratorLoop

    # RECALL bookend (once, amortized): serve a hot context pack to every task/phase.
    if prepare_context:
        from context_build import ensure_context
        ensure_context(project_root)

    db = db or TaskDB()
    loop = OrchestratorLoop(db, reward_log=reward_log, rl_batch_size=rl_batch_size)

    runs = []
    for spec in tasks:
        if isinstance(spec, str):
            task = db.create_task(spec)
        else:
            task = db.create_task(
                spec["title"],
                description=spec.get("description", ""),
                parent_id=spec.get("parent_id"),
                discipline=spec.get("discipline", "tdd"),
                priority=spec.get("priority", 0),
                tags=spec.get("tags"),
                phase_mode=spec.get("phase_mode", "full"),
            )
        runs.append(_drive_task(loop, task, model, run_tests, on_hitl,
                                max_steps_per_task, on_submit=on_submit))

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

    from model_backends import make_model, make_phase_router, providers, command_test_runner

    ap = argparse.ArgumentParser(
        description="Drive a Techne pipeline run end-to-end with any model provider.",
    )
    ap.add_argument("task", nargs="?", help="a single task (omit if using --plan)")
    ap.add_argument("--plan", metavar="FILE",
                    help="run a GROUP of tasks (one per line) through the full RL pipeline")
    ap.add_argument("--provider", choices=providers(), default=default_provider(),
                    help="model provider (default: Xiaomi/Mimo via minimax, no API key if configured)")
    ap.add_argument("--model", default=None,
                    help="model id (provider default if omitted)")
    ap.add_argument("--base-url", default=None,
                    help="OpenAI-compatible endpoint for --provider openai "
                         "(OpenRouter/Groq/Together/Ollama/…)")
    ap.add_argument("--test-cmd", default="python -m pytest -q",
                    help="REAL command run for VERIFY (its stdout is SHA-gated)")
    ap.add_argument("--subagent-model", default=None,
                    help="model id for subagent phases (default: same as --model). "
                         "Use this to route CRITIQUE/REVIEW/RETRO to a different model.")
    ap.add_argument("--subagent-provider", default=None,
                    help="provider for subagent phases (default: same as --provider)")
    args = ap.parse_args()

    if not args.task and not args.plan:
        ap.error("provide a task or --plan FILE")

    if args.subagent_model or args.subagent_provider:
        # Phase routing: default model for IMPLEMENT, subagent model for other phases
        sub_provider = args.subagent_provider or args.provider
        sub_model = args.subagent_model or args.model
        router = make_phase_router(
            default=args.provider,
            default_model=args.model,
            routes={
                "critique": (sub_provider, sub_model),
                "review":   (sub_provider, sub_model),
                "retro":    (sub_provider, sub_model),
                "conclude": (sub_provider, sub_model),
                "recall":   (sub_provider, sub_model),
                "context_guard": (sub_provider, sub_model),
            },
        )
        model = router
    else:
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
