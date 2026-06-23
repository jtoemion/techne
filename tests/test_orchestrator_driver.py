"""
test_orchestrator_driver.py — driver.run_plan drives the FULL OrchestratorLoop RL pipeline.

No tokens: a FakeModel returns per-phase artifacts. Proves run_plan walks a task through
IMPLEMENT→CONTEXT_GUARD→CRITIQUE→REVIEW→VERIFY→DONE, runs multiple tasks, feeds the
reward_log, stages evolution after the run, and handles BLOCK_HITL (critique CRITICAL)
by stopping safely or resuming via an on_hitl decision.

Run from tests/:  python test_orchestrator_driver.py
"""

from __future__ import annotations

import json
import subprocess
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
from orchestrator_loop import OrchestratorLoop
from checkpoint import mark_honcho_concluded

# Module-level mock: suppress the real .techne/context git-state check during unit tests.
# The check is integration-level (requires a real repo); here we test SHA-gate logic in isolation.
import unittest.mock as _mock

# Module-level mock: suppress the real .techne/context git-state check during unit tests.
# The check is integration-level (requires a real repo); here we test SHA-gate logic in isolation.
_mock.patch.object(OrchestratorLoop, "_get_uncommitted_context_files", return_value=[]).start()

# Module-level mock: intercept refresh_generated_docs.py subprocess calls during unit tests.
# The script requires a real .techne repo at CWD; unit tests run in temp directories.
_real_subprocess_run = subprocess.run
def _mock_subprocess_run(*args, **kwargs):
    cmd = args[0] if args else kwargs.get('args', [])
    cmd_str = ' '.join(cmd) if isinstance(cmd, list) else str(cmd)
    if 'refresh_generated_docs.py' in cmd_str:
        task_id_arg = 'test'
        if '--task' in cmd:
            idx = cmd.index('--task')
            if idx + 1 < len(cmd):
                task_id_arg = cmd[idx + 1]
        return subprocess.CompletedProcess(
            args=cmd, returncode=0,
            stdout=json.dumps({
                "generated_updated": [".techne/generated/context_index.json", ".techne/generated/subsystem_map.json"],
                "stale_docs": [],
                "touched": [],
                "task_id": task_id_arg,
            }),
            stderr='',
        )
    return _real_subprocess_run(*args, **kwargs)
