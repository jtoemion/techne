"""
test_gate_proposals.py — the gate propose / validate / ratify firewall.

gate_evolution used to write a gate plugin the instant statistical thresholds
passed (auto_evolve → approve → write). A gate is part of the GRADER, so a
self-writing grader is the sharpest Goodhart hole there is. This drives the
replacement: gate candidates are STAGED, structurally validated against history,
and only a HUMAN ratification writes the plugin file — recurrence-gated +
structurally-gated + human-approved, never threshold-driven auto-write.

Mirrors test_prompt_proposals.py (the same firewall on the policy).

Run from tests/:  python test_gate_proposals.py
"""

import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

import gate_evolution
from gate_evolution import GateEvolution
from reward_log import RewardLog

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []

# Redirect gate writes to a temp dir so ratification never pollutes the real
# harness/plugins or memory/ during the test run.
_SANDBOX = Path(tempfile.mkdtemp(prefix="gate_evo_test_"))
gate_evolution.PLUGINS_DIR = _SANDBOX / "plugins"
gate_evolution.PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
gate_evolution.MEMORY_DIR = _SANDBOX / "memory"
gate_evolution.MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def check(label, cond):
    results.append(bool(cond))
    print(f"  {PASS if cond else FAIL} {label}")


def _fresh_evo(with_pattern=True):
    """A GateEvolution over a temp reward log + temp proposals file."""
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db.close()
    proposals = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    proposals.close()
    log = RewardLog(db.name)
    if with_pattern:
        # 4 tasks share the same finding → "null check" recurs (count 4 ≥ 3),
        # and find_candidates maps it to a known regex template.
        for i in range(4):
            log.record(
                task_id=f"t{i}", task_type="auth", prompt_variant="v1",
                gate_pass=True, test_pass=True,
                review_findings=["missing null check at boundary"],
                critique_predictions=[], scope_clean=True, attempt_count=1,
            )
    evo = GateEvolution(log, proposals_path=proposals.name)
    return evo, log, Path(db.name), Path(proposals.name)


def _written_gates():
    return list(gate_evolution.PLUGINS_DIR.glob("evolved_*.py"))


def test_propose_stages_without_writing():
    print("\n[propose — stages a candidate, writes NO plugin file]")
    evo, log, db, pf = _fresh_evo()
    before = set(_written_gates())
    staged = evo.propose(min_count=3)
    check("propose returns at least one proposal", len(staged) >= 1)
    check("proposal starts pending", all(p.status == "pending" for p in staged))
    check("no gate plugin written by propose", set(_written_gates()) == before)
    log.close(); db.unlink(); pf.unlink()


def test_propose_persists():
    print("\n[propose — proposal survives to a new instance via the log]")
    evo, log, db, pf = _fresh_evo()
    p = evo.propose(min_count=3)[0]
    evo2 = GateEvolution(log, proposals_path=str(pf))
    again = evo2.get_proposal(p.id)
    check("proposal retrievable by id from a new instance", again is not None)
    check("round-trips the gate name", again and again.gate_name == p.gate_name)
    check("listed under pending",
          any(x.id == p.id for x in evo2.list_proposals(status="pending")))
    log.close(); db.unlink(); pf.unlink()


def test_propose_needs_recurrence():
    print("\n[propose — recurrence gate: no recurring pattern, no proposal]")
    evo, log, db, pf = _fresh_evo(with_pattern=False)
    staged = evo.propose(min_count=3)
    check("propose returns nothing without recurrence", staged == [])
    check("nothing written to the proposals log", evo.list_proposals() == [])
    log.close(); db.unlink(); pf.unlink()


def test_propose_is_idempotent_while_open():
    print("\n[propose — does not stack duplicate open proposals]")
    evo, log, db, pf = _fresh_evo()
    first = evo.propose(min_count=3)[0]
    again = evo.propose(min_count=3)[0]
    check("second propose reuses the same open proposal", first.id == again.id)
    check("only one proposal per gate_name in the log",
          len([x for x in evo.list_proposals() if x.gate_name == first.gate_name]) == 1)
    log.close(); db.unlink(); pf.unlink()


def test_validate_is_structural_gate_only():
    print("\n[validate — marks validated/rejected, writes nothing]")
    evo, log, db, pf = _fresh_evo()
    p = evo.propose(min_count=3)[0]
    before = set(_written_gates())
    validated = evo.validate(p)
    check("recurring pattern → validated", validated.status == "validated")
    check("validate writes no gate plugin", set(_written_gates()) == before)
    log.close(); db.unlink(); pf.unlink()


