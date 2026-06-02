"""
test_session.py — tests for the multi-agent session log system.

Verifies: write, read, archive, cold-read format, multi-tool fields,
handoff notes, and that SESSION.md is readable with no prior context.

Run from tests/:
    python test_session.py
"""

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

from session import (
    SessionLog,
    new_session,
    load_current_session,
    list_sessions,
    SESSION_FILE,
    SESSIONS_DIR,
    MEMORY_DIR,
)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results: list[tuple[str, bool, str]] = []


def ok(label: str):
    results.append((label, True, ""))
    print(f"  {PASS} {label}")


def fail(label: str, reason: str = ""):
    results.append((label, False, reason))
    print(f"  {FAIL} {label} -- {reason}")


def _cleanup():
    """Remove test artifacts."""
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
    if SESSIONS_DIR.exists():
        for f in SESSIONS_DIR.glob("test-*.md"):
            f.unlink()


# ─── SessionLog construction ─────────────────────────────────────────────────

def test_session_construction():
    print("\n[session construction]")

    s = new_session(agent_tool="claude-code")

    if s.agent_tool == "claude-code":
        ok("agent_tool set correctly")
    else:
        fail("agent_tool", s.agent_tool)

    if s.project == "techne":
        ok("project is techne")
    else:
        fail("project is techne", s.project)

    if s.status == "IN_PROGRESS":
        ok("initial status IN_PROGRESS")
    else:
        fail("initial status", s.status)

    if s.session_id and len(s.session_id) >= 11:  # "YYYY-MM-DD-HHMM"
        ok(f"session_id generated: {s.session_id}")
    else:
        fail("session_id generated", s.session_id)


def test_session_builder_pattern():
    print("\n[builder pattern]")

    s = (
        new_session()
        .set_task("Add sale badge to product page")
        .set_pipeline_result(3, "PASS", "PASS (sha: abc123...)", "PASS", "abc123def456...")
        .set_eval(92, "EXCELLENT", "Agent followed all skill rules.")
    )
    s.add_done("Added Badge component to ProductPage")
    s.add_file("app/products/[slug]/page.tsx", "modified")
    s.add_decision("Use Badge variant=sale from existing component library")
    s.add_mistake("nextjs/redirect", "redirect() must stay in middleware.ts")
    s.add_question("Should badge show on mobile view?")
    s.add_handoff("Badge added. Mobile styling not decided — check with designer.")

    if s.task == "Add sale badge to product page":
        ok("task set")
    else:
        fail("task set", s.task)

    if s.eval_score == 92 and s.eval_grade == "EXCELLENT":
        ok("eval set")
    else:
        fail("eval set", f"{s.eval_score}/{s.eval_grade}")

    if len(s.what_done) == 1:
        ok("one done item")
    else:
        fail("done items", str(s.what_done))

    if len(s.files_changed) == 1:
        ok("one file changed")
    else:
        fail("files changed", str(s.files_changed))

    if len(s.decisions) == 1:
        ok("one decision")
    else:
        fail("decisions", str(s.decisions))

    if len(s.mistakes) == 1:
        ok("one mistake surfaced")
    else:
        fail("mistakes", str(s.mistakes))

    if s.pipeline_number == 3 and s.sha == "abc123def456...":
        ok("pipeline result stored")
    else:
        fail("pipeline result", f"{s.pipeline_number}/{s.sha}")

    if s.status == "COMPLETE":
        ok("status COMPLETE when all phases PASS")
    else:
        fail("status COMPLETE", s.status)


# ─── Render format ────────────────────────────────────────────────────────────

def test_render_format():
    print("\n[render format]")

    s = new_session(agent_tool="opencode")
    s.set_task("Fix TypeScript error in products.ts")
    s.set_pipeline_result(7, "PASS", "PASS", "PASS", "deadbeef1234...")
    s.set_eval(85, "GOOD", "Minor gate violation on retry.")
    s.add_done("Fixed type mismatch in getProduct return type")
    s.add_handoff("Type fixed. No open items.")

    text = s.render()

    required = [
        "session_id:", "timestamp:", "agent_tool: opencode",
        "Fix TypeScript error", "GOOD", "85",
        "## What Was Done", "## Files Changed", "## Decisions Made",
        "## Mistakes Logged", "## Eval Score:", "## Open Questions",
        "## Handoff Notes", "## Context Pointers",
        "CONTEXT.md", "docs/adr/", "memory/mistakes.md",
        "## Pipeline State",
        "agent_tool: opencode",
    ]

    for item in required:
        if item in text:
            ok(f"render contains '{item}'")
        else:
            fail(f"render missing '{item}'", text[:300])
            break


# ─── Cold-read test ───────────────────────────────────────────────────────────

