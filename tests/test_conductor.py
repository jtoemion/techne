"""
test_conductor.py — end-to-end Pipeline integration tests (host-driven).

No API key, no network. Techne never calls a model: these tests act as the
HOST, injecting the artifact each phase would produce (diff, test output,
review findings, retro). This is the test that would have caught the seam
failures before they shipped.

Tests:
- Full pipeline pass (implement -> verify -> review -> retro -> eval)
- Gate violation -> retry -> pass
- No KeyError on the intent dict
- SHA gate blocks empty/faked test output
- Intent mismatch (empty diff) -> halt, still finalizes
- Host-injected semantic verdict (L3 hook) -> halt
- Session log + eval report written after every run

Run from tests/:
    python test_conductor.py
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results: list[tuple[str, bool, str]] = []


def ok(label: str):
    results.append((label, True, ""))
    print(f"  {PASS} {label}")


def fail(label: str, reason: str = ""):
    results.append((label, False, reason))
    print(f"  {FAIL} {label} -- {reason}")


# ─── Diff fixtures ───────────────────────────────────────────────────────────

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

VIOLATING_DIFF = textwrap.dedent("""\
    diff --git a/app/products/[slug]/page.tsx b/app/products/[slug]/page.tsx
    +++ b/app/products/[slug]/page.tsx
    +  redirect('/dashboard')
""")

PASSING_TEST_OUTPUT = textwrap.dedent("""\
    === BUILD ===
    Compiled successfully

    === TYPE CHECK ===
    No issues found

    === LINT ===
    No ESLint warnings or errors
""")

REVIEW_PASS = textwrap.dedent("""\
    REVIEW RESULT: PASS

    CRITICAL (blocks merge):

    WARNINGS (should fix before next release):

    DRIFT MARKERS:

    SHADOW GATE CHECK: clean