_mock.patch('subprocess.run', side_effect=_mock_subprocess_run).start()

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
        self._impl_idx = 0  # ensure each IMPLEMENT returns a unique diff

    def __call__(self, system, user, phase):
        self.phases.append(phase)
        if phase == "RECALL":
            mark_honcho_concluded("honcho://conclusion/abc123")
            return (
                "HONCHO_CONTEXT: relevant prior work on product pages and badge components. "
                "User prefers minimal, focused changes.\n"
                "WORKSHOP_CONTEXT: none (unit test)\n"
                "WORKSHOP_FILES: none\n"
                "LESSONS: none\n"
                "FOCUS: add SaleBadge component, keep it minimal, one file change\n"
            )
        if phase == "IMPLEMENT":
            self._impl_idx += 1
            return textwrap.dedent(f"""\
                diff --git a/components/product/SaleBadge{self._impl_idx}.tsx b/components/product/SaleBadge{self._impl_idx}.tsx
                new file mode 100644
                --- /dev/null
                +++ b/components/product/SaleBadge{self._impl_idx}.tsx
                @@ -0,0 +1,6 @@
                +export function SaleBadge{self._impl_idx}() {{
                +  return <span className="badge-sale">Sale {self._impl_idx}</span>
                +}}
                +++ b/app/products/[slug]/page.tsx
                --- a/app/products/[slug]/page.tsx
                @@ -3,4 +3,5 @@
                +import {{ SaleBadge{self._impl_idx} }} from '@/components/product/SaleBadge{self._impl_idx}'
                +  {{product.onSale && <SaleBadge{self._impl_idx} />}}
            """)
        if phase == "CONTEXT_GUARD":
            return (
                "Context audit: change is scoped to the product page. No drift.\n\n"
                "CONCLUDE PUNCH LIST\n"
                "DOCS: NOT_NEEDED: trivial UI change\n"
                "CONTEXT: NOT_NEEDED: no .techne/context files affected\n"
                "HONCHO: saved badge component pattern"
            )
        if phase == "CRITIQUE":
            return self.critique
        if phase == "REVIEW":
            return "REVIEW RESULT: PASS\n\nSHADOW GATE CHECK: clean"
        if phase == "CONCLUDE":
            return (
                "HONCHO: honcho://conclusion/abc123 — Saved badge component pattern.\n"
                "DOCS: NOT_NEEDED: trivial UI component addition does not change architecture/API/workflow.\n"
                "CONTEXT: NOT_NEEDED: project fingerprint unchanged beyond local component diff."
            )
        if phase == "RETRO":
            return (
                "GOAL: add sale badge to product page.\n"
                "DONE: created SaleBadge.tsx, updated page.tsx. IMPLEMENT passed gates, REVIEW passed.\n"
                "CHALLENGES: none — clean diff.\n"
                "ROOM: could have added a test for the badge rendering.\n"
                "FLAWS: no VERIFY test output was needed since the diff was trivial.\n"
                "BETTER: scope was tight, no drift.\n"
                "HOW: focused on the single file change.\n"
                "PATTERNS: component addition pattern — new file + import in parent.\n"
                "REGRESSION WATCH: if SaleBadge import breaks, page.tsx will fail at build."
            )
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
    for ph in ("RECALL", "IMPLEMENT", "CONTEXT_GUARD", "CRITIQUE", "REVIEW", "RETRO", "CONCLUDE"):
        check(f"model drove {ph}", ph in model.phases)
    check("VERIFY ran real tests (model NOT asked for VERIFY)", "VERIFY" not in model.phases)
    check("EVAL is deterministic (model NOT asked for EVAL)", "EVAL" not in model.phases)
    # VERIFY → EVAL (score) → RETRO (reflect) → CONCLUDE → DONE, all recorded in history.
    hist = [e.action for e in db.get_task_history(plan.tasks[0].task_id)]
    check("RECALL recorded in history", "RECALL" in hist)
    check("EVAL recorded in history", "EVAL" in hist)
    check("RETRO recorded in history", "RETRO" in hist)
    check("CONCLUDE recorded in history", "CONCLUDE" in hist)
    check("order is RECALL < IMPLEMENT < EVAL < RETRO < CONCLUDE",
          hist.index("RECALL") < hist.index("IMPLEMENT") < hist.index("EVAL") < hist.index("RETRO") < hist.index("CONCLUDE"))


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
    check("hook saw RECALL", "RECALL" in phases)
    check("hook saw IMPLEMENT", "IMPLEMENT" in phases)
    check("hook saw CRITIQUE", "CRITIQUE" in phases)
    check("hook saw VERIFY", "VERIFY" in phases)
    check("hook saw RETRO close", "RETRO" in phases)
    check("hook saw CONCLUDE close", "CONCLUDE" in phases)


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


def test_retro_gate_rejects_checkbox():
    print("\n[plan — RETRO gate rejects checkbox retros]")
    db, rl = _fresh()

    class CheckboxRetroModel:
        def __init__(self):
            self.phases = []

        def __call__(self, system, user, phase):
            self.phases.append(phase)
            if phase == "RECALL":
                return "Honcho context: relevant prior work on product pages and badge components."
            if phase == "IMPLEMENT":
                return CLEAN_DIFF
            if phase == "CONTEXT_GUARD":
                return "Context audit: change is scoped to the product page. No drift."
            if phase == "CRITIQUE":
                return "No critical issues found. Looks clean."
            if phase == "REVIEW":
                return "REVIEW RESULT: PASS\n\nSHADOW GATE CHECK: clean"
            if phase == "CONCLUDE":
                return (
                    "HONCHO: honcho://conclusion/abc123\n"
                    "DOCS: NOT_NEEDED: checkbox retro test changes no docs.\n"
                    "CONTEXT: NOT_NEEDED: checkbox retro test changes no context."
                )
            if phase == "RETRO":
                return "Clean. Fix is minimal."
            return "ok"

    plan = run_plan(["add sale badge to product page"], model=CheckboxRetroModel(),
                    run_tests=lambda: PASSING_TESTS, db=db, reward_log=rl,
                    prepare_context=False, max_steps_per_task=15)
    # Task should NOT reach DONE — it halts because RETRO keeps failing the gate
    t = plan.tasks[0]
    check("task did NOT reach DONE with checkbox retro", t.status != "DONE")
    check("task halted, blocked, or failed", t.status in ("HALTED", "BLOCKED", "INCOMPLETE", "FAILED"))


