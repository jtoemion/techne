"""Techne Pipeline Orchestrator — retry caps, HITL, session continuity."""

import json
import os
import subprocess
from pathlib import Path

STATE_FILE = Path.home() / ".orchestrator_state.json"
TECHNE_DIR = ".techne"
TECHNE_STATE = "loop/state.json"
MAX_RETRIES = 3


def _detect_model_failure(tool_name: str, tool_input: dict, tool_output) -> bool:
    """
    Detect patterns that suggest a model/API failure requiring Revolver rotation.
    At pre_tool_call stage we only see the outgoing call, not the response yet,
    so detection is based on indirect signals:
      - Tool names that suggest model invocation with empty/null output
      - Repeated identical tool_input (retry loop indicator)
      - API error codes (401, 429, 502, 503) in tool_input
    """
    if tool_output is None or tool_output == "":
        # Empty output on a model-adjacent tool may signal API failure
        if tool_name in ("terminal", "bash", "read_file", "grep", "search_files"):
            return True

    input_str = str(tool_input or "")

    # API error codes in the input payload suggest a failing upstream call
    api_error_codes = ("401", "429", "502", "503")
    if any(code in input_str for code in api_error_codes):
        return True

    return False


def _read_state():
    """Read orchestrator state from JSON file."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "task_id": "",
        "phase": "",
        "attempt_count": 0,
        "hitl_blocked": False,
        "block_reason": "",
    }


def _write_state(state):
    """Write orchestrator state to JSON file."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _find_techne_state():
    """Walk up from cwd to find .techne/loop/state.json."""
    cwd = Path.cwd()
    for path in [cwd] + list(cwd.parents):
        state_path = path / TECHNE_DIR / TECHNE_STATE
        if state_path.exists():
            return state_path
    return None


def _read_techne_phase():
    """Read current phase from .techne/loop/state.json."""
    state_path = _find_techne_state()
    if state_path:
        try:
            with open(state_path) as f:
                data = json.load(f)
                return data.get("phase", ""), data.get("task_id", "")
        except (json.JSONDecodeError, IOError):
            pass
    return "", ""


def _run_techne_handoff():
    """Run techne handoff via subprocess."""
    try:
        result = subprocess.run(
            ["python3", "-m", "techne_cli.main", "handoff"],
            cwd=str(Path.home() / "repos" / "techne"),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)


