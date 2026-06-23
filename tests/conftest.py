"""
conftest.py — make pytest the canonical, HONEST runner for the Techne suite.

Many test files are "script-style": their test_* functions record outcomes into a
module-global `results` list via helpers like ok()/fail()/check(), and only assert
overall pass/fail in their `if __name__ == "__main__"` block. Under bare pytest those
functions never raise, so pytest marked them green even when they recorded failures —
a false pass that hid real staleness (e.g. routing tests against renamed skills).

This hook closes that gap: after each test runs, it inspects the entries the test
appended to its module's `results` and fails the test if any are failures. Files that
use plain `assert` (no `results` list) are unaffected, and a test that already raised
keeps its real error.

`results` entry shapes supported:
  - bool                      → False means a failed check     (check(label, cond))
  - (label, ok, reason, ...)  → 2nd item is the pass flag      (ok()/fail())
"""
import subprocess as _subprocess_module
import sys
from pathlib import Path
import pytest

_HARNESS_DIR = Path(__file__).parent.parent / "harness"
if str(_HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(_HARNESS_DIR))

# Save real subprocess.run BEFORE any module-level mock.patch().start() replaces it.
# test_loop_hardening.py and stress_test.py patch subprocess.run at module level and
# never stop it. Restoring the real function lets test_scripts/ and test_workshop_foundation
# spawn real child processes.
_real_subprocess_run = _subprocess_module.run

# Save real checkpoint.check_honcho_logged for the same reason:
# test_phase_summary_printing.py patches it at module level and never stops the patch.
# Tests that verify honcho is NOT logged (test_conclude_gate, test_enforcement) need the real one.
import importlib as _importlib
_checkpoint_module = _importlib.import_module("checkpoint")
_real_check_honcho_logged = _checkpoint_module.check_honcho_logged


@pytest.fixture(autouse=True)
def _restore_subprocess_run(monkeypatch):
    """Restore real subprocess.run and checkpoint.check_honcho_logged before every test.

    test_loop_hardening.py and stress_test.py apply module-level subprocess.run mocks
    that persist for the whole session. test_phase_summary_printing.py patches
    checkpoint.check_honcho_logged at module level. Both contaminate unrelated tests.
    """
    monkeypatch.setattr(_subprocess_module, "run", _real_subprocess_run)
    monkeypatch.setattr(_checkpoint_module, "check_honcho_logged", _real_check_honcho_logged)


def _is_failure(entry) -> bool:
    if entry is False:
        return True
    if isinstance(entry, (tuple, list)) and len(entry) >= 2:
        return not entry[1]
    return False


def _label(entry) -> str:
    if isinstance(entry, (tuple, list)) and entry:
        return str(entry[0])
    return "unlabeled check"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    results = getattr(getattr(item, "module", None), "results", None)
    before = len(results) if isinstance(results, list) else None
    res = yield  # runs the test; re-raises here if it asserted/raised on its own
    if before is not None:
        failures = [_label(e) for e in results[before:] if _is_failure(e)]
        if failures:
            raise AssertionError(
                f"{len(failures)} recorded failure(s): " + "; ".join(failures)
            )
    return res