def test_retro_gate_accepts_substantive():
    print("\n[plan — RETRO gate accepts substantive retros]")
    db, rl = _fresh()
    plan = run_plan(["add sale badge to product page"], model=FakeModel(),
                    run_tests=lambda: PASSING_TESTS, db=db, reward_log=rl,
                    prepare_context=False)
    t = plan.tasks[0]
    check("task reached DONE with substantive retro", t.status == "DONE")


def test_conclude_gate_requires_context_and_docs_proof():
    print("\n[plan — CONCLUDE gate requires Honcho + docs/context proof]")
    db, rl = _fresh()

    class WeakConcludeModel(FakeModel):
        def __call__(self, system, user, phase):
            if phase == "CONCLUDE":
                return "honcho://conclusion/abc123"
            return super().__call__(system, user, phase)

    plan = run_plan(["add sale badge to product page"], model=WeakConcludeModel(),
                    run_tests=lambda: PASSING_TESTS, db=db, reward_log=rl,
                    prepare_context=False, max_steps_per_task=20)
    t = plan.tasks[0]
    check("task did NOT reach DONE with weak conclude", t.status != "DONE")
    check("task halted, blocked, or failed when conclude proof missing", t.status in ("HALTED", "FAILED"))


def test_conclude_prompt_includes_context_guard_punch_list():
    print("\n[loop — CONCLUDE prompt includes context-guard punch list]")
    db, rl = _fresh()
    plan = run_plan(["add sale badge to product page"], model=FakeModel(),
                    run_tests=lambda: PASSING_TESTS, db=db, reward_log=rl,
                    prepare_context=False)
    # Build prompt from completed task history; even after DONE it should expose the proof contract.
    from orchestrator_loop import OrchestratorLoop
    loop = OrchestratorLoop(db, reward_log=rl)
    prompt = loop.get_prompt(plan.tasks[0].task_id, "CONCLUDE")["user"]
    check("CONCLUDE prompt asks for Honcho proof", "HONCHO" in prompt)
    check("CONCLUDE prompt asks for docs proof", "DOCS" in prompt)
    check("CONCLUDE prompt asks for context proof", ".techne/context" in prompt)
    check("CONCLUDE prompt includes context-guard report", "LATEST CONTEXT_GUARD REPORT" in prompt)
    check("CONCLUDE prompt mentions SHA requirement", "sha:" in prompt.lower())


