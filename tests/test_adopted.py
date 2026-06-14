"""
test_adopted.py — tests for adopted features from mattpocock + jtoemion repos.

Tests: skill router, structured mistakes, checkpoint enforcer.
Run from harness/:
    python test_adopted.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(TESTS_DIR)); import _mem_guard  # noqa: snapshots memory/, restores at exit

from router import route, get_always_loaded, route_with_explanation
from mistakes import log_mistake, check_relevant, count_active, mark_resolved, _parse_entries, MISTAKES_FILE, INSERT_MARKER
from checkpoint import (
    read_state, write_state, init_state, increment_pipeline_run,
    log_gate_pass, log_gate_fail, mark_verified, check_verification,
    get_summary, STATE_FILE,
)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results: list[tuple[str, bool, str]] = []


def ok(label: str):
    results.append((label, True, ""))
    print(f"  {PASS} {label}")


def fail(label: str, reason: str = ""):
    results.append((label, False, reason))
    print(f"  {FAIL} {label} — {reason}")


# ─── Skill Router ─────────────────────────────────────────────────────────────

def test_router():
    print("\n[skill router]")

    r = route("there's a bug, something is broken")
    if r and r["id"] == "diagnose":
        ok("bug report routes to diagnose")
    else:
        fail("bug report routes to diagnose", f"got {r}")

    r = route("let's write tests first using TDD")
    if r and r["id"] == "tdd":
        ok("TDD request routes to tdd")
    else:
        fail("TDD request routes to tdd", f"got {r}")

    r = route("stress-test this plan before we build it")
    if r and r["id"] == "grill":
        ok("plan stress-test routes to grill")
    else:
        fail("plan stress-test routes to grill", f"got {r}")

    r = route("update the middleware redirect logic")
    if r and r["id"] == "nextjs-rules":
        ok("Next.js task routes to nextjs-rules")
    else:
        fail("Next.js task routes to nextjs-rules", f"got {r}")

    r = route("fix the TypeScript type error in products.ts")
    if r and r["id"] == "typescript-rules":
        ok("TypeScript task routes to typescript-rules")
    else:
        fail("TypeScript task routes to typescript-rules", f"got {r}")

    r = route("make me a sandwich")
    if r is None:
        ok("irrelevant task returns None")
    else:
        fail("irrelevant task returns None", f"got {r}")

    always = get_always_loaded()
    if len(always) >= 2:
        ok(f"always_loaded has {len(always)} entries")
    else:
        fail("always_loaded has entries", f"got {always}")

    explanation = route_with_explanation("something is broken and failing")
    if "diagnose" in explanation.lower():
        ok("route_with_explanation mentions diagnose")
    else:
        fail("route_with_explanation mentions diagnose", explanation)


# ─── Structured Mistakes ──────────────────────────────────────────────────────

def test_mistakes():
    print("\n[structured mistakes]")

    # Save original and work on a temp copy
    original = MISTAKES_FILE.read_text(encoding="utf-8")

    try:
        # Reset to clean state
        MISTAKES_FILE.write_text(
            f"# Test mistakes\n\n{INSERT_MARKER}\n",
            encoding="utf-8",
        )

        # Log a mistake
        log_mistake(
            phase="IMPLEMENT",
            error="redirect() outside middleware.ts",
            cause="agent violated skill rule",
            lesson="pending retro",
            gate="nextjs/redirect",
        )
        ok("log_mistake writes without error")

        content = MISTAKES_FILE.read_text(encoding="utf-8")
        if "redirect()" in content and "ACTIVE" in content:
            ok("mistake entry has error + ACTIVE status")
        else:
            fail("mistake entry format", content[:200])

        # Count
        c = count_active()
        if c == 1:
            ok("count_active returns 1")
        else:
            fail("count_active returns 1", f"got {c}")

        # Check relevant
        relevant = check_relevant("redirect middleware")
        if len(relevant) == 1:
            ok("check_relevant finds matching entry")
        else:
            fail("check_relevant finds matching entry", f"got {len(relevant)}")

        irrelevant = check_relevant("database migration")
        if len(irrelevant) == 0:
            ok("check_relevant returns empty for unrelated task")
        else:
            fail("check_relevant returns empty for unrelated task", f"got {len(irrelevant)}")

        # Parse entries
        entries = _parse_entries(content)
        if len(entries) == 1 and entries[0]["status"] == "ACTIVE":
            ok("_parse_entries extracts structured fields")
        else:
            fail("_parse_entries extracts structured fields", str(entries))

        # Mark resolved
        date_str = entries[0]["date"]
        resolved = mark_resolved(date_str)
        if resolved:
            ok("mark_resolved changes ACTIVE to RESOLVED")
        else:
            fail("mark_resolved", "returned False")

        c2 = count_active()
        if c2 == 0:
            ok("count_active returns 0 after resolve")
        else:
            fail("count_active returns 0 after resolve", f"got {c2}")

        # Log multiple
        MISTAKES_FILE.write_text(
            f"# Test\n\n{INSERT_MARKER}\n",
            encoding="utf-8",
        )
        for i in range(3):
            log_mistake(
                phase="IMPLEMENT",
                error=f"violation #{i}",
                gate=f"gate_{i}",
            )
        if count_active() == 3:
            ok("3 sequential log_mistake calls produce 3 active entries")
        else:
            fail("3 sequential log_mistake calls", f"got {count_active()}")

    finally:
        MISTAKES_FILE.write_text(original, encoding="utf-8")


# ─── Checkpoint Enforcer ──────────────────────────────────────────────────────

def test_checkpoint():
    print("\n[checkpoint enforcer]")

    # Save original state
    original_state = None
    if STATE_FILE.exists():
        original_state = STATE_FILE.read_text(encoding="utf-8")

    try:
        # Init
        state = init_state()
        if state.get("session_id") and state.get("verification_logged") is False:
            ok("init_state creates session with verification_logged=False")
        else:
            fail("init_state", str(state))

        # Increment run
        run_num = increment_pipeline_run()
        if run_num == 1:
            ok("increment_pipeline_run returns 1")
        else:
            fail("increment_pipeline_run returns 1", f"got {run_num}")

        # Verification starts False
        if not check_verification():
            ok("check_verification is False before marking")
        else:
            fail("check_verification should be False initially")

        # Log gate pass/fail
        log_gate_pass("all_gates")
        log_gate_fail("nextjs/redirect", "redirect outside middleware")
        state = read_state()
        if len(state.get("gates_passed", [])) == 1 and len(state.get("gates_failed", [])) == 1:
            ok("gate pass/fail logged correctly")
        else:
            fail("gate pass/fail logging", str(state))

        # Mark verified
        mark_verified("abc123def456")
        if check_verification():
            ok("check_verification is True after mark_verified")
        else:
            fail("check_verification should be True after mark_verified")

        state = read_state()
        if state.get("last_verification_sha") == "abc123def456":
            ok("SHA stored in state")
        else:
            fail("SHA stored in state", state.get("last_verification_sha"))

        # New pipeline run resets verification
        increment_pipeline_run()
        if not check_verification():
            ok("new pipeline run resets verification_logged to False")
        else:
            fail("verification should reset on new run")

        # Summary
        summary = get_summary()
        if "Pipeline runs:" in summary and "Verified:" in summary:
            ok("get_summary returns formatted status")
        else:
            fail("get_summary format", summary)

    finally:
        if original_state:
            STATE_FILE.write_text(original_state, encoding="utf-8")
        elif STATE_FILE.exists():
            STATE_FILE.unlink()


# ─── Skill file existence ─────────────────────────────────────────────────────

def test_skill_files_exist():
    print("\n[adopted skill files]")

    expected = ["tdd.md", "diagnose.md", "grill.md", "nextjs.md", "typescript.md", "implementer.md", "evaluation.md"]
    for name in expected:
        path = ROOT / "skills" / name
        if path.exists() and len(path.read_text(encoding="utf-8")) > 100:
            ok(f"{name} exists and has content")
        else:
            fail(f"{name} exists and has content")

    # skill-router.yaml lives in harness/
    router_path = ROOT / "harness" / "skill-router.yaml"
    if router_path.exists():
        ok("skill-router.yaml exists")
    else:
        fail("skill-router.yaml exists")


# ─── Run all ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("ADOPTED FEATURES — STRESS TEST")
    print("=" * 60)

    test_router()
    test_mistakes()
    test_checkpoint()
    test_skill_files_exist()

    total = len(results)
    passed = sum(1 for _, ok_flag, _ in results if ok_flag)
    failed = total - passed

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
        print("\nFailed tests:")
        for label, ok_flag, reason in results:
            if not ok_flag:
                print(f"  {FAIL} {label}: {reason}")
    else:
        print("  -- all clear")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)