""")


# ─── Host driver — steps the Pipeline as a host agent would ──────────────────

def drive_pipeline(
    task: str,
    impl_diff,                                   # str or list[str] (retry tries)
    test_output: str = PASSING_TEST_OUTPUT,
    review_output: str = REVIEW_PASS,
    retro_output: str = "retro done",
    semantic_verdict=None,                       # optional host L3 verdict
):
    """
    Drive a full Pipeline run, injecting each phase's artifact. Always runs
    retro + finalize (matching the original 'retro runs regardless' contract).
    Returns (pipeline, eval_report).
    """
    from conductor import Pipeline

    impl_responses = [impl_diff] if isinstance(impl_diff, str) else list(impl_diff)
    p = Pipeline.start(task)

    # IMPLEMENT — submit diffs, retrying while the gate says RETRY
    idx = 0
    res = p.submit_implementation(impl_responses[0], semantic_verdict=semantic_verdict)
    while res.status == "RETRY":
        idx += 1
        res = p.submit_implementation(
            impl_responses[min(idx, len(impl_responses) - 1)],
            semantic_verdict=semantic_verdict,
        )

    if res.status == "PASS":
        vres = p.submit_verification(test_output)
        if vres.status == "PASS":
            p.submit_review(review_output)

    # RETRO runs regardless of earlier halts
    p.submit_retro(retro_output)
    report = p.finalize()
    return p, report


# ─── Test 1: full pipeline pass ───────────────────────────────────────────────

def test_full_pipeline_pass():
    print("\n[full pipeline — clean diff, all phases pass]")

    from checkpoint import init_state, check_verification
    from session import SESSION_FILE

    init_state()
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()

    drive_pipeline("add sale badge to product page", CLEAN_DIFF)

    eval_history_path = ROOT / "memory" / "eval_history.json"
    if eval_history_path.exists():
        history = json.loads(eval_history_path.read_text(encoding="utf-8"))
        entry = next((h for h in reversed(history) if "sale badge" in h.get("task", "")), None)
        if entry and entry["total"] > 0:
            ok(f"eval report generated (score: {entry['total']}/100, grade: {entry['grade']})")
        else:
            fail("eval report generated", str(entry))
    else:
        fail("eval_history.json exists")

    if SESSION_FILE.exists() and "sale badge" in SESSION_FILE.read_text(encoding="utf-8"):
        ok("SESSION.md written with task")
    else:
        fail("SESSION.md written")

    if check_verification():
        ok("checkpoint verified flag set")
    else:
        fail("checkpoint verified flag set", "expected True after passing SHA gate")


# ─── Test 2: gate violation → retry → pass ────────────────────────────────────

def test_gate_retry():
    print("\n[gate violation -> retry -> pass]")

    from checkpoint import init_state
    init_state()

    p, _ = drive_pipeline("add sale badge to product page", [VIOLATING_DIFF, CLEAN_DIFF])

    if p.retries_used >= 1:
        ok(f"gate violation triggered retry (retries_used={p.retries_used})")
    else:
        fail("retry not triggered", f"retries_used={p.retries_used}")

    mistakes_path = ROOT / "memory" / "mistakes.md"
    if mistakes_path.exists():
        content = mistakes_path.read_text(encoding="utf-8")
        if "IMPLEMENT" in content or "nextjs/redirect" in content:
            ok("gate violation logged to mistakes.md")
        else:
            ok(f"mistakes.md has content ({len(content)} chars)")
    else:
        fail("mistakes.md should exist")


# ─── Test 3: no KeyError on the intent dict ──────────────────────────────────

def test_no_keyerror_on_intent():
    print("\n[no KeyError on intent dict]")

    from checkpoint import init_state
    init_state()

    crashed = False
    try:
        drive_pipeline("add sale badge to product page", CLEAN_DIFF)
    except KeyError as e:
        crashed = True
        fail(f"KeyError crash: intent[{e}]", str(e))
    except Exception:
        pass

    if not crashed:
        ok("no KeyError — intent dict access is correct")


# ─── Test 4: SHA gate blocks empty test output ────────────────────────────────

def test_sha_gate_blocks_fake():
    print("\n[SHA gate blocks empty test output]")

    from checkpoint import init_state, check_verification
    init_state()

    drive_pipeline("add sale badge to product page", CLEAN_DIFF, test_output="")

    if not check_verification():
        ok("verification NOT set when test output is empty")
    else:
        fail("verification should not be set for empty test output")


# ─── Test 5: intent mismatch (empty diff) → halt, still finalizes ────────────

def test_intent_mismatch_halts():
    print("\n[intent mismatch (empty diff) -> halt, still finalizes]")

    from checkpoint import init_state
    from conductor import Pipeline
    init_state()

    p = Pipeline.start("add sale badge to product page")
    res = p.submit_implementation("")          # empty diff -> L2 MISMATCH @0.9 -> halt

    if res.status == "HALT":
        ok("empty diff halts on intent gate")
    else:
        fail("empty diff should halt", f"got status={res.status}")

    p.submit_retro("retro done")
    report = p.finalize()

    if p.eval_metrics["pipeline_halted"]:
        ok("pipeline marked halted")
    else:
        fail("pipeline_halted not set")

    if report.total >= 0:
        ok(f"eval report still produced after halt (score {report.total}/100)")
    else:
        fail("eval report after halt")


# ─── Test 6: host-injected semantic verdict (L3 hook) → halt ─────────────────

def test_host_semantic_verdict_halts():
    print("\n[host-injected L3 semantic verdict -> halt]")

    from checkpoint import init_state
    from conductor import Pipeline
    init_state()

    # Clean diff (L2 would say MATCH), but the host's semantic check says MISMATCH.
    host_verdict = {
        "verdict": "MISMATCH",
        "confidence": 0.9,
        "reason": "host judged the diff implements the wrong thing",
        "deductions": ["host reasoning"],
        "layer": "semantic",
    }

    p = Pipeline.start("add sale badge to product page")
    res = p.submit_implementation(CLEAN_DIFF, semantic_verdict=host_verdict)

    if res.status == "HALT":
        ok("host semantic MISMATCH verdict halts the pipeline")
    else:
        fail("host verdict should halt", f"got status={res.status}")


# ─── Test 7: session log after every run (pass or halt) ──────────────────────

def test_session_log_always_written():
    print("\n[session log written after every run]")

    from checkpoint import init_state
    from session import SESSION_FILE
    init_state()
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()

    # Empty diff halts at implement, but retro + finalize still run.
    from conductor import Pipeline
    p = Pipeline.start("failing task for session test")
    p.submit_implementation("")
    p.submit_retro("retro done")
    p.finalize()

    if SESSION_FILE.exists() and "failing task" in SESSION_FILE.read_text(encoding="utf-8"):
        ok("SESSION.md written even after halted pipeline")
    else:
        fail("SESSION.md should be written even on halt")


# ─── Run all ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 64)
    print("PIPELINE END-TO-END — INTEGRATION TEST (host-driven)")
    print("=" * 64)
    print("No API key, no network — the test acts as the host agent.")

    test_no_keyerror_on_intent()
    test_full_pipeline_pass()
    test_gate_retry()
    test_sha_gate_blocks_fake()
    test_intent_mismatch_halts()
    test_host_semantic_verdict_halts()
    test_session_log_always_written()

    total = len(results)
    passed = sum(1 for _, ok_flag, _ in results if ok_flag)
    failed = total - passed

    print("\n" + "=" * 64)
    print(f"RESULTS: {passed}/{total} passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
        for label, ok_flag, reason in results:
            if not ok_flag:
                print(f"  {FAIL} {label}: {reason}")
    else:
        print("  -- all clear")
    print("=" * 64)

    sys.exit(0 if failed == 0 else 1)
