"""
test_worker_gate.py — the deterministic FLOOR gate for Kanban deliverables.

Verifies each structural check (exists / persistent / non-stub / contract / grounded)
passes and fails as specified, that enforce() raises GateViolation, and that the gate
is purely structural — it never judges quality. See skills/kanban/roles.md.

Run from tests/:  python test_worker_gate.py
"""

import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

import worker_gate as wg
from gates import GateViolation

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []

# A durable scratch dir UNDER the repo (not the system tempdir) for content tests,
# so must_persist doesn't trip on legitimate content cases.
WORK = TESTS_DIR / "_wg_tmp"


def check(label, cond):
    results.append(cond)
    print(f"  {PASS if cond else FAIL} {label}")


def write(name: str, content: str) -> str:
    WORK.mkdir(exist_ok=True)
    p = WORK / name
    p.write_text(content, encoding="utf-8")
    return str(p)


def test_exists_and_persistent():
    print("\n[floor — exists / persistent]")
    missing = wg.Acceptance(deliverable_path=str(WORK / "nope.md"), must_persist=False)
    r = wg.check_deliverable(missing)
    check("missing file fails 'exists'", r.checks["exists"] is False and not r.passed)

    # A file in the system tempdir fails 'persistent' (the stranded-file footgun).
    tf = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    tf.write("real content here, long enough to pass non-stub easily."); tf.close()
    r = wg.check_deliverable(wg.Acceptance(deliverable_path=tf.name, must_persist=True))
    check("tempdir file fails 'persistent'", r.checks.get("persistent") is False)
    r2 = wg.check_deliverable(wg.Acceptance(deliverable_path=tf.name, must_persist=False))
    check("same file passes when must_persist=False", r2.passed)
    Path(tf.name).unlink()

    # Regression: a durable path that merely CONTAINS "temp"/"tmp" as a substring
    # (e.g. .../templates/...) must NOT be flagged scratch. Single-segment match only.
    tdir = TESTS_DIR / "templates_out"
    tdir.mkdir(exist_ok=True)
    tricky = tdir / "report.md"
    tricky.write_text("# Report\n\nsubstantive durable content here.", encoding="utf-8")
    r3 = wg.check_deliverable(wg.Acceptance(str(tricky), must_persist=True))
    check("'templates/' path NOT flagged scratch (substring false-positive)", r3.checks.get("persistent") is True)
    tricky.unlink(); tdir.rmdir()


def test_non_stub():
    print("\n[floor — non-stub]")
    empty = write("empty.md", "   \n  ")
    check("empty fails non_stub", not wg.check_deliverable(wg.Acceptance(empty, must_persist=False, min_chars=5)).checks["non_stub"])
    todo = write("todo.md", "TODO")
    check("bare 'TODO' fails non_stub", not wg.check_deliverable(wg.Acceptance(todo, must_persist=False)).checks["non_stub"])
    bail = write("bail.md", "I was unable to complete this build.")
    check("short bail fails non_stub", not wg.check_deliverable(wg.Acceptance(bail, must_persist=False)).checks["non_stub"])
    real = write("real.md", "# Report\n\nHere is a full, substantive answer to the task with detail.")
    check("substantive content passes non_stub", wg.check_deliverable(wg.Acceptance(real, must_persist=False)).checks["non_stub"])


def test_contract_json():
    print("\n[floor — contract: json + required fields]")
    good = write("good.json", '{"title": "x", "score": 80, "sources": []}')
    r = wg.check_deliverable(wg.Acceptance(good, must_persist=False, fmt="json", required_fields=["title", "score"]))
    check("valid json with fields passes contract", r.checks["contract"])
    miss = write("miss.json", '{"title": "x"}')
    r = wg.check_deliverable(wg.Acceptance(miss, must_persist=False, fmt="json", required_fields=["title", "score"]))
    check("json missing a field fails contract", not r.checks["contract"])
    bad = write("bad.json", "{not valid json")
    r = wg.check_deliverable(wg.Acceptance(bad, must_persist=False, fmt="json"))
    check("unparseable json fails contract", not r.checks["contract"])


def test_contract_markdown_and_grounded():
    print("\n[floor — contract: markdown sections + grounded]")
    md = write("doc.md", "# Summary\n\nfindings here\n\n# Sources\n\n- https://example.com/x")
    r = wg.check_deliverable(wg.Acceptance(md, must_persist=False, fmt="markdown",
                                           required_fields=["Summary", "Sources"], require_sources=True))
    check("markdown with required sections passes contract", r.checks["contract"])
    check("deliverable with a URL passes grounded", r.checks["grounded"])
    nolink = write("nolink.md", "# Summary\n\nclaims with no source at all\n\n# Sources\n\n(none)")
    r = wg.check_deliverable(wg.Acceptance(nolink, must_persist=False, fmt="markdown",
                                           required_fields=["Summary"], require_sources=True))
    check("require_sources with no link fails grounded", not r.checks["grounded"])


def test_enforce_and_full_pass():
    print("\n[floor — enforce() raises; a clean deliverable passes everything]")
    good = write("clean.md", "# Answer\n\nA complete deliverable with a source: https://example.com")
    acc = wg.Acceptance(good, must_persist=False, fmt="markdown", required_fields=["Answer"], require_sources=True)
    r = wg.check_deliverable(acc)
    check("clean deliverable: passed True", r.passed)
    check("clean deliverable: every check True", all(r.checks.values()))
    check("enforce() returns on pass", wg.enforce(acc).passed)

    bad = wg.Acceptance(str(WORK / "ghost.md"), must_persist=False)
    try:
        wg.enforce(bad)
        check("enforce() raises GateViolation on failure", False)
    except GateViolation:
        check("enforce() raises GateViolation on failure", True)


def _cleanup():
    if not WORK.exists():
        return
    for p in WORK.glob("*"):
        p.unlink()
    WORK.rmdir()


def teardown_module(module):
    """pytest path: remove the scratch dir after the module's tests run, mirroring
    the __main__ `finally`. Without this, pytest left tests/_wg_tmp/ behind each run."""
    _cleanup()


if __name__ == "__main__":
    print("=" * 60)
    print("WORKER FLOOR GATE — TEST")
    print("=" * 60)
    try:
        test_exists_and_persistent()
        test_non_stub()
        test_contract_json()
        test_contract_markdown_and_grounded()
        test_enforce_and_full_pass()
    finally:
        _cleanup()
    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed" + ("  -- all clear" if passed == total else f"  ({total-passed} FAILED)"))
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
