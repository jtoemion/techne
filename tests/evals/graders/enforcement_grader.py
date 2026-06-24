"""
enforcement_grader.py — eval suite: enforcement stack (phase_guard, audit chain).

Tests the phase_guard plugin write-discipline and the audit chain integrity.
phase_guard is loaded via importlib.util.spec_from_file_location (not direct
import through plugins __init__).
"""
import json
import sys
import tempfile
from pathlib import Path

EVALS_DIR = Path(__file__).parent.parent
HARNESS_DIR = EVALS_DIR.parent.parent / "harness"
sys.path.insert(0, str(HARNESS_DIR))

# Import audit_chain via exec (scripts/ is not an importable package)
import hashlib
import sys
import types

_audit_chain_path = HARNESS_DIR.parent / "scripts" / "audit_chain.py"
_audit_chain_src = _audit_chain_path.read_text(encoding="utf-8")

# Create a proper module object so @dataclass decorators work correctly
_audit_mod = types.ModuleType("scripts.audit_chain")
_audit_mod.__file__ = str(_audit_chain_path)
sys.modules["scripts.audit_chain"] = _audit_mod
exec(_audit_chain_src, _audit_mod.__dict__)

AuditEntry = _audit_mod.AuditEntry
append_entry = _audit_mod.append_entry
verify_chain = _audit_mod.verify_chain
GENESIS_PREV = _audit_mod.GENESIS_PREV


def run(verbose: bool = False, **kwargs) -> dict:
    """
    Test enforcement stack (phase_guard + audit chain).
    Returns {suite, passed, failed, total, cases, failures, status}.
    """
    cases = []
    failures = []
    passed = 0
    failed = 0

    # ── Case 1: no .techne/ → phase_guard blocks all source writes ───────────
    c1 = _test_no_techne_dir()
    cases.append(c1)
    if c1["passed"]:
        passed += 1
        if verbose:
            print(f"  PASS [enf-1] no_techne_dir")
    else:
        failed += 1
        failures.append(f"[enf-1] no_techne_dir: {c1['reason']}")
        if verbose:
            print(f"  FAIL [enf-1] {c1['reason']}")

    # ── Case 2: .techne/ exists but no state.json ──────────────────────────
    c2 = _test_no_state_json()
    cases.append(c2)
    if c2["passed"]:
        passed += 1
        if verbose:
            print(f"  PASS [enf-2] no_state_json")
    else:
        failed += 1
        failures.append(f"[enf-2] no_state_json: {c2['reason']}")
        if verbose:
            print(f"  FAIL [enf-2] {c2['reason']}")

    # ── Case 3: correct phase artifact → allowed ────────────────────────────
    c3 = _test_correct_phase_artifact()
    cases.append(c3)
    if c3["passed"]:
        passed += 1
        if verbose:
            print(f"  PASS [enf-3] correct_phase_artifact")
    else:
        failed += 1
        failures.append(f"[enf-3] correct_phase_artifact: {c3['reason']}")
        if verbose:
            print(f"  FAIL [enf-3] {c3['reason']}")

    # ── Case 4: wrong phase artifact → blocked ───────────────────────────────
    c4 = _test_wrong_phase_artifact()
    cases.append(c4)
    if c4["passed"]:
        passed += 1
        if verbose:
            print(f"  PASS [enf-4] wrong_phase_artifact")
    else:
        failed += 1
        failures.append(f"[enf-4] wrong_phase_artifact: {c4['reason']}")
        if verbose:
            print(f"  FAIL [enf-4] {c4['reason']}")

    # ── Case 5: audit dir blocked ────────────────────────────────────────────
    c5 = _test_audit_dir_blocked()
    cases.append(c5)
    if c5["passed"]:
        passed += 1
        if verbose:
            print(f"  PASS [enf-5] audit_dir_blocked")
    else:
        failed += 1
        failures.append(f"[enf-5] audit_dir_blocked: {c5['reason']}")
        if verbose:
            print(f"  FAIL [enf-5] {c5['reason']}")

    # ── Case 6: audit chain integrity ───────────────────────────────────────
    c6 = _test_audit_chain_integrity()
    cases.append(c6)
    if c6["passed"]:
        passed += 1
        if verbose:
            print(f"  PASS [enf-6] audit_chain_integrity")
    else:
        failed += 1
        failures.append(f"[enf-6] audit_chain_integrity: {c6['reason']}")
        if verbose:
            print(f"  FAIL [enf-6] {c6['reason']}")

    status = "pass" if failed == 0 else "fail"
    return {
        "suite": "enforcement",
        "passed": passed,
        "failed": failed,
        "total": len(cases),
        "cases": cases,
        "failures": failures,
        "status": status,
    }


# ── phase_guard loader via importlib ─────────────────────────────────────────


def _load_phase_guard():
    """Load phase_guard via importlib.util.spec_from_file_location."""
    import importlib.util

    pg_path = HARNESS_DIR / "plugins" / "phase_guard.py"
    spec = importlib.util.spec_from_file_location("phase_guard", pg_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["phase_guard"] = module
    spec.loader.exec_module(module)
    return module


# ── Test helpers ──────────────────────────────────────────────────────────────


def _test_no_techne_dir() -> dict:
    """No .techne/ → phase_guard blocks all source writes."""
    pg = _load_phase_guard()

    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp) / "project"
        cwd.mkdir()
        # No .techne/ created

        allowed, reason = pg.check_write_allowed("src/test.ts", cwd=str(cwd))

        result = {"passed": False, "reason": ""}
        if allowed is False:
            result["passed"] = True
        else:
            result["reason"] = f"expected blocked, got allowed={allowed}"

        return result


