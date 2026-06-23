"""Full end-to-end test of the ./next loop system.

Creates a task, walks through RECALL → IMPLEMENT → VERIFY → CONCLUDE → DONE,
verifying each phase's gate behavior.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

# Path to the techne repo
TECHNE = Path(__file__).resolve().parent.parent  # scripts/../ = techne/
NEXT_SCRIPT = TECHNE / "scripts" / "next.py"


def _next(cwd: Path) -> subprocess.CompletedProcess:
    """Run ./next in the given directory and return the result."""
    return subprocess.run(
        [sys.executable, str(NEXT_SCRIPT)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_full_loop():
    """Walk through every phase and verify gate behavior."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cwd = Path(tmpdir)

        # Create .techne/loop/ directory structure
        loop_dir = cwd / ".techne" / "loop"
        loop_dir.mkdir(parents=True, exist_ok=True)

        # ---- SCENARIO 1: No state ----
        print("=" * 60)
        print("SCENARIO 1: No state → should fail cleanly")
        print("=" * 60)
        r = _next(cwd)
        assert r.returncode == 1, f"Expected exit 1, got {r.returncode}"
        assert "No active loop" in r.stdout, f"Unexpected output: {r.stdout}"
        print(f"  PASS: {r.stdout.strip()}")
        print()

        # ---- SCENARIO 2: RECALL phase ----
        print("=" * 60)
        print("SCENARIO 2: RECALL phase — no artifact → fails")
        print("=" * 60)

        # Create initial state
        state_path = loop_dir / "state.json"
        state = {
            "task_id": "test-001",
            "phase": "RECALL",
            "created_at": "2026-06-23T12:00:00",
            "updated_at": "2026-06-23T12:00:00",
        }
        state_path.write_text(json.dumps(state, indent=2))

        # Should fail — recall.txt doesn't exist yet
        r = _next(cwd)
        assert r.returncode == 1, f"Expected exit 1 (no artifact), got {r.returncode}"
        assert "artifact:" in r.stdout and "not found" in r.stdout, \
            f"Expected artifact error in: {r.stdout}"
        print(f"  PASS: {r.stdout.split(chr(10))[3].strip()}")
        print()

        # ---- SCENARIO 3: RECALL with valid artifact ----
        print("=" * 60)
        print("SCENARIO 3: RECALL with valid artifact → advances to IMPLEMENT")
        print("=" * 60)

        # Write a valid recall artifact
        recall_artifact = loop_dir / "recall.txt"
        recall_artifact.write_text(
            "HONCHO_CONTEXT: searched for 'test-001'\n"
            "Found relevant context: test setup pattern\n"
            "Task involves verifying the loop system\n"
            "Workshop context applied.\n"
        )

        r = _next(cwd)
        assert r.returncode == 0, f"Expected exit 0, got {r.returncode} (output: {r.stdout})"
        assert "IMPLEMENT" in r.stdout, f"Expected IMPLEMENT in: {r.stdout}"
        assert "✓" in r.stdout, f"Expected checkmark in: {r.stdout}"
        print(f"  PASS: RECALL → IMPLEMENT transition")
        print(f"  Summary: {r.stdout.split(chr(10))[1].strip()}")
        print()

        # Verify state was advanced
        new_state = json.loads(state_path.read_text())
        assert new_state["phase"] == "IMPLEMENT", \
            f"Expected IMPLEMENT, got {new_state['phase']}"
        print(f"  State advanced: {new_state['phase']}")
        print()

        # ---- SCENARIO 4: IMPLEMENT with no artifact ----
        print("=" * 60)
        print("SCENARIO 4: IMPLEMENT — no diff → fails")
        print("=" * 60)

        r = _next(cwd)
        assert r.returncode == 1, f"Expected exit 1, got {r.returncode}"
        assert "artifact:" in r.stdout
        print(f"  PASS: {r.stdout.split(chr(10))[3].strip()}")
        print()

        # ---- SCENARIO 5: IMPLEMENT with valid diff ----
        print("=" * 60)
        print("SCENARIO 5: IMPLEMENT with valid diff → advances to VERIFY")
        print("=" * 60)

        diff_artifact = loop_dir / "diff.txt"
        diff_artifact.write_text(
            "diff --git a/app.py b/app.py\n"
            "index abc..def 100644\n"
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -1,5 +1,8 @@\n"
            " def hello():\n"
            "-    print('old')\n"
            "+    print('new')\n"
            "+\n"
            "+def world():\n"
            "+    return 42\n"
        )

        r = _next(cwd)
        assert r.returncode == 0, f"Expected exit 0, got {r.returncode} (output: {r.stdout})"
        assert "VERIFY" in r.stdout, f"Expected VERIFY in: {r.stdout}"
        print(f"  PASS: IMPLEMENT → VERIFY transition")
        print(f"  Summary: {r.stdout.split(chr(10))[1].strip()}")
        print()

        # ---- SCENARIO 6: IMPLEMENT — forbidden patterns ----
        print("=" * 60)
        print("SCENARIO 6: IMPLEMENT with TODO marker → fails")
        print("=" * 60)

        # Reset to IMPLEMENT and write a bad diff
        state["phase"] = "IMPLEMENT"
        state_path.write_text(json.dumps(state, indent=2))
        bad_diff = loop_dir / "diff.txt"
        bad_diff.write_text(
            "diff --git a/app.py b/app.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+# TODO: fix this later\n"
        )

        r = _next(cwd)
        assert r.returncode == 1, f"Expected exit 1, got {r.returncode}"
        assert "TODO" in r.stdout, f"Expected TODO gate failure in: {r.stdout}"
        print(f"  PASS: TODO marker caught")
        print(f"  Detail: {[l for l in r.stdout.split(chr(10)) if 'TODO' in l][0].strip()}")
        print()

        # ---- SCENARIO 7: VERIFY phase ----
        print("=" * 60)
        print("SCENARIO 7: VERIFY with valid test output → advances to CONCLUDE")
        print("=" * 60)

        # Reset to IMPLEMENT, write good diff, advance
        state["phase"] = "IMPLEMENT"
        state_path.write_text(json.dumps(state, indent=2))
        diff_artifact.write_text(
            "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n"
        )
        r = _next(cwd)
        assert r.returncode == 0, f"Advance to VERIFY failed: {r.stdout}"

        # State should now be VERIFY
        assert json.loads(state_path.read_text())["phase"] == "VERIFY"

        # No artifact → should fail
        r = _next(cwd)
        assert r.returncode == 1, "Expected fail on missing test output"
        print(f"  PASS: VERIFY missing artifact caught")

        # Write valid test output
        test_output = loop_dir / "test_output.txt"
        test_output.write_text(
            "collected 42 items\n"
            "test_app.py ........                                  [ 50%]\n"
            "test_utils.py .......                                [100%]\n"
            "\n"
            "================= 42 passed in 0.42s =================\n"
        )

        r = _next(cwd)
        assert r.returncode == 0, f"Expected exit 0, got {r.returncode} (output: {r.stdout})"
        assert "CONCLUDE" in r.stdout, f"Expected CONCLUDE in: {r.stdout}"
        print(f"  PASS: VERIFY → CONCLUDE transition")
        print()

        # ---- SCENARIO 8: CONCLUDE phase ----
        print("=" * 60)
        print("SCENARIO 8: CONCLUDE without artifact → fails")
        print("=" * 60)

        r = _next(cwd)
        assert r.returncode == 1, "Expected fail on missing conclude.txt"
        print(f"  PASS: CONCLUDE missing artifact caught")
        print()

        # Write valid conclude
        conclude_artifact = loop_dir / "conclude.txt"
        conclude_artifact.write_text(
            "honcho_conclusion_id: abc-def-123\n"
            "Task completed successfully through all phases.\n"
            "Honcho context updated with task outcome.\n"
        )

        r = _next(cwd)
        assert r.returncode == 0, f"Expected exit 0, got {r.returncode} (output: {r.stdout})"
        assert "DONE" in r.stdout or "TASK COMPLETE" in r.stdout, \
            f"Expected DONE in: {r.stdout}"
        print(f"  PASS: CONCLUDE → DONE transition")
        print(f"  Summary: {r.stdout.split(chr(10))[1].strip()}")
        print()

        # ---- SCENARIO 9: DONE state ----
        print("=" * 60)
        print("SCENARIO 9: Already DONE → prints completion")
        print("=" * 60)

        r = _next(cwd)
        assert r.returncode == 0, f"Expected exit 0, got {r.returncode}"
        assert "DONE" in r.stdout or "all phases complete" in r.stdout.lower(), \
            f"Expected DONE in: {r.stdout}"
        print(f"  PASS: DONE state recognized")
        print()

    print("=" * 60)
    print("ALL SCENARIOS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    test_full_loop()
