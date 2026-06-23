"""
test_bake_pipeline.py — end-to-end "bake" of the RL pipeline.

Drives OrchestratorLoop through scenarios that each exercise one layer of the
original pipeline's deterministic enforcement, proving it is wired into the RL
loop (not the old hardcoded gate_pass=True). Covered layers:

  1. GateRegistry (+plugins)  — run_gates at IMPLEMENT
  2. measurements (focus/scope)— measure_scope at IMPLEMENT
  3. intent L1/L2             — measure_scope (verdict/layer/l1 computed; the
                                 gate blocks at confidence >= 0.7)
  4. SHA gate                 — verify_tests at VERIFY
  5. reward signal            — reward_log composite, win AND loss

Run as a report:  python tests/test_bake_pipeline.py
Run as tests:     pytest tests/test_bake_pipeline.py
"""
import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent.parent / "harness"
sys.path.insert(0, str(HARNESS))

from enforcement import run_gates, measure_scope, verify_tests  # noqa: E402
from task_db import TaskDB  # noqa: E402
from reward_log import RewardLog  # noqa: E402
from orchestrator_loop import OrchestratorLoop, LoopAction  # noqa: E402
from checkpoint import mark_honcho_concluded, clear_honcho_flag  # noqa: E402

# ── Fixtures: diffs and test output ──────────────────────────────────────────
CLEAN = (
    "--- a/rate_limiter.py\n+++ b/rate_limiter.py\n@@ -1 +1,2 @@\n"
    "-old\n+def rate_limiter(rate):\n+    return rate\n"
)
CONSOLE_LOG = (
    "--- a/rate_limiter.py\n+++ b/rate_limiter.py\n@@ -1 +1,2 @@\n"
    "-old\n+console.log('rate limiter debug')\n"
)
TS_IGNORE = (
    "--- a/rate_limiter.ts\n+++ b/rate_limiter.ts\n@@ -1 +1,2 @@\n"
    "-old\n+// @ts-ignore\n+const x: any = rate\n"
)
UNRELATED = (  # task is about rate limiting; this touches billing
    "--- a/billing/invoice.py\n+++ b/billing/invoice.py\n@@ -1 +1,2 @@\n"
    "-old\n+def total(): return 1\n"
)
GOOD_TESTS = (
    "============================= test session starts ===========================\n"
    "collected 12 items\n\n"
    "tests/test_rate_limiter.py ............                                [100%]\n\n"
    "============================== 12 passed in 0.04s ===========================\n"
)


@pytest.fixture
def loop(tmp_path):
    db = TaskDB(str(tmp_path / "tasks.db"))
    rewards = RewardLog(str(tmp_path / "rewards.db"))
    lp = OrchestratorLoop(db, reward_log=rewards)
    yield lp
    lp.db.close()
    lp.reward_log.close()


@pytest.fixture(autouse=True)
def honcho_fixture():
    """P3 fix: mark Honcho concluded before every test that drives RECALL.
    clear_honcho_flag() runs after each test to prevent cross-test leakage."""
    mark_honcho_concluded("p3-fixture")
    yield
    clear_honcho_flag()


