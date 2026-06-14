"""
test_kanban.py — Kanban-worker compatibility: run-state isolation.

The compatibility blocker (skills/kanban/isolation.md): a Hermes card runs Techne
in an isolated worker, but conductor/checkpoint wrote ONE shared
memory/harness-state.json — parallel cards corrupt each other's run counter and
verify flag. The fix: store.state_dir() honors a caller's TECHNE_STATE_DIR.

This test is the baseline-failure PROOF:
  - WITHOUT the override, two runs share state (the bug we're guarding against).
  - WITH per-worker TECHNE_STATE_DIR, two runs are independent (the fix).

Run from tests/:  python test_kanban.py
"""

import os
import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

import store
import checkpoint

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []


def check(label, cond):
    results.append(cond)
    print(f"  {PASS if cond else FAIL} {label}")


def _clear_override():
    os.environ.pop(store.STATE_DIR_ENV, None)


def test_default_is_memory_dir():
    """No override → state_dir resolves to memory/ (backward compatible)."""
    print("\n[kanban — default state_dir is memory/]")
    _clear_override()
    check("state_dir() == memory/ when unset", store.state_dir() == store.MEMORY_DIR)
    check("checkpoint state file under memory/",
          checkpoint._state_file() == store.MEMORY_DIR / "harness-state.json")


def test_override_redirects_state():
    """TECHNE_STATE_DIR redirects the checkpoint file into the worker's dir."""
    print("\n[kanban — TECHNE_STATE_DIR isolates one worker]")
    with tempfile.TemporaryDirectory() as d:
        os.environ[store.STATE_DIR_ENV] = d
        try:
            check("state_dir() honors the override", store.state_dir() == Path(d))
            check("checkpoint writes under the override",
                  checkpoint._state_file() == Path(d) / "harness-state.json")
            checkpoint.init_state()
            n = checkpoint.increment_pipeline_run()
            check("run counter starts in the isolated dir (==1)", n == 1)
            check("the override dir actually holds the state file",
                  (Path(d) / "harness-state.json").exists())
            check("memory/ was NOT written for this worker",
                  not (Path(d) / "harness-state.json").samefile(store.MEMORY_DIR / "harness-state.json")
                  if (store.MEMORY_DIR / "harness-state.json").exists() else True)
        finally:
            _clear_override()


def test_two_workers_do_not_collide():
    """Two isolated dirs → independent pipeline counters (the parallel-safety claim)."""
    print("\n[kanban — two parallel workers keep separate state]")
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        os.environ[store.STATE_DIR_ENV] = a
        checkpoint.init_state()
        checkpoint.increment_pipeline_run()
        checkpoint.increment_pipeline_run()       # worker A: 2 runs
        checkpoint.mark_verified("sha-A")

        os.environ[store.STATE_DIR_ENV] = b
        checkpoint.init_state()
        n_b = checkpoint.increment_pipeline_run()  # worker B: fresh
        verified_b = checkpoint.check_verification()

        os.environ[store.STATE_DIR_ENV] = a
        state_a = checkpoint.read_state()
        _clear_override()

        check("worker B counter independent of A (==1)", n_b == 1)
        check("worker B not marked verified by A's mark_verified", verified_b is False)
        check("worker A retained its own 2 runs", state_a.get("pipeline_runs") == 2)
        check("worker A kept its own verify sha", state_a.get("last_verification_sha") == "sha-A")


if __name__ == "__main__":
    print("=" * 60)
    print("KANBAN WORKER — STATE ISOLATION TEST")
    print("=" * 60)
    test_default_is_memory_dir()
    test_override_redirects_state()
    test_two_workers_do_not_collide()
    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed" + ("  -- all clear" if passed == total else f"  ({total-passed} FAILED)"))
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