def test_conclude_rejects_context_update_without_sha():
    print("\n[loop — CONCLUDE rejects context update without SHA]")
    from orchestrator_loop import LoopAction
    db, rl = _fresh()
    loop = OrchestratorLoop(db, reward_log=rl)
    mark_honcho_concluded("honcho://conclusion/abc123")

    task = db.create_task("add sale badge", description="add badge", discipline="frontend", tags=["test"])
    task_id = task.id
    # Mark all phases up to CONCLUDE as done
    for ph in ("RECALL", "IMPLEMENT", "CONTEXT_GUARD", "CRITIQUE", "REVIEW", "VERIFY", "EVAL", "RETRO"):
        loop.enforcer.mark_complete(task_id, ph, agent="test", summary="ok", findings="ok")

    # _get_uncommitted_context_files is mocked module-wide; SHA gate tested in isolation
    # Proof with context updated but no SHA
    bad_proof = (
        "HONCHO: honcho://conclusion/abc123 — saved badge pattern\n"
        "DOCS: docs/ARCHITECTURE.md updated with badge component\n"
        "CONTEXT: .techne/context/project_digest.md refreshed"
    )
    outcome = loop.submit(task_id, "CONCLUDE", bad_proof)
    check("rejects context update without SHA", outcome.action == LoopAction.RETRY)
    check("message mentions SHA", "sha" in outcome.message.lower())

    # Proof with context updated AND SHA
    good_proof = (
        "HONCHO: honcho://conclusion/abc123 — saved badge pattern\n"
        "DOCS: docs/ARCHITECTURE.md updated with badge component\n"
        "CONTEXT: .techne/context/project_digest.md refreshed sha: f87d411ce52bbf9ca3b4e12f89a5c2d1e0b6f3a7"
    )
    outcome2 = loop.submit(task_id, "CONCLUDE", good_proof)
    check("accepts context update with SHA",
          outcome2.action == LoopAction.RUN_PHASE and outcome2.phase == "REFRESH_CONTEXT")

    # Proof with NOT_NEEDED (no SHA required)
    task2 = db.create_task("add sale badge 2", description="add badge 2", discipline="frontend", tags=["test"])
    task_id2 = task2.id
    for ph in ("RECALL", "IMPLEMENT", "CONTEXT_GUARD", "CRITIQUE", "REVIEW", "VERIFY", "EVAL", "RETRO"):
        loop.enforcer.mark_complete(task_id2, ph, agent="test", summary="ok", findings="ok")
    not_needed_proof = (
        "HONCHO: honcho://conclusion/def456 — trivial change\n"
        "DOCS: NOT_NEEDED: no architecture changes\n"
        "CONTEXT: NOT_NEEDED: no context changes"
    )
    outcome3 = loop.submit(task_id2, "CONCLUDE", not_needed_proof)
    check("NOT_NEEDED context does not require SHA",
          outcome3.action == LoopAction.RUN_PHASE and outcome3.phase == "REFRESH_CONTEXT")