def _drive_to_done(loop, diff, test_output, *, task_type="api", variant="v1"):
    """Run a task all the way through the loop. Returns the final outcome."""
    t = loop.db.create_task("add rate_limiter", discipline="implement")
    loop.set_task_type(t.id, task_type)
    loop.set_variant(t.id, variant)
    # RECALL must come first (full pipeline); honcho_fixture handles mark_honcho_concluded
    recall = loop.submit(t.id, "RECALL",
                         "HONCHO_CONTEXT: prior work on rate limiting\n"
                         "WORKSHOP_CONTEXT: workshop retrieval packet")
    assert recall.action == LoopAction.RUN_PHASE, (
        f"_drive_to_done: RECALL failed → {recall.action}: {recall.message}"
    )
    assert recall.phase == "IMPLEMENT"
    impl = loop.submit(t.id, "IMPLEMENT", diff)
    assert impl.action == LoopAction.RUN_PHASE, (
        f"_drive_to_done: IMPLEMENT failed → {impl.action}: {impl.message}"
    )
    # CONTEXT_GUARD requires CONCLUDE PUNCH LIST format
    loop.submit(t.id, "CONTEXT_GUARD",
                "All scoped clean.\n\n"
                "CONCLUDE PUNCH LIST\n"
                "DOCS: NOT_NEEDED\n"
                "CONTEXT: NOT_NEEDED\n"
                "HONCHO: saved pattern")
    loop.submit(t.id, "CRITIQUE", "No critical findings")
    loop.submit(t.id, "REVIEW", "REVIEW RESULT: PASS")
    verify = loop.submit(t.id, "VERIFY", test_output)
    # VERIFY → EVAL (score) → RETRO → CONCLUDE → REFRESH_CONTEXT → DONE
    if verify.action == LoopAction.RUN_PHASE and verify.phase == "EVAL":
        loop.submit(t.id, "EVAL", "")           # deterministic score
        # RETRO gate: must be >= 100 chars AND reference at least one completed phase
        retro_text = (
            "Retro review of this implementation run.\n"
            "IMPLEMENT: passed gates cleanly with CLEAN diff.\n"
            "CONTEXT_GUARD: all scoped clean, punch list closed.\n"
            "CRITIQUE: no critical findings raised.\n"
            "REVIEW: passed with no reservations.\n"
            "VERIFY: tests passed with good output.\n"
            "No recurring issues observed — clean run overall."
        )
        loop.submit(t.id, "RETRO", retro_text)
        # CONCLUDE gate: requires HONCHO: / DOCS: / CONTEXT: structured proof
        # HONCHO: line must match the conclusion-id from mark_honcho_concluded()
        mark_honcho_concluded("test-fixture")
        # Patch _get_uncommitted_context_files to return [] so the CONCLUDE gate
        # doesn't see dirty .techne/context files from the techne repo itself
        original_get_uncommitted = loop._get_uncommitted_context_files
        loop._get_uncommitted_context_files = lambda touched_files=None: []
        try:
            conclude_proof = (
                "HONCHO: honcho://conclusion/test-fixture — verified bake test\n"
                "DOCS: NOT_NEEDED: no docs changes\n"
                "CONTEXT: NOT_NEEDED: no context changes"
            )
            outcome = loop.submit(t.id, "CONCLUDE", conclude_proof)
        finally:
            loop._get_uncommitted_context_files = original_get_uncommitted
        return t, loop.submit(t.id, "REFRESH_CONTEXT", "context refreshed")
    return t, verify  # VERIFY blocked/failed — return as-is


# ── Layer 1: GateRegistry ────────────────────────────────────────────────────

def test_bake_gate_registry_blocks_console_log(loop):
    t = loop.db.create_task("add a limiter", discipline="implement")
    loop.submit(t.id, "RECALL",
                "HONCHO_CONTEXT: prior work\nWORKSHOP_CONTEXT: workshop retrieval packet")
    outcome = loop.submit(t.id, "IMPLEMENT", CONSOLE_LOG)
    assert outcome.action == LoopAction.RETRY
    assert loop._gate_pass.get(t.id) is False


def test_bake_gate_registry_blocks_ts_ignore(loop):
    t = loop.db.create_task("add a limiter", discipline="implement")
    loop.submit(t.id, "RECALL",
                "HONCHO_CONTEXT: prior work\nWORKSHOP_CONTEXT: workshop retrieval packet")
    outcome = loop.submit(t.id, "IMPLEMENT", TS_IGNORE)
    assert outcome.action == LoopAction.RETRY
    assert loop._gate_pass.get(t.id) is False


# ── Layer 2: measurements (focus / scope-creep) ──────────────────────────────

def test_bake_scope_measurement_flags_creep(loop):
    # Gates pass (no console.log etc.) but the diff is unrelated to the task,
    # so scope-creep is flagged: the run advances but scope_clean is False.
    t = loop.db.create_task("add rate limiter to the api", discipline="implement")
    loop.submit(t.id, "RECALL",
                "HONCHO_CONTEXT: prior work\nWORKSHOP_CONTEXT: workshop retrieval packet")
    outcome = loop.submit(t.id, "IMPLEMENT", UNRELATED)
    assert outcome.action == LoopAction.RUN_PHASE   # creep does not hard-block
    assert loop._gate_pass.get(t.id) is True
    assert loop._scope_clean.get(t.id) is False         # measurement caught it


