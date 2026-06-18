"""
test_driver.py — proves driver.run_task actually DRIVES the pipeline with a model.

No API key, no network, no tokens: a FakeModel returns canned artifacts, standing in
for a real backend. The point is to prove the loop is REAL — the model is called per
phase, the gates fire on the model's output, a gate violation triggers a retry that
recovers, and faked/failing test output HALTs at VERIFY. With a real model adapter
swapped in for FakeModel, the same loop runs autonomously.

Run from tests/:  python test_driver.py
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(TESTS_DIR)); import _mem_guard  # noqa: snapshots memory/, restores at exit

from driver import run_task

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []


def check(label, cond):
    results.append(bool(cond))
    print(f"  {PASS if cond else FAIL} {label}")


# ─── Fixtures: a coherent task + diff so the intent gate passes ──────────────

TASK = "add sale badge to product page"

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

# redirect() outside middleware.ts trips the nextjs/redirect gate → RETRY.
VIOLATING_DIFF = textwrap.dedent("""\
    diff --git a/app/products/[slug]/page.tsx b/app/products/[slug]/page.tsx
    +++ b/app/products/[slug]/page.tsx
    +  redirect('/dashboard')
""")

PASSING_TESTS = "=== BUILD ===\nCompiled successfully\n\n=== TYPE CHECK ===\nNo issues found\n"
FAILING_TESTS = "=== BUILD ===\nnpm ERR! Type error: x is not assignable\n"
REVIEW_PASS = "REVIEW RESULT: PASS\n\nCRITICAL:\n\nSHADOW GATE CHECK: clean\n"


class FakeModel:
    """Stands in for a real backend. Returns a queued diff per implement call,
    a fixed review/retro otherwise, and records which phases it was asked for."""

    def __init__(self, impl_queue):
        self.impl_queue = list(impl_queue)
        self.phases_called = []

    def __call__(self, system: str, user: str, phase: str) -> str:
        self.phases_called.append(phase)
        # The real driver passes a non-empty system prompt (the agent .md) every call.
        assert system, "driver must pass the agent system prompt"
        if phase == "implement":
            return self.impl_queue.pop(0) if self.impl_queue else CLEAN_DIFF
        if phase == "review":
            return REVIEW_PASS
        return "retro complete"


def test_clean_run_drives_all_phases():
    print("\n[clean run — model drives every phase to a finalized report]")
    model = FakeModel([CLEAN_DIFF])
    res = run_task(TASK, model=model, run_tests=lambda: PASSING_TESTS)
    check("run completed (no HALT)", res.completed)
    check("model was called for implement", "implement" in model.phases_called)
    check("model was called for review", "review" in model.phases_called)
    check("model was called for retro", "retro" in model.phases_called)
    check("an EvalReport was produced", res.report is not None)
    check("report scored > 0", res.report is not None and res.report.total > 0)


def test_gate_violation_retries_then_recovers():
    print("\n[gate violation — driver feeds a bad diff, recovers on the next]")
    model = FakeModel([VIOLATING_DIFF, CLEAN_DIFF])
    res = run_task(TASK, model=model, run_tests=lambda: PASSING_TESTS)
    check("run still completed after a retry", res.completed)
    check("a retry was actually used", res.retries_used >= 1)
    check("model was re-asked for implement (>=2 times)",
          model.phases_called.count("implement") >= 2)


def test_failing_tests_halt_at_verify():
    print("\n[real tests fail — SHA/verify gate HALTs the run]")
    model = FakeModel([CLEAN_DIFF])
    res = run_task(TASK, model=model, run_tests=lambda: FAILING_TESTS)
    check("run halted", not res.completed)
    check("halted at VERIFY", res.halted_phase == "VERIFY")
    check("no report when halted", res.report is None)
    check("review was NEVER reached", "review" not in model.phases_called)


def test_unfixable_violation_halts_implement():
    print("\n[every diff violates — driver HALTs at IMPLEMENT after MAX_RETRIES]")
    # Always return the violating diff; the pipeline HALTs itself at MAX_RETRIES.
    model = FakeModel([VIOLATING_DIFF] * 10)
    res = run_task(TASK, model=model, run_tests=lambda: PASSING_TESTS)
    check("run halted", not res.completed)
    check("halted at IMPLEMENT", res.halted_phase == "IMPLEMENT")
    check("verify/review never reached",
          "review" not in model.phases_called)


if __name__ == "__main__":
    print("=" * 60)
    print("DRIVER — host loop runs the pipeline with an (injected) model")
    print("=" * 60)
    test_clean_run_drives_all_phases()
    test_gate_violation_retries_then_recovers()
    test_failing_tests_halt_at_verify()
    test_unfixable_violation_halts_implement()
    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed" + ("  -- all clear" if passed == total else f"  ({total-passed} FAILED)"))
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
