"""
test_context_amortization.py — deterministic checks for mandatory context preflight.
Run:
    python -X utf8 tests/test_context_amortization.py
"""
import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

from context_preflight import (
    extract_changed_files_from_report,
    format_preflight_prompt,
    select_context_pack,
)
from orchestrator_loop import LoopAction, OrchestratorLoop
from router import route
from task_db import TaskDB

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results: list[tuple[str, bool, str]] = []


def expect_pass(label: str, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
        results.append((label, True, ""))
        print(f"  {PASS} {label}")
    except Exception as e:
        results.append((label, False, str(e)))
        print(f"  {FAIL} {label}\n       raised unexpectedly: {e}")


def expect_true(label: str, value: bool):
    if value:
        results.append((label, True, ""))
        print(f"  {PASS} {label}")
    else:
        results.append((label, False, "expected True"))
        print(f"  {FAIL} {label}")


def test_skill_files_are_compact():
    print("\n[skill files]")
    skill = ROOT / "skills" / "context-amortization.md"
    agent = ROOT / "agents" / "context-preflight.md"
    expect_true("context-amortization skill exists", skill.exists())
    expect_true("context-preflight agent exists", agent.exists())
    expect_true("context-amortization skill <= 100 lines", len(skill.read_text(encoding="utf-8").splitlines()) <= 100)
    expect_true("context-preflight agent <= 120 lines", len(agent.read_text(encoding="utf-8").splitlines()) <= 120)


def test_router_wires_context_skill():
    print("\n[router]")
    result = route("make agents stop rereading the whole project")
    expect_true("context task routes to context-amortization", result and result["id"] == "techne/context-amortization")

    router_text = (ROOT / "harness" / "skill-router.yaml").read_text(encoding="utf-8")
    expect_true("context skill is always loaded", '"skills/context-amortization.md"' in router_text)


def test_context_pack_selection():
    print("\n[context pack selection]")
    expect_true("auth task selects auth pack", "auth" in select_context_pack("refresh auth session", "JWT token login"))
    expect_true("Techne harness task selects techne pack", "techne" in select_context_pack("update orchestrator loop", "harness router gate"))
    expect_true("database task selects database pack", "database" in select_context_pack("add migration", "schema sqlite"))


def test_preflight_prompt_is_mandatory():
    print("\n[preflight prompt]")
    prompt = format_preflight_prompt(
        task_id="t1",
        title="Add context preflight to Techne",
        description="Make context packs mandatory before implementation",
        discipline="techne",
        tags=["context", "harness"],
    )
    expect_true("prompt contains mandatory marker", "CONTEXT_PREFLIGHT (mandatory)" in prompt)
    expect_true("prompt selects techne pack", "SELECTED_PACKS: techne.md" in prompt)
    expect_true("prompt requires context_hash refresh", "context_hash.txt" in prompt)
    expect_true("prompt names read budget", "READ ORDER FOR NEXT PHASE" in prompt)


def test_report_file_extraction():
    print("\n[report parsing]")
    report = """
CONTEXT-PREFLIGHT REPORT
FILES WRITTEN:
  .techne/context/project_digest.md
  .techne/context/context_packs/techne.md
  .techne/context/context_hash.txt
"""
    files = extract_changed_files_from_report(report)
    expect_true("extracts context files", files == [
        ".techne/context/project_digest.md",
        ".techne/context/context_packs/techne.md",
        ".techne/context/context_hash.txt",
    ])


def test_orchestrator_starts_with_context_preflight():
    print("\n[orchestrator loop]")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "tasks.db"
        db = TaskDB(db_path)
        try:
            task = db.create_task(
                "Add context preflight to Techne",
                description="Make context packs mandatory before implementation",
                discipline="techne",
                tags=["context", "harness"],
            )
            loop = OrchestratorLoop(db)

            phase = loop.next_phase(task.id)
            expect_true("first phase is CONTEXT_PREFLIGHT", phase == "CONTEXT_PREFLIGHT")

            prompt = loop.get_prompt(task.id, phase)
            expect_true("context prompt includes mandatory preflight", "CONTEXT_PREFLIGHT (mandatory)" in prompt["user"])
            expect_true("context prompt includes selected techne pack", "SELECTED_PACKS: techne.md" in prompt["user"])

            report = """CONTEXT-PREFLIGHT REPORT
Task: t1 | Add context preflight to Techne
Status: CREATED
FILES WRITTEN:
  .techne/context/project_digest.md
  .techne/context/context_hash.txt
SELECTED_PACKS:
  techne.md
HITL_BOUNDARIES:
  none
"""
            outcome = loop.submit(task.id, phase, report)
            expect_true("context preflight advances to IMPLEMENT", outcome.action == LoopAction.RUN_PHASE and outcome.phase == "IMPLEMENT")
            expect_true("outcome phase is IMPLEMENT", outcome.phase == "IMPLEMENT")
        finally:
            db._conn.close()


def main():
    print("=" * 64)
    print("CONTEXT AMORTIZATION TESTS")
    print("=" * 64)

    test_skill_files_are_compact()
    test_router_wires_context_skill()
    test_context_pack_selection()
    test_preflight_prompt_is_mandatory()
    test_report_file_extraction()
    test_orchestrator_starts_with_context_preflight()

    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed

    print("\n" + "=" * 64)
    print(f"RESULTS: {passed}/{len(results)} passed")
    if failed:
        for label, ok, msg in results:
            if not ok:
                print(f"  FAIL {label}: {msg}")
    print("=" * 64)

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