# ── Layer 3: intent L1/L2 ────────────────────────────────────────────────────

def test_bake_intent_layers_are_computed():
    # L1 syntactic + L2 structural both run and populate the intent dict.
    scope = measure_scope("add rate_limiter", CLEAN)
    assert "l1_score" in scope.intent
    assert scope.intent.get("layer") in ("syntactic", "structural", "semantic")
    assert scope.intent.get("verdict") in ("MATCH", "PARTIAL", "MISMATCH")


def test_bake_intent_gate_fires_on_high_confidence_mismatch():
    # A host-supplied L3 verdict of MISMATCH at >=0.7 makes the intent gate fire.
    verdict = {"verdict": "MISMATCH", "confidence": 0.95, "reason": "diff unrelated",
               "layer": "semantic", "deductions": ["builds X, task asked for Y"]}
    scope = measure_scope("add rate_limiter", UNRELATED, semantic_verdict=verdict)
    assert scope.intent_mismatch is True
    assert scope.scope_clean is False


def test_bake_intent_mismatch_blocks_loop_at_implement(loop):
    # When intent mismatches hard, the loop retries IMPLEMENT (does not advance).
    # We force it via a stubbed measure_scope to keep the test deterministic.
    # Patch _recall_implement.measure_scope (where it's actually called) so the
    # mock is seen by the handler. phase_mode="micro" avoids the lane-switch path.
    from unittest.mock import patch
    from enforcement import ScopeResult

    mocked = lambda task, diff, **k: ScopeResult(
        diff_focused=True, scope_creep=False, intent={"verdict": "MISMATCH"},
        intent_mismatch=True, violation="INTENT GATE: MISMATCH",
    )
    # Diff large enough (many lines) to avoid lane-switch on full-mode task,
    # while still passing all hard gates (no console.log / ts-ignore).
    large_diff = (
        "--- a/rate_limiter.py\n+++ b/rate_limiter.py\n@@ -1 +1,15 @@\n"
        "-old\n"
        "+def rate_limiter(rate, window=60):\n"
        "+    \"\"\"Token-bucket rate limiter.\"\"\"\n"
        "+    tokens = []\n"
        "+    def check(token):\n"
        "+        now = time.time()\n"
        "+        tokens[:] = [t for t in tokens if now - t < window]\n"
        "+        if len(tokens) >= rate:\n"
        "+            return False\n"
        "+        tokens.append(now)\n"
        "+        return True\n"
        "+    return check\n"
        "+\n"
        "+def reset(): pass\n"
        "+def status(): return 0\n"
    )
    with patch("_recall_implement.measure_scope", mocked):
        t = loop.db.create_task("add rate_limiter", discipline="implement")
        loop.submit(t.id, "RECALL",
                    "HONCHO_CONTEXT: prior work\nWORKSHOP_CONTEXT: workshop retrieval packet")
        outcome = loop.submit(t.id, "IMPLEMENT", large_diff)
        assert outcome.action == LoopAction.RETRY
        assert loop._scope_clean.get(t.id) is False


# ── Layer 4: SHA gate ────────────────────────────────────────────────────────

def test_bake_sha_gate_blocks_faked_output(loop):
    t = loop.db.create_task("add rate_limiter", discipline="implement")
    loop.submit(t.id, "RECALL",
                "HONCHO_CONTEXT: prior work\nWORKSHOP_CONTEXT: workshop retrieval packet")
    loop.submit(t.id, "IMPLEMENT", CLEAN)
    loop.submit(t.id, "CONTEXT_GUARD", "All scoped clean.\n\n"
                "CONCLUDE PUNCH LIST\n"
                "DOCS: NOT_NEEDED\n"
                "CONTEXT: NOT_NEEDED\n"
                "HONCHO: saved pattern")
    loop.submit(t.id, "CRITIQUE", "No critical findings")
    loop.submit(t.id, "REVIEW", "REVIEW RESULT: PASS")
    outcome = loop.submit(t.id, "VERIFY", "tests pass")  # too short / faked
    assert outcome.action == LoopAction.BLOCK_HITL
    assert loop._test_pass.get(t.id) is False