def test_a2_refresh_context_retry_on_fail():
    """A failing script run produces a RETRY, not a silent pass."""
    from unittest.mock import patch
    from orchestrator_loop import LoopAction

    outcomes = []  # (phase, action, message)

    def capture(task, phase, outcome):
        outcomes.append((phase, outcome.action, outcome.message))

    # Mock subprocess.run to fail for refresh_generated_docs.py
    real_run = _real_subprocess_run

    def fail_mock(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "refresh_generated_docs.py" in cmd_str:
            return subprocess.CompletedProcess(
                args=cmd, returncode=1,
                stdout="", stderr="Refresh script crashed: disk full",
            )
        return real_run(*args, **kwargs)

    with patch("subprocess.run", side_effect=fail_mock):
        db, rl = _fresh()
        plan = run_plan(
            ["add sale badge to product page"],
            model=FakeModel(),
            run_tests=lambda: PASSING_TESTS,
            db=db, reward_log=rl,
            prepare_context=False,
            max_steps_per_task=15,
            on_submit=capture,
        )

        t = plan.tasks[0]
        # Task should NOT silently reach DONE
        check("task did not silently reach DONE", t.status != "DONE")

        # At least one RETRY was produced for REFRESH_CONTEXT
        refresh_retries = [
            (p, m) for p, a, m in outcomes
            if p == "REFRESH_CONTEXT" and a == LoopAction.RETRY
        ]
        check("at least one REFRESH_CONTEXT RETRY produced", len(refresh_retries) > 0)

        # The RETRY message contains the failure reason
        msg = refresh_retries[0][1] if refresh_retries else ""
        check("RETRY message mentions failure reason",
              "failed" in msg.lower() or "crashed" in msg.lower() or "disk" in msg.lower())


def test_post_run_evolve_called_on_done():
    """post_run_evolve() fires automatically when submit() returns DONE."""
    print("\n[loop — post_run_evolve fires on DONE]")
    db, rl = _fresh()

    called = {"n": 0}
    orig_compute = rl.compute_batch_advantages

    def tracking_compute(*args, **kwargs):
        called["n"] += 1
        return orig_compute(*args, **kwargs)

    with _mock.patch.object(rl, "compute_batch_advantages", tracking_compute):
        plan = run_plan(
            ["add sale badge to product page"],
            model=FakeModel(),
            run_tests=lambda: PASSING_TESTS,
            db=db,
            reward_log=rl,
            prepare_context=False,
        )

    check("task reached DONE", plan.tasks[0].status == "DONE")
    check("compute_batch_advantages called at least once", called["n"] >= 1)


def test_batch_mode_queues_tasks():
    """With rl_batch_size=N (>1), post_run_evolve fires only when the Nth task DONE arrives.

    Tasks 1..N-1: compute_batch_advantages NOT called.
    Task N:        compute_batch_advantages called once (flush), then post_run_evolve fires.
    """
    print("\n[loop — batch mode rl_batch_size=3 queues tasks and fires on Nth DONE]")
    db, rl = _fresh()

    batch_calls = {"n": 0}
    orig_compute = rl.compute_batch_advantages

    def tracking_compute(*args, **kwargs):
        batch_calls["n"] += 1
        return orig_compute(*args, **kwargs)

    with _mock.patch.object(rl, "compute_batch_advantages", tracking_compute):
        plan = run_plan(
            ["add sale badge to product page",
             "add wishlist button to product page",
             "add share button to product page"],
            model=FakeModel(),
            run_tests=lambda: PASSING_TESTS,
            db=db,
            reward_log=rl,
            prepare_context=False,
            rl_batch_size=3,
        )

    check("all 3 tasks reached DONE", all(t.status == "DONE" for t in plan.tasks))
    # With batch_size=3: 1 batch flush → 1 post_run_evolve call.
    # driver.py also calls post_run_evolve once after all tasks → total ≤ 2.
    check("compute_batch_advantages called by batch flush (≥1, ≤2)", 1 <= batch_calls["n"] <= 2)


def test_immediate_mode_no_change():
    """rl_batch_size=1 (default) should call post_run_evolve on every DONE — no behavioural change."""
    print("\n[loop — immediate mode rl_batch_size=1 fires on every DONE]")
    db, rl = _fresh()

    batch_calls = {"n": 0}
    orig_compute = rl.compute_batch_advantages

    def tracking_compute(*args, **kwargs):
        batch_calls["n"] += 1
        return orig_compute(*args, **kwargs)

    with _mock.patch.object(rl, "compute_batch_advantages", tracking_compute):
        plan = run_plan(
            ["add sale badge to product page", "add wishlist button to product page"],
            model=FakeModel(),
            run_tests=lambda: PASSING_TESTS,
            db=db,
            reward_log=rl,
            prepare_context=False,
            rl_batch_size=1,  # default
        )

    check("all tasks DONE", all(t.status == "DONE" for t in plan.tasks))
    # With batch_size=1, each DONE fires post_run_evolve → at least 2 calls
    # (driver.py also calls post_run_evolve once after all tasks, so >= 2)
    check("compute_batch_advantages called on every DONE (≥2 calls)", batch_calls["n"] >= 2)


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
    test_retro_gate_rejects_checkbox()
    test_retro_gate_accepts_substantive()
    test_conclude_gate_requires_context_and_docs_proof()
    test_conclude_prompt_includes_context_guard_punch_list()
    test_conclude_rejects_context_update_without_sha()
    test_a2_refresh_context_retry_on_fail()
    test_post_run_evolve_called_on_done()
    test_batch_mode_queues_tasks()
    test_immediate_mode_no_change()
    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed" + ("  -- all clear" if passed == total else f"  ({total-passed} FAILED)"))
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
