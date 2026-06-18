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
import pytest


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