def test_bake_sha_gate_passes_real_output(loop):
    t, outcome = _drive_to_done(loop, CLEAN, GOOD_TESTS)
    assert outcome.action == LoopAction.DONE
    assert loop._test_pass.get(t.id) is True


# ── Layer 5: reward signal (win vs loss) ─────────────────────────────────────

def test_bake_win_and_loss_separate_in_reward_log(loop):
    # Win
    _drive_to_done(loop, CLEAN, GOOD_TESTS, variant="v_win")
    # Loss: exhaust retries on a gate violation -> escalation records a loss
    t2 = loop.db.create_task("add a limiter", discipline="implement")
    loop.set_task_type(t2.id, "api")
    loop.set_variant(t2.id, "v_lose")
    loop.submit(t2.id, "RECALL",
                "HONCHO_CONTEXT: prior work\nWORKSHOP_CONTEXT: workshop retrieval packet")
    for _ in range(5):
        last = loop.submit(t2.id, "IMPLEMENT", CONSOLE_LOG)
    assert last.action == LoopAction.BLOCK_HITL

    scores = {v["prompt_variant"]: v for v in loop.reward_log.variant_scores("api")}
    assert scores["v_win"]["avg_score"] > scores["v_lose"]["avg_score"]
    assert scores["v_win"]["gate_passes"] == 1
    assert scores["v_lose"]["gate_passes"] == 0


# ── Layer 6: EVAL phase (original 100-point deterministic eval) ──────────────

def test_bake_eval_phase_runs_and_scores(loop):
    t, outcome = _drive_to_done(loop, CLEAN, GOOD_TESTS)
    assert outcome.action == LoopAction.DONE
    report = loop.get_eval(t.id)
    assert report is not None
    assert 0 <= report.total <= 100
    assert set(report.scores) == {
        "Gate Compliance", "Verification Integrity",
        "Process Discipline", "Review Quality", "Retro Value",
    }


def test_bake_eval_phase_recorded_in_history(loop):
    t, _ = _drive_to_done(loop, CLEAN, GOOD_TESTS)
    actions = [e.action for e in loop.db.get_task_history(t.id)]
    # The EVAL phase sits between VERIFY and REFRESH_CONTEXT in the trail.
    # DONE is never recorded in history (orchestrator_loop never calls
    # mark_complete("DONE") — the terminal state is derived, not logged).
    assert "EVAL" in actions
    assert actions.index("VERIFY") < actions.index("EVAL")
    assert actions.index("EVAL") < actions.index("REFRESH_CONTEXT")


def test_bake_eval_clean_run_scores_full(loop):
    t, _ = _drive_to_done(loop, CLEAN, GOOD_TESTS)
    assert loop.get_eval(t.id).total == 100


def test_bake_eval_reflects_gate_violation(loop):
    # A gate violation corrected on retry must cost Gate Compliance points.
    t = loop.db.create_task("add rate_limiter", discipline="implement")
    loop.submit(t.id, "RECALL",
                "HONCHO_CONTEXT: prior work\nWORKSHOP_CONTEXT: workshop retrieval packet")
    # First attempt: violation → retry
    assert loop.submit(t.id, "IMPLEMENT", CONSOLE_LOG).action == LoopAction.RETRY
    # Second attempt: clean → advances
    loop.submit(t.id, "IMPLEMENT", CLEAN)
    loop.submit(t.id, "CONTEXT_GUARD",
                "All scoped clean.\n\n"
                "CONCLUDE PUNCH LIST\n"
                "DOCS: NOT_NEEDED\n"
                "CONTEXT: NOT_NEEDED\n"
                "HONCHO: saved pattern")
    loop.submit(t.id, "CRITIQUE", "No critical findings")
    loop.submit(t.id, "REVIEW", "REVIEW RESULT: PASS")
    loop.submit(t.id, "VERIFY", GOOD_TESTS)
    loop.submit(t.id, "EVAL", "")  # deterministic score runs here now
    report = loop.get_eval(t.id)
    assert report.scores["Gate Compliance"][0] < 20     # not a perfect gate run
    assert report.total < 100