def _test_no_state_json() -> dict:
    """.techne/ exists but no state.json → blocks source, allows .techne/ writes."""
    pg = _load_phase_guard()

    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp) / "project"
        cwd.mkdir()
        techne_dir = cwd / ".techne"
        techne_dir.mkdir()

        # .techne/ exists but no state.json
        allowed_source, _ = pg.check_write_allowed("src/test.ts", cwd=str(cwd))
        allowed_techne, _ = pg.check_write_allowed(".techne/loop/state.json", cwd=str(cwd))

        result = {"passed": False, "reason": ""}
        if allowed_source is False and allowed_techne is True:
            result["passed"] = True
        else:
            result["reason"] = (
                f"source={'blocked' if not allowed_source else 'allowed'}, "
                f".techne/={'allowed' if allowed_techne else 'blocked'}"
            )

        return result


def _test_correct_phase_artifact() -> dict:
    """.techne/ with state.json phase=RECALL → recall.txt allowed."""
    pg = _load_phase_guard()

    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp) / "project"
        cwd.mkdir()
        techne_dir = cwd / ".techne"
        loop_dir = techne_dir / "loop"
        loop_dir.mkdir(parents=True)

        # Write state.json with phase=RECALL
        state = {"phase": "RECALL", "task_id": "test_task"}
        (loop_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

        allowed, _ = pg.check_write_allowed(".techne/loop/recall.txt", cwd=str(cwd))

        result = {"passed": False, "reason": ""}
        if allowed is True:
            result["passed"] = True
        else:
            result["reason"] = f"expected allowed for recall.txt in RECALL phase, got blocked"

        return result


def _test_wrong_phase_artifact() -> dict:
    """state.json phase=RECALL → test_output.txt blocked."""
    pg = _load_phase_guard()

    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp) / "project"
        cwd.mkdir()
        techne_dir = cwd / ".techne"
        loop_dir = techne_dir / "loop"
        loop_dir.mkdir(parents=True)

        state = {"phase": "RECALL", "task_id": "test_task"}
        (loop_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

        allowed, _ = pg.check_write_allowed(".techne/loop/test_output.txt", cwd=str(cwd))

        result = {"passed": False, "reason": ""}
        if allowed is False:
            result["passed"] = True
        else:
            result["reason"] = f"expected blocked for test_output.txt in RECALL phase, got allowed"

        return result


def _test_audit_dir_blocked() -> dict:
    """state.json phase=IMPLEMENT → .techne/audit/chain.jsonl blocked."""
    pg = _load_phase_guard()

    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp) / "project"
        cwd.mkdir()
        techne_dir = cwd / ".techne"
        loop_dir = techne_dir / "loop"
        audit_dir = techne_dir / "audit"
        loop_dir.mkdir(parents=True)
        audit_dir.mkdir(parents=True)

        state = {"phase": "IMPLEMENT", "task_id": "test_task"}
        (loop_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

        allowed, _ = pg.check_write_allowed(".techne/audit/chain.jsonl", cwd=str(cwd))

        result = {"passed": False, "reason": ""}
        if allowed is False:
            result["passed"] = True
        else:
            result["reason"] = f"expected blocked for .techne/audit/ in IMPLEMENT phase, got allowed"

        return result


def _test_audit_chain_integrity() -> dict:
    """Sequence of 3 audit entries with proper prev_hash chaining → chain validates."""
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp) / "project"
        cwd.mkdir()
        techne_dir = cwd / ".techne"
        audit_dir = techne_dir / "audit"
        audit_dir.mkdir(parents=True)

        chain_path = audit_dir / "chain.jsonl"

        # Patch the audit_chain module to use our temp directory
        ac = _audit_mod
        orig_chain_file = ac.CHAIN_FILE
        orig_audit_dir = ac.AUDIT_DIR
        ac.CHAIN_FILE = chain_path
        ac.AUDIT_DIR = audit_dir

        try:
            # Append 3 entries
            for i in range(3):
                entry = AuditEntry(
                    seq=0,  # Will be overwritten by append_entry
                    timestamp="2025-01-01T00:00:00Z",
                    task_id=f"task_{i}",
                    phase="IMPLEMENT",
                    gates=[],
                    summary=f"summary {i}",
                    prev_hash="",  # Will be set by append_entry
                )
                append_entry(entry)

            # Verify the chain
            valid, msg = verify_chain()

            # Also manually verify each prev_hash link
            with open(chain_path) as fh:
                lines = [ln.strip() for ln in fh if ln.strip()]

            links_valid = True
            prev_hash = GENESIS_PREV
            for idx, line in enumerate(lines):
                d = json.loads(line)
                if d["prev_hash"] != prev_hash:
                    links_valid = False
                    break
                # Recompute hash to verify integrity
                entry = AuditEntry(
                    seq=d["seq"],
                    timestamp=d["timestamp"],
                    task_id=d["task_id"],
                    phase=d["phase"],
                    gates=d["gates"],
                    summary=d["summary"],
                    prev_hash=d["prev_hash"],
                    entry_hash=d["entry_hash"],
                )
                expected_hash = _audit_mod.compute_hash(entry)
                if expected_hash != d["entry_hash"]:
                    links_valid = False
                    break
                prev_hash = d["entry_hash"]

            result = {"passed": False, "reason": ""}
            if valid and links_valid and len(lines) == 3:
                result["passed"] = True
            else:
                result["reason"] = f"chain valid={valid}, links_valid={links_valid}, entries={len(lines)}"

        finally:
            ac.CHAIN_FILE = orig_chain_file
            ac.AUDIT_DIR = orig_audit_dir

        return result
