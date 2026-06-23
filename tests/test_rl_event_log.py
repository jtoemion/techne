"""
test_rl_event_log.py — RL event logging writes valid JSON lines to .techne/events/rl.jsonl.

Run from tests/:  python test_rl_event_log.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(TESTS_DIR))

from _mem_guard import *  # noqa: snapshots memory/, restores at exit

from reward_log import RewardLog


def check(label: str, condition: bool) -> None:
    """Accumulate results for final summary."""
    global results
    results.append(condition)
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")


results: list[bool] = []


def test_rl_event_log_creates_file():
    """post_run_evolve() writes a JSON line to .techne/events/rl.jsonl."""
    print("\n[event log — creates rl.jsonl on post_run_evolve]")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Change to temp dir so .techne/events/ is created there (not in repo).
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            rl = RewardLog(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

            # Import the context function (it's a method on OrchestratorContext).
            from _orchestrator_context import post_run_evolve

            # Bind to a minimal mock context that satisfies what post_run_evolve needs.
            class _Ctx:
                reward_log = rl
                evolution = _MockEvolution()
                gate_evolution = _MockGateEvolution()
                rl_dashboard = lambda self: ""

            ctx = _Ctx()
            result = post_run_evolve(ctx)

            events_path = Path(tmpdir) / ".techne" / "events" / "rl.jsonl"
            check("event file created", events_path.exists())
            check("event file is non-empty", events_path.stat().st_size > 0)

            with open(events_path) as f:
                line = f.readline()
            check("line is valid JSON", line.strip())
            event = json.loads(line)
            check("event has 'ts' key", "ts" in event)
            check("event has 'event' key", "event" in event)
            check("event has 'task_count' key", "task_count" in event)
            check("event has 'prompts_proposed' key", "prompts_proposed" in event)
            check("event has 'skills_proposed' key", "skills_proposed" in event)
            check("event has 'framework_proposed' key", "framework_proposed" in event)
            check("event has 'advantages_computed' key", "advantages_computed" in event)
            check("event type is grpo_proposals", event.get("event") == "grpo_proposals")
        finally:
            os.chdir(orig_cwd)


def test_rl_event_log_append():
    """Two post_run_evolve() calls produce two lines (append mode)."""
    print("\n[event log — append mode, two calls = two lines]")

    with tempfile.TemporaryDirectory() as tmpdir:
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            rl = RewardLog(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
            from _orchestrator_context import post_run_evolve

            class _Ctx:
                reward_log = rl
                evolution = _MockEvolution()
                gate_evolution = _MockGateEvolution()
                rl_dashboard = lambda self: ""

            ctx = _Ctx()

            # Call twice.
            post_run_evolve(ctx)
            post_run_evolve(ctx)

            events_path = Path(tmpdir) / ".techne" / "events" / "rl.jsonl"
            with open(events_path) as f:
                lines = [line for line in f if line.strip()]
            check("two lines after two calls", len(lines) == 2)
            for i, line in enumerate(lines):
                check(f"line {i+1} is valid JSON", _is_valid_json(line))
        finally:
            os.chdir(orig_cwd)


def _is_valid_json(s: str) -> bool:
    try:
        json.loads(s)
        return True
    except Exception:
        return False


class _MockEvolution:
    """Minimal mock for EvolutionStage/propose()."""

    def propose(self, task_type: str, agent: str = "implementer"):
        return None

    def dashboard(self) -> str:
        return ""


class _MockGateEvolution:
    """Minimal mock for GateEvolution/propose()."""

    def propose(self, min_count: int = 3):
        return []


if __name__ == "__main__":
    print("=" * 60)
    print("RL EVENT LOG — post_run_evolve() writes audit JSON lines")
    print("=" * 60)
    test_rl_event_log_creates_file()
    test_rl_event_log_append()
    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed" + ("  -- all clear" if passed == total else f"  ({total-passed} FAILED)"))
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
