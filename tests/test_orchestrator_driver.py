"""
test_orchestrator_driver.py — driver.run_plan drives the FULL OrchestratorLoop RL pipeline.

No tokens: a FakeModel returns per-phase artifacts. Proves run_plan walks a task through
IMPLEMENT→CONTEXT_GUARD→CRITIQUE→REVIEW→VERIFY→DONE, runs multiple tasks, feeds the
reward_log, stages evolution after the run, and handles BLOCK_HITL (critique CRITICAL)
by stopping safely or resuming via an on_hitl decision.

Run from tests/:  python test_orchestrator_driver.py
"""

from __future__ import annotations

import sys
import tempfile
import textwrap
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(TESTS_DIR)); import _mem_guard  # noqa: snapshots memory/, restores at exit

from driver import run_plan
from task_db import TaskDB
from reward_log import RewardLog

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []


def check(label, cond):
    results.append(bool(cond))
    print(f"  {PASS if cond else FAIL} {label}")


CLEAN_DIFF = textwrap.dedent("""\
    diff --git a/components/product/SaleBadge.tsx b/components/product/SaleBadge.tsx
    new file mode 100644
    --- /dev/null
    +++ b/components/product/SaleBadge.tsx
    @@ -0,0 +1,6 @@
    +export function SaleBadge() {
    +  return <span className="badge-sale">Sale</span>
    +}
    +++ b/app/products/[slug]/page.tsx
    --- a/app/products/[slug]/page.tsx
    @@ -3,4 +3,5 @@
    +import { SaleBadge } from '@/components/product/SaleBadge'
    +  {product.onSale && <SaleBadge />}
""")

PASSING_TESTS = "=== BUILD ===\nCompiled successfully\n\n=== TYPE CHECK ===\nNo issues found\n"


class FakeModel:
    def __init__(self, *, critique="No critical issues found. Looks clean."):
        self.critique = critique
        self.phases = []

    def __call__(self, system, user, phase):
        self.phases.append(phase)
        if phase == "IMPLEMENT":
            return CLEAN_DIFF
        if phase == "CONTEXT_GUARD":
            return "Context audit: change is scoped to the product page. No drift."
        if phase == "CRITIQUE":
            return self.critique
        if phase == "REVIEW":
            return "REVIEW RESULT: PASS\n\nSHADOW GATE CHECK: clean"
        return "ok"