def test_ratify_promotes_only_validated():
    print("\n[ratify — human step writes a validated gate]")
    evo, log, db, pf = _fresh_evo()
    p = evo.propose(min_count=3)[0]
    evo.validate(p)
    ok = evo.ratify(p.id, approved=True, by="test")
    check("ratify returns True", ok is True)
    check("gate plugin now exists on disk",
          (gate_evolution.PLUGINS_DIR / f"evolved_{p.gate_name}.py").exists())
    check("status recorded as ratified",
          evo.get_proposal(p.id).status == "ratified")
    log.close(); db.unlink(); pf.unlink()


def test_ratify_refuses_unvalidated():
    print("\n[ratify — structural gate: cannot write a pending proposal]")
    evo, log, db, pf = _fresh_evo()
    p = evo.propose(min_count=3)[0]  # never validated
    before = set(_written_gates())
    ok = evo.ratify(p.id, approved=True, by="test")
    check("ratify refuses (returns False) without validation", ok is False)
    check("no gate plugin written for a pending proposal",
          set(_written_gates()) == before)
    log.close(); db.unlink(); pf.unlink()


def test_ratify_reject_path():
    print("\n[ratify — human rejection marks rejected, writes nothing]")
    evo, log, db, pf = _fresh_evo()
    p = evo.propose(min_count=3)[0]
    evo.validate(p)
    before = set(_written_gates())
    ok = evo.ratify(p.id, approved=False, by="test")
    check("ratify(approved=False) returns False", ok is False)
    check("rejected by human → no gate written", set(_written_gates()) == before)
    check("status recorded as rejected",
          evo.get_proposal(p.id).status == "rejected")
    log.close(); db.unlink(); pf.unlink()


def test_auto_evolve_no_longer_writes():
    print("\n[auto_evolve — back-compat shim now stages instead of writing]")
    evo, log, db, pf = _fresh_evo()
    before = set(_written_gates())
    out = evo.auto_evolve(min_count=3)
    check("auto_evolve returns [] (writes nothing)", out == [])
    check("auto_evolve wrote no gate plugin", set(_written_gates()) == before)
    check("auto_evolve left a pending proposal instead",
          any(x.status == "pending" for x in evo.list_proposals()))
    log.close(); db.unlink(); pf.unlink()


def test_generated_gate_code_is_injection_safe():
    print("\n[security — a malicious finding cannot inject code into a generated gate]")
    import re as _re
    evo, log, db, pf = _fresh_evo(with_pattern=False)
    # A finding crafted to break out of a docstring/string and run code on import.
    nasty_desc = '"""; import os; os.system("touch PWNED"); _x = """'
    safe_regex = r'console\.log'  # a real, compilable regex; the payload is in the desc

    # The gate name must be coerced to a safe identifier even from a hostile pattern.
    name = evo._pattern_to_gate_name('"); import os #  evilname')
    check("gate name is a safe identifier", _re.fullmatch(r"[a-z][a-z0-9_]*", name) is not None)

    # An invalid/booby-trapped regex is refused at generation, not crashed at import.
    rejected = False
    try:
        evo._generate_gate_code("safe_name", r'"); __import__("os").system("x"); ("', "x")
    except ValueError:
        rejected = True
    check("invalid/hostile regex refused at generation", rejected)

    code = evo._generate_gate_code("safe_name", safe_regex, nasty_desc)
    # 1) It must be valid Python.
    compiled = None
    try:
        compiled = compile(code, "<evolved>", "exec")
    except SyntaxError:
        pass
    check("generated code parses (no broken-out syntax)", compiled is not None)

    # 2) Importing/exec-ing it must NOT run the payload.
    import tempfile, os as _os
    workdir = tempfile.mkdtemp()
    cwd = _os.getcwd()
    _os.chdir(workdir)
    try:
        ns = {}
        if compiled is not None:
            exec(compiled, ns)
        ran_payload = _os.path.exists("PWNED") or _os.path.exists("PWNED2")
        check("payload did NOT execute on import", not ran_payload)
        # The description survives as inert DATA, not code.
        check("pattern text stored as a string literal", ns.get("_PATTERN_DESC") == nasty_desc)
    finally:
        _os.chdir(cwd)
    log.close(); db.unlink(); pf.unlink()


if __name__ == "__main__":
    print("=" * 60)
    print("GATE PROPOSALS (propose / validate / ratify) — TEST")
    print("=" * 60)
    test_propose_stages_without_writing()
    test_propose_persists()
    test_propose_needs_recurrence()
    test_propose_is_idempotent_while_open()
    test_validate_is_structural_gate_only()
    test_ratify_promotes_only_validated()
    test_ratify_refuses_unvalidated()
    test_ratify_reject_path()
    test_auto_evolve_no_longer_writes()
    test_generated_gate_code_is_injection_safe()
    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed" + ("  -- all clear" if passed == total else f"  ({total-passed} FAILED)"))
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