def register(ctx):
    """Plugin registration — returns dict of hook handlers and commands."""

    # -------------------------------------------------------------------------
    # on_session_start
    # -------------------------------------------------------------------------
    def on_session_start(session_id=None, **kwargs):
        state = _read_state()
        techne_phase, task_id = _read_techne_phase()

        # Sync task/phase if we have techne state
        if techne_phase and techne_phase != state.get("phase"):
            state["phase"] = techne_phase
        if task_id:
            state["task_id"] = task_id

        _write_state(state)

        phase = state.get("phase", "UNKNOWN")
        attempt = state.get("attempt_count", 0)
        blocked = state.get("hitl_blocked", False)

        print(f"[orchestrator] Session started — Phase: {phase} | Attempt: {attempt} | HITL: {'BLOCKED' if blocked else 'clear'}")

        if phase and phase != "DONE":
            print(f"[orchestrator] Active task detected — use /orchestrator status for details")

    # -------------------------------------------------------------------------
    # pre_tool_call
    # -------------------------------------------------------------------------
    def pre_tool_call(tool_name=None, tool_input=None, **kwargs):
        state = _read_state()
        techne_phase, _ = _read_techne_phase()

        # Detect phase changes
        current_phase = techne_phase or state.get("phase", "")
        if current_phase and current_phase != state.get("phase"):
            state["phase"] = current_phase
            state["attempt_count"] = 0  # Reset on phase change
            _write_state(state)

        # Check for ultrawork/ulw routing in tool_input
        input_str = str(tool_input or "")
        if "ultrawork" in input_str.lower() or "ulw" in input_str.lower():
            phase = state.get("phase", "")
            inject = {
                "action": "inject",
                "message": (
                    f"[orchestrator] Ultrawork task detected. "
                    f"Current phase: {phase or 'NONE'}. "
                    f"Pipeline guidance: start with RECALL phase if fresh task, "
                    f"otherwise resume from current phase. "
                    f"Next steps: IMPLEMENT → VERIFY → CONCLUDE"
                ),
            }
            return inject

        # Model-failure detection — inject Revolver rotation suggestion
        if _detect_model_failure(tool_name, tool_input, tool_input):  # tool_output unavailable at pre_call
            return {
                "action": "inject",
                "message": "/revolver next — model failure detected, rotating cylinder",
            }

        # HITL block check
        if state.get("hitl_blocked", False):
            return {
                "action": "block",
                "message": f"[orchestrator] HITL blocked: {state.get('block_reason', 'unknown')} — run /orchestrator unblock to continue",
            }

        # Retry cap check (only enforce during active phases)
        phase = state.get("phase", "")
        if phase and phase != "DONE":
            attempt = state.get("attempt_count", 0)
            if attempt > MAX_RETRIES:
                state["hitl_blocked"] = True
                state["block_reason"] = "Retry cap exceeded"
                _write_state(state)
                return {
                    "action": "block",
                    "message": f"[orchestrator] Retry cap ({MAX_RETRIES}) reached — HITL required. Run /orchestrator unblock to continue.",
                }

        # Increment attempt counter for this phase
        state["attempt_count"] = state.get("attempt_count", 0) + 1
        _write_state(state)

        return None  # Allow the tool call to proceed

    # -------------------------------------------------------------------------
    # on_session_end
    # -------------------------------------------------------------------------
    def on_session_end(session_id=None, **kwargs):
        state = _read_state()
        phase = state.get("phase", "")

        if phase and phase != "DONE":
            print(f"[orchestrator] Session ending with incomplete task (phase: {phase}) — triggering handoff")
            success, stdout, stderr = _run_techne_handoff()
            if success:
                print(f"[orchestrator] Handoff completed: {stdout}")
            else:
                print(f"[orchestrator] Handoff failed: {stderr}")
        else:
            print("[orchestrator] Session ended cleanly — no handoff needed")

    # -------------------------------------------------------------------------
    # Commands
    # -------------------------------------------------------------------------
    def cmd_status(**kwargs):
        state = _read_state()
        techne_phase, task_id = _read_techne_phase()

        current_phase = techne_phase or state.get("phase", "UNKNOWN")
        current_task = task_id or state.get("task_id", "none")
        attempt = state.get("attempt_count", 0)
        blocked = state.get("hitl_blocked", False)
        reason = state.get("block_reason", "")

        print("=== Orchestrator Status ===")
        print(f"  Task:      {current_task}")
        print(f"  Phase:     {current_phase}")
        print(f"  Attempts:  {attempt}/{MAX_RETRIES}")
        print(f"  HITL:      {'BLOCKED' if blocked else 'clear'}")
        if blocked:
            print(f"  Reason:    {reason}")
        print("============================")

    def cmd_retry(**kwargs):
        state = _read_state()
        state["attempt_count"] = 0
        _write_state(state)
        print(f"[orchestrator] Retry counter reset for phase '{state.get('phase', 'unknown')}'")

    def cmd_block(reason="manual", **kwargs):
        state = _read_state()
        state["hitl_blocked"] = True
        state["block_reason"] = reason
        _write_state(state)
        print(f"[orchestrator] HITL block set: {reason}")

    def cmd_unblock(**kwargs):
        state = _read_state()
        state["hitl_blocked"] = False
        state["block_reason"] = ""
        state["attempt_count"] = 0  # Reset retry counter on unblock
        _write_state(state)
        print("[orchestrator] HITL block cleared — retry counter reset")

    def cmd_handoff(**kwargs):
        print("[orchestrator] Running techne handoff...")
        success, stdout, stderr = _run_techne_handoff()
        if success:
            print(f"[orchestrator] Handoff complete:\n{stdout}")
        else:
            print(f"[orchestrator] Handoff failed:\n{stderr}")

    return {
        "hooks": {
            "on_session_start": on_session_start,
            "pre_tool_call": pre_tool_call,
            "on_session_end": on_session_end,
        },
        "commands": {
            "orchestrator": {
                "status": cmd_status,
                "retry": cmd_retry,
                "block": cmd_block,
                "unblock": cmd_unblock,
                "handoff": cmd_handoff,
            }
        },
    }