def _fresh():
    db = TaskDB(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    rl = RewardLog(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    return db, rl


def test_single_task_runs_all_phases_to_done():
    print("\n[plan — one task walks every phase to DONE]")
    db, rl = _fresh()
    model = FakeModel()
    plan = run_plan(["add sale badge to product page"], model=model,
                    run_tests=lambda: PASSING_TESTS, db=db, reward_log=rl,
                    prepare_context=False)
    t = plan.tasks[0]
    check("task reached DONE", t.status == "DONE")
    for ph in ("IMPLEMENT", "CONTEXT_GUARD", "CRITIQUE", "REVIEW", "RETRO"):
        check(f"model drove {ph}", ph in model.phases)
    check("VERIFY ran real tests (model NOT asked for VERIFY)", "VERIFY" not in model.phases)
    check("EVAL is deterministic (model NOT asked for EVAL)", "EVAL" not in model.phases)
    # VERIFY → EVAL (score) → RETRO (reflect) → DONE, all recorded in history.
    hist = [e.action for e in db.get_task_history(plan.tasks[0].task_id)]
    check("EVAL recorded in history", "EVAL" in hist)
    check("RETRO recorded in history", "RETRO" in hist)
    check("order is VERIFY < EVAL < RETRO",
          hist.index("VERIFY") < hist.index("EVAL") < hist.index("RETRO"))


def test_reward_log_and_evolution_fed():
    print("\n[plan — the RL loop is actually fed + evolution staged]")
    db, rl = _fresh()
    plan = run_plan(["add sale badge to product page"], model=FakeModel(),
                    run_tests=lambda: PASSING_TESTS, db=db, reward_log=rl,
                    prepare_context=False)
    rows = rl._conn.execute("SELECT COUNT(*) FROM rewards").fetchone()[0]
    check("reward_log recorded the run", rows >= 1)
    check("evolution staged (keys present)",
          "prompts_proposed" in plan.evolution and "gates_proposed" in plan.evolution)


def test_multi_task_plan():
    print("\n[plan — a GROUP of tasks all complete]")
    db, rl = _fresh()
    plan = run_plan(
        ["add sale badge to product page", "add wishlist button to product page"],
        model=FakeModel(), run_tests=lambda: PASSING_TESTS, db=db, reward_log=rl,
        prepare_context=False,
    )
    check("two task runs returned", len(plan.tasks) == 2)
    check("all tasks DONE", plan.all_done)


def test_on_submit_hook_runs_after_every_phase_submit():
    print("\n[plan — on_submit hook sees every phase submission]")
    db, rl = _fresh()
    seen = []
    run_plan(["add sale badge to product page"], model=FakeModel(),
             run_tests=lambda: PASSING_TESTS, db=db, reward_log=rl,
             prepare_context=False,
             on_submit=lambda task, phase, outcome: seen.append((phase, outcome.action.value)))
    phases = [phase for phase, _ in seen]
    check("hook saw IMPLEMENT", "IMPLEMENT" in phases)
    check("hook saw CRITIQUE", "CRITIQUE" in phases)
    check("hook saw VERIFY", "VERIFY" in phases)
    check("hook saw RETRO close", "RETRO" in phases)


def test_critique_follow_up_tasks_become_children_immediately():
    print("\n[plan — critique FOLLOW_UP_TASK lines become child tasks]")
    db, rl = _fresh()
    critique = """CRITIQUE REPORT
Risk Level: LOW
LOW:
- Index lookup is pre-existing and out of scope [convex/schema.ts:12] — would slow reads.
FOLLOW_UP_TASKS:
- FOLLOW_UP_TASK: Add Convex index for users.by_email lookup
VERDICT: CLEAR
"""
    plan = run_plan(["add sale badge to product page"], model=FakeModel(critique=critique),
                    run_tests=lambda: PASSING_TESTS, db=db, reward_log=rl,
                    prepare_context=False)
    children = db.get_children(plan.tasks[0].task_id)
    check("one follow-up child task created", len(children) == 1)
    check("child keeps critique-follow-up tag", "critique-follow-up" in children[0].tags)
    check("child title came from FOLLOW_UP_TASK", children[0].title == "Add Convex index for users.by_email lookup")


def test_critique_ignores_placeholder_follow_up_tasks():
    print("\n[plan — critique placeholder FOLLOW_UP_TASK lines are ignored]")
    db, rl = _fresh()
    critique = """CRITIQUE REPORT
Risk Level: LOW
LOW:
- No issues found.
FOLLOW_UP_TASKS:
- FOLLOW_UP_TASK: <atomic task title for any real but out-of-scope finding>
VERDICT: CLEAR
"""
    plan = run_plan(["add sale badge to product page"], model=FakeModel(critique=critique),
                    run_tests=lambda: PASSING_TESTS, db=db, reward_log=rl,
                    prepare_context=False)
    children = db.get_children(plan.tasks[0].task_id)
    check("placeholder follow-up did not create a child", len(children) == 0)


def test_critical_critique_still_creates_follow_up_tasks_before_hitl():
    print("\n[plan — CRITICAL critique keeps explicit follow-up tasks]")
    db, rl = _fresh()
    critique = """CRITIQUE REPORT
Risk Level: CRITICAL
CRITICAL:
- CRITICAL [src/foo.py:1] — blocking issue.
FOLLOW_UP_TASKS:
- FOLLOW_UP_TASK: Add regression coverage for foo edge case
VERDICT: NEEDS_FIX
"""
    plan = run_plan(["add sale badge to product page"], model=FakeModel(critique=critique),
                    run_tests=lambda: PASSING_TESTS, db=db, reward_log=rl,
                    prepare_context=False, on_hitl=lambda outcome: "Proceed to review anyway")
    children = db.get_children(plan.tasks[0].task_id)
    check("critical critique created the follow-up child", len(children) == 1)
    check("critical follow-up title preserved",
          children[0].title == "Add regression coverage for foo edge case")


def test_critical_blocks_then_resumes_with_hitl():
    print("\n[plan — critique CRITICAL → BLOCK_HITL, resolved by on_hitl]")
    db, rl = _fresh()
    # No human → stops safely at BLOCKED.
    blocked = run_plan(["add sale badge to product page"],
                       model=FakeModel(critique="CRITICAL: unsanitized prop injected"),
                       run_tests=lambda: PASSING_TESTS, db=db, reward_log=rl,
                       prepare_context=False)
    check("task BLOCKED without a human", blocked.tasks[0].status == "BLOCKED")
    check("the HITL question surfaced", "CRITICAL" in blocked.tasks[0].detail)

    # With an on_hitl policy that proceeds, the task moves past the block.
    db2, rl2 = _fresh()
    resumed = run_plan(["add sale badge to product page"],
                       model=FakeModel(critique="CRITICAL: unsanitized prop injected"),
                       run_tests=lambda: PASSING_TESTS, db=db2, reward_log=rl2,
                       prepare_context=False,
                       on_hitl=lambda outcome: "Proceed to review anyway")
    check("on_hitl moved the task off BLOCKED",
          resumed.tasks[0].status in ("DONE", "HALTED", "INCOMPLETE", "FAILED"))


def test_prepare_context_invokes_amortization():
    print("\n[plan — prepare_context runs the amortized context step once]")
    import driver as drv
    called = {"n": 0}
    import context_build
    orig = context_build.ensure_context
    context_build.ensure_context = lambda *a, **k: called.__setitem__("n", called["n"] + 1)
    try:
        db, rl = _fresh()
        run_plan(["t1", "t2"], model=FakeModel(), run_tests=lambda: PASSING_TESTS,
                 db=db, reward_log=rl, prepare_context=True)
        check("ensure_context called exactly once for the whole plan", called["n"] == 1)
    finally:
        context_build.ensure_context = orig


if __name__ == "__main__":
    print("=" * 60)
    print("ORCHESTRATOR DRIVER — run_plan drives the full RL pipeline")
    print("=" * 60)
    test_single_task_runs_all_phases_to_done()
    test_reward_log_and_evolution_fed()
    test_multi_task_plan()
    test_on_submit_hook_runs_after_every_phase_submit()
    test_critique_follow_up_tasks_become_children_immediately()
    test_critique_ignores_placeholder_follow_up_tasks()
    test_critical_critique_still_creates_follow_up_tasks_before_hitl()
    test_critical_blocks_then_resumes_with_hitl()
    test_prepare_context_invokes_amortization()
    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed" + ("  -- all clear" if passed == total else f"  ({total-passed} FAILED)"))
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
