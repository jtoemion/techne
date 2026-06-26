"""
Plugin: techne-plugin — delegates enforcement to techne gate CLI.

pre_tool_call hook:
  - On IMPLEMENT phase write: run `techne gate hashline .techne/loop/diff.txt`
  - On any write (write_file/patch): run `techne gate forbidden <content>`
  - Run `techne gate audit <event_json>` with gate outcome
  - Write RL event to .techne/events/rl.jsonl (append JSON line)

Commands:
  /techne-plugin status — show phase, block count, RL events
  /techne-plugin off    — disable enforcement for this session
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────

HOME = Path.home()
TECHNE_REPO = HOME / "repos" / "techne"
TECHNE_CLI_MODULE = "techne_cli.main"

# Write tools that trigger gate checks
_WRITE_TOOLS = {"write_file", "patch"}


def _find_techne_root() -> Path | None:
    """Walk up from CWD to find .techne/ directory."""
    cwd = Path.cwd().resolve()
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".techne").is_dir():
            return parent
        if parent == parent.parent:
            break
    return None


def _read_loop_state() -> tuple[str, str, dict | None]:
    """Read .techne/loop/state.json.

    Returns (phase, task_id, raw_state_dict) or ("", "", None) if no state.
    """
    root = _find_techne_root()
    if root is None:
        return ("", "", None)

    state_file = root / ".techne" / "loop" / "state.json"
    if not state_file.exists():
        return ("", "", None)

    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        phase = data.get("phase", "").upper()
        task_id = data.get("task_id", "")
        return (phase, task_id, data)
    except (json.JSONDecodeError, OSError):
        return ("", "", None)


def _find_diff_path() -> Path | None:
    """Find .techne/loop/diff.txt."""
    root = _find_techne_root()
    if root is None:
        return None
    diff = root / ".techne" / "loop" / "diff.txt"
    return diff if diff.exists() else None


def _ensure_events_dir() -> Path | None:
    """Ensure .techne/events/ exists and return the path."""
    root = _find_techne_root()
    if root is None:
        return None
    events_dir = root / ".techne" / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    return events_dir


# ── Techne gate CLI delegation ───────────────────────────────────────────────


def _run_gate_gate(
    subcommand: str,
    args: list[str],
    cwd: Path | None = None,
    input_text: str | None = None,
) -> tuple[int, str, str]:
    """Run `python3 -m techne_cli.main gate <subcommand> <args>`.

    Returns (returncode, stdout, stderr).
    """
    cmd = [
        "python3",
        "-m",
        TECHNE_CLI_MODULE,
        "gate",
        subcommand,
        *args,
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd or TECHNE_REPO,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return (result.returncode, result.stdout, result.stderr)
    except subprocess.TimeoutExpired:
        return (-1, "", "gate command timed out after 30s")
    except Exception as e:
        return (-1, "", str(e))


def _gate_hashline(diff_path: Path) -> tuple[bool, str]:
    """Run `techne gate hashline <diff_path>`.

    Returns (passed, message).
    """
    returncode, stdout, stderr = _run_gate_gate(
        "hashline",
        [str(diff_path)],
        cwd=TECHNE_REPO,
    )
    if returncode == 0:
        return (True, stdout.strip() if stdout else "hashline OK")
    return (False, (stderr or stdout).strip())


def _gate_forbidden(content: str) -> tuple[bool, str]:
    """Run `techne gate forbidden` with content on stdin.

    Returns (passed, message).
    """
    returncode, stdout, stderr = _run_gate_gate(
        "forbidden",
        [],
        cwd=TECHNE_REPO,
        input_text=content,
    )
    if returncode == 0:
        return (True, stdout.strip() if stdout else "forbidden OK")
    return (False, (stderr or stdout).strip())


def _gate_audit(event_json: str) -> tuple[bool, str]:
    """Run `techne gate audit <json_event>`.

    Returns (passed, message).
    """
    returncode, stdout, stderr = _run_gate_gate(
        "audit",
        [event_json],
        cwd=TECHNE_REPO,
    )
    if returncode == 0:
        return (True, stdout.strip() if stdout else "audit OK")
    return (False, (stderr or stdout).strip())


# ── RL event logging ─────────────────────────────────────────────────────────


def _write_rl_event(
    phase: str,
    gate_name: str,
    passed: bool,
    tool_name: str,
    path: str,
) -> None:
    """Append an RL event to .techne/events/rl.jsonl."""
    events_dir = _ensure_events_dir()
    if events_dir is None:
        return

    event = {
        "ts": time.time(),
        "phase": phase,
        "gate": gate_name,
        "reward": 1.0 if passed else -1.0,
        "advantage": 0.5 if passed else -0.5,
        "tool": tool_name,
        "path": path,
    }

    try:
        rl_path = events_dir / "rl.jsonl"
        with open(rl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except OSError as e:
        logger.warning("[techne-plugin] could not write RL event: %s", e)


# ── Plugin state ─────────────────────────────────────────────────────────────


def register(ctx) -> None:
    _state = {
        "enforcement_active": True,
        "total_blocks": 0,
        "gate_results": [],  # list of {"gate", "passed", "tool", "path"}
    }

    def _log_gate_result(gate: str, passed: bool, tool: str, path: str) -> None:
        _state["total_blocks"] += 0 if passed else 1
        _state["gate_results"].append({
            "gate": gate,
            "passed": passed,
            "tool": tool,
            "path": path,
        })
        if len(_state["gate_results"]) > 50:
            _state["gate_results"] = _state["gate_results"][-50:]

    # ── pre_tool_call hook ─────────────────────────────────────────────────
    @ctx.on("pre_tool_call")
    def on_pre_tool_call(
        tool_name: str = "",
        tool_input: dict = None,
        session_id: str = "",
        **kwargs,
    ) -> dict | None:
        """Intercept write tools, run techne gate checks, return block if failed."""
        if tool_input is None:
            tool_input = {}

        if not _state["enforcement_active"]:
            return None

        # Only gate write tools
        if tool_name not in _WRITE_TOOLS:
            return None

        # Extract content and path
        content = ""
        path = ""
        if isinstance(tool_input, dict):
            content = tool_input.get("content", tool_input.get("patch", ""))
            path = tool_input.get("path", tool_input.get("file_path", ""))
        elif isinstance(tool_input, str):
            content = tool_input

        # Read current phase
        phase, task_id, _ = _read_loop_state()

        # ── 1. hashline gate (IMPLEMENT phase only) ─────────────────────────
        hashline_passed = True
        hashline_msg = "not checked (not IMPLEMENT phase)"
        if phase == "IMPLEMENT":
            diff_path = _find_diff_path()
            if diff_path is not None:
                hashline_passed, hashline_msg = _gate_hashline(diff_path)
                _log_gate_result("hashline", hashline_passed, tool_name, str(diff_path))

                # Audit event
                audit_event = json.dumps({
                    "gate": "hashline",
                    "passed": hashline_passed,
                    "tool": tool_name,
                    "path": str(diff_path),
                    "phase": phase,
                })
                _gate_audit(audit_event)
                _write_rl_event(phase, "hashline", hashline_passed, tool_name, str(diff_path))

                if not hashline_passed:
                    return {
                        "action": "block",
                        "message": (
                            f"[techne-plugin] hashline FAILED: {hashline_msg}\n"
                            f"Phase: {phase}\n"
                            f"Fix: Ensure diff is linear before writing.\n"
                        ),
                    }
            else:
                # No diff.txt — warn but allow
                logger.warning("[techne-plugin] IMPLEMENT phase but no diff.txt found")

        # ── 2. forbidden gate (any write) ───────────────────────────────────
        if content:
            forbidden_passed, forbidden_msg = _gate_forbidden(content)
            _log_gate_result("forbidden", forbidden_passed, tool_name, path)

            # Audit event
            audit_event = json.dumps({
                "gate": "forbidden",
                "passed": forbidden_passed,
                "tool": tool_name,
                "path": path,
                "phase": phase,
            })
            _gate_audit(audit_event)
            _write_rl_event(phase, "forbidden", forbidden_passed, tool_name, path)

            if not forbidden_passed:
                return {
                    "action": "block",
                    "message": (
                        f"[techne-plugin] forbidden pattern detected: {forbidden_msg}\n"
                        f"Tool: {tool_name}\n"
                        f"Path: {path}\n"
                        f"Fix: Remove forbidden content before writing.\n"
                    ),
                }

        return None

    # ── on_session_start ───────────────────────────────────────────────────
    @ctx.on("on_session_start")
    def on_session_start(session_id: str = "") -> None:
        _state["enforcement_active"] = True
        _state["total_blocks"] = 0
        _state["gate_results"].clear()

        # Auto-detect .techne/ root
        root = _find_techne_root()
        if root is not None:
            ctx.inject_message(
                "╔══════════════════════════════════════════╗\n"
                "║  TECHNE-PLUGIN ACTIVE                   ║\n"
                "║  Delegating gates to techne gate CLI    ║\n"
                "║  Commands:                              ║\n"
                "║    /techne-plugin status                ║\n"
                "║    /techne-plugin off                   ║\n"
                "╚══════════════════════════════════════════╝",
                role="assistant",
            )
        else:
            ctx.inject_message(
                "[techne-plugin] No .techne/ directory found — enforcement passive.",
                role="assistant",
            )

    # ── Commands ───────────────────────────────────────────────────────────
    def _cmd_techne_plugin(args: str = "") -> str:
        """Handle /techne-plugin command and subcommands."""
        args_lower = args.strip().lower() if args else ""

        if args_lower == "off":
            _state["enforcement_active"] = False
            return "[techne-plugin] Enforcement disabled for this session."

        if args_lower in ("status", "state", ""):
            lines = ["**techne-plugin status**"]
            lines.append(
                f"Enforcement active: {'✅' if _state['enforcement_active'] else '❌'}"
            )
            lines.append(f"Total blocks this session: {_state['total_blocks']}")

            # Phase info
            phase, task_id, _ = _read_loop_state()
            if phase:
                lines.append(f"Loop phase: **{phase}** (task: {task_id})")
            else:
                lines.append("Loop phase: none (no .techne/loop/state.json)")

            # RL events file
            events_dir = _ensure_events_dir()
            if events_dir is not None:
                rl_path = events_dir / "rl.jsonl"
                if rl_path.exists():
                    try:
                        lines_count = len(rl_path.read_text(encoding="utf-8").splitlines())
                        lines.append(f"RL events file: {lines_count} entries at {rl_path}")
                    except OSError:
                        lines.append(f"RL events file: present but unreadable")
                else:
                    lines.append("RL events file: not yet created")
            else:
                lines.append("RL events file: no .techne/ directory found")

            # Last gate results
            if _state["gate_results"]:
                lines.append("**Recent gate results:**")
                for entry in _state["gate_results"][-10:]:
                    icon = "✅" if entry["passed"] else "⛔"
                    lines.append(
                        f"  {icon} {entry['gate']} — {entry['tool']} → {entry['path'] or '(no path)'}"
                    )

            return "\n".join(lines)

        return f"[techne-plugin] Unknown subcommand: {args!r}. Use: status, off"

    ctx.register_command(
        "techne-plugin",
        _cmd_techne_plugin,
        description="Techne enforcement control — status, off",
    )

    logger.info("[techne-plugin] Registered: /techne-plugin (status, off), pre_tool_call gate delegation")