def test_bake_eval_reflects_scope_creep(loop):
    t, _ = _drive_to_done(loop, UNRELATED, GOOD_TESTS, task_type="api")
    report = loop.get_eval(t.id)
    assert report.scores["Process Discipline"][0] < 20   # scope creep detected


# ── Bake report (human-readable) ─────────────────────────────────────────────

def _bake_report():
    import tempfile
    d = Path(tempfile.mkdtemp())
    db = TaskDB(str(d / "t.db"))
    loop = OrchestratorLoop(db, reward_log=RewardLog(str(d / "r.db")))

    print("=" * 64)
    print("TECHNE RL PIPELINE — BAKE REPORT")
    print("=" * 64)

    # Layer 1: GateRegistry
    g_clean = run_gates(CLEAN).passed
    g_bad = run_gates(CONSOLE_LOG)
    print(f"[1] GateRegistry   clean={g_clean}  console.log->blocked={not g_bad.passed} ({g_bad.gate_name})")

    # Layer 2 + 3: measurements + intent
    s = measure_scope("add rate_limiter", UNRELATED)
    print(f"[2] Measurements   focused={s.diff_focused} scope_creep={s.scope_creep} scope_clean={s.scope_clean}")
    print(f"[3] Intent L1/L2   l1_score={s.intent.get('l1_score')} layer={s.intent.get('layer')} verdict={s.intent.get('verdict')}")

    # Layer 4: SHA gate
    faked = verify_tests("tests pass", memory_dir=d).passed
    real = verify_tests(GOOD_TESTS, memory_dir=d).passed
    print(f"[4] SHA gate       faked->pass={faked}  real->pass={real}")

    # Layer 5: reward signal through the live loop
    mark_honcho_concluded("bake-report")
    t = loop.db.create_task("add rate_limiter", discipline="implement")
    loop.set_task_type(t.id, "api"); loop.set_variant(t.id, "v_win")
    loop.submit(t.id, "RECALL",
                "HONCHO_CONTEXT: prior work\nWORKSHOP_CONTEXT: workshop retrieval packet")
    loop.submit(t.id, "IMPLEMENT", CLEAN)
    loop.submit(t.id, "CONTEXT_GUARD", """
# Context audit: change is scoped
## CONCLUDE PUNCH LIST
DOCS: NOT_NEEDED
CONTEXT: NOT_NEEDED
HONCHO: NOT_NEEDED
""")
    loop.submit(t.id, "CRITIQUE", "No critical findings"); loop.submit(t.id, "REVIEW", "REVIEW RESULT: PASS")
    loop.submit(t.id, "VERIFY", GOOD_TESTS)
    t2 = loop.db.create_task("add a limiter", discipline="implement")
    loop.set_task_type(t2.id, "api"); loop.set_variant(t2.id, "v_lose")
    loop.submit(t2.id, "RECALL",
                "HONCHO_CONTEXT: prior work\nWORKSHOP_CONTEXT: workshop retrieval packet")
    for _ in range(5):
        loop.submit(t2.id, "IMPLEMENT", CONSOLE_LOG)
    print("[5] Reward signal  (real gate/SHA/scope -> composite):")
    for v in loop.reward_log.variant_scores("api"):
        print(f"      {v['prompt_variant']:7} score={v['avg_score']:.3f} "
              f"gate_passes={v['gate_passes']} test_passes={v['test_passes']}")

    # Layer 6: EVAL phase — the original 100-point deterministic eval
    rep = loop.get_eval(t.id)
    print(f"[6] EVAL phase     {rep.total}/100 ({rep.grade}) — original 100-pt eval, now a phase")
    for dim, (sc, _r) in rep.scores.items():
        print(f"      {dim:24} {sc}/20")

    print("=" * 64)
    db.close()


if __name__ == "__main__":
    import os
    os.environ.setdefault("PYTHONUTF8", "1")
    _bake_report()