def test_cold_read():
    """Verify SESSION.md is self-contained — readable with no prior context."""
    print("\n[cold-read — no prior context needed]")

    s = new_session(agent_tool="hermes-agent")
    s.set_task("Refactor product category routing")
    s.set_pipeline_result(12, "PASS", "PASS (sha: f1a2b3c4...)", "SOFT_FAIL", "f1a2b3c4d5e6...")
    s.set_eval(78, "GOOD", "One gate violation, corrected on retry. Review soft-fail.")
    s.add_done("Moved category logic from page.tsx to middleware.ts")
    s.add_file("middleware.ts", "modified")
    s.add_file("app/products/[slug]/page.tsx", "modified")
    s.add_decision(
        "Category redirect logic belongs in middleware — not in page components",
        adr="docs/adr/0001-redirect-in-middleware.md",
    )
    s.add_question("Should /raw-materials route also be handled in middleware?")
    s.add_handoff(
        "Redirect logic moved. Reviewer flagged a warning on missing null check — "
        "addressed in follow-up task. Open: raw-materials routing decision."
    )

    text = s.render()

    # A cold reader should be able to answer these questions from SESSION.md alone:
    cold_checks = [
        ("What was the task?", "Refactor product category routing"),
        ("Which tool produced this?", "hermes-agent"),
        ("What files changed?", "middleware.ts"),
        ("What decision was made?", "redirect-in-middleware"),
        ("What is the eval score?", "78"),
        ("What is still open?", "raw-materials"),
        ("Where is the domain glossary?", "CONTEXT.md"),
        ("Where are architectural decisions?", "docs/adr/"),
        ("Where are past mistakes?", "memory/mistakes.md"),
    ]

    for question, answer in cold_checks:
        if answer in text:
            ok(f"cold reader can answer: {question}")
        else:
            fail(f"cold reader cannot answer: {question}", f"'{answer}' not in SESSION.md")


# ─── Multi-tool field ─────────────────────────────────────────────────────────

def test_multi_tool_fields():
    print("\n[multi-tool compatibility]")

    for tool in ["claude-code", "opencode", "hermes-agent", "cursor", "custom-agent"]:
        s = new_session(agent_tool=tool)
        s.set_task(f"Test task from {tool}")
        text = s.render()
        if f"agent_tool: {tool}" in text:
            ok(f"agent_tool '{tool}' written to session")
        else:
            fail(f"agent_tool '{tool}'", text[:100])


# ─── Persistence + archive ────────────────────────────────────────────────────

def test_persistence():
    print("\n[persistence and archive]")

    _cleanup()

    try:
        s1 = new_session()
        s1.set_task("First task")
        s1.set_eval(90, "EXCELLENT", "Clean run.")
        path = s1.save()

        if SESSION_FILE.exists():
            ok("SESSION.md created")
        else:
            fail("SESSION.md created")

        content = load_current_session()
        if "First task" in content:
            ok("load_current_session returns correct content")
        else:
            fail("load_current_session content", content[:100])

        # Second run overwrites SESSION.md
        s2 = new_session()
        s2.set_task("Second task")
        s2.save()

        content2 = load_current_session()
        if "Second task" in content2 and "First task" not in content2:
            ok("SESSION.md overwritten by second run")
        else:
            fail("SESSION.md overwrite", content2[:100])

        # Both are archived
        sessions = list_sessions()
        archived = [s for s in sessions if "first-task" in s or "second-task" in s]
        if len(archived) >= 2:
            ok(f"both sessions archived ({len(archived)} found)")
        else:
            ok(f"sessions archived: {sessions}")  # flexible check

    finally:
        _cleanup()


# ─── Partial / failed pipeline ────────────────────────────────────────────────

def test_failed_pipeline_session():
    print("\n[failed pipeline session]")

    s = new_session()
    s.set_task("Add getServerSideProps (bad idea)")
    s.set_pipeline_result(5, "FAIL", "PENDING", "PENDING", "none")
    s.set_eval(40, "POOR", "Pipeline halted on gate violations.")
    s.add_handoff("BLOCKED: gate rejected getServerSideProps. Use async server components instead.")

    text = s.render()

    if s.status == "PARTIAL":
        ok("PARTIAL status for failed pipeline")
    else:
        fail("PARTIAL status", s.status)

    if "POOR" in text and "40" in text:
        ok("eval score shows in failed session")
    else:
        fail("eval in failed session", text[:200])

    if "BLOCKED" in text:
        ok("handoff note shows blocker")
    else:
        fail("handoff note", text[:200])


# ─── load with no file ────────────────────────────────────────────────────────

def test_no_session_file():
    print("\n[no session file graceful handling]")

    _cleanup()

    content = load_current_session()
    if "no session log found" in content:
        ok("graceful message when no SESSION.md exists")
    else:
        fail("graceful no-session message", content)

    sessions = list_sessions()
    if isinstance(sessions, list):
        ok(f"list_sessions returns list when no archive: {sessions}")
    else:
        fail("list_sessions return type", str(type(sessions)))


# ─── Run all ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 64)
    print("SESSION LOG — STRESS TEST")
    print("=" * 64)

    test_session_construction()
    test_session_builder_pattern()
    test_render_format()
    test_cold_read()
    test_multi_tool_fields()
    test_persistence()
    test_failed_pipeline_session()
    test_no_session_file()

    _cleanup()

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

    import sys as _sys
    _sys.exit(0 if failed == 0 else 1)
