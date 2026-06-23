"""
Plugin: techne — pipeline mode enabler with pre_tool_call enforcement.
- /techne: injects worker metaprompt, enables pipeline discipline
- /techne status: shows current pipeline state for active tasks
- /techne bypass: temporarily bypass pipeline enforcement (one write)
- pre_tool_call hook: blocks write_file/patch/terminal(git) without active task
"""

import json
import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

TECHNE_REPO = Path.home() / "repos" / "techne"
METAPROMPT_PATH = TECHNE_REPO / "docs" / "plans" / "techne-worker-metaprompt.md"
PIPELINE_SKILL_PATH = TECHNE_REPO / "SKILL.md"
REVOLVER_STATE_PATH = Path.home() / ".hermes" / ".revolver_state.json"

# Pipeline state
_pipeline_active = False
_bypass_count = 0  # allows N bypassed writes
TASKS_DB = TECHNE_REPO / ".techne" / "memory" / "tasks.db"

# Tools that modify files — blocked without active pipeline task
_WRITE_TOOLS = {"write_file", "patch"}

# Terminal commands that are destructive and should be blocked
_DESTRUCTIVE_TERMINAL_PATTERNS = [
    "git commit",
    "git push",
    "git merge",
    "git rebase",
    "git reset",
    "git cherry-pick",
    "rm -rf",
    "rm -r",
    "mv ",
    "cp ",
    "> ",
    ">> ",
    "| tee ",
]


def _has_active_task() -> bool:
    """Check if there's an active (non-DONE, non-FAILED) pipeline task."""
    db_path = TASKS_DB
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        row = conn.execute(
            """SELECT COUNT(*) FROM tasks
               WHERE status NOT IN ('DONE', 'FAILED', 'PENDING')
               AND status != ''"""
        ).fetchone()
        conn.close()
        count = row[0] if row else 0
        return count > 0
    except (sqlite3.Error, Exception):
        return False


def _is_destructive_tool(tool_name: str, tool_input: dict) -> bool:
    """Check if the tool call is a write/destructive operation."""
    if tool_name in _WRITE_TOOLS:
        return True
    if tool_name == "terminal":
        command = ""
        if isinstance(tool_input, dict):
            command = tool_input.get("command", "")
        elif isinstance(tool_input, str):
            command = tool_input
        command_lower = command.lower()
        for pattern in _DESTRUCTIVE_TERMINAL_PATTERNS:
            if pattern in command_lower:
                return True
    return False


def register(ctx) -> None:
    _pipeline_active_local = {"active": False}
    _bypass_local = {"count": 0}

    # ── pre_tool_call hook ───────────────────────────────────────────────
    @ctx.on("pre_tool_call")
    def on_pre_tool_call(
        tool_name: str = "",
        tool_input: dict = None,
        session_id: str = "",
        **kwargs,
    ) -> dict | None:
        """Block write tools if pipeline mode is active and no task exists."""
        if tool_input is None:
            tool_input = {}

        if not _pipeline_active_local["active"]:
            return None  # allow everything — pipeline not activated

        if _bypass_local["count"] > 0:
            _bypass_local["count"] -= 1
            logger.info(
                "[techne] Bypassing pipeline enforcement for %s "
                "(bypasses remaining: %d)",
                tool_name, _bypass_local["count"],
            )
            return None

        if not _is_destructive_tool(tool_name, tool_input):
            return None  # read-only tools always allowed

        if _has_active_task():
            return None  # active task → writes allowed

        # Block: no active pipeline task
        return {
            "action": "block",
            "message": (
                "Pipeline enforcement: no active task found.\n\n"
                "You must create a pipeline task before writing files. "
                "Run:\n"
                "  1. Load the pipeline skill: /skill techne\n"
                "  2. Create a task via task_db.create_task()\n"
                "  3. Drive through RECALL → IMPLEMENT → ... → DONE\n\n"
                f"To bypass this once: /techne bypass\n"
                f"To disable pipeline mode: /techne off"
            ),
        }

    # ── Hooks: session lifecycle ──────────────────────────────────────────
    @ctx.on("on_session_start")
    def on_session_start(session_id: str = "") -> None:
        """Reset pipeline state on new session."""
        _pipeline_active_local["active"] = False
        _bypass_local["count"] = 0

    @ctx.on("on_session_end")
    def on_session_end(session_id: str = "") -> None:
        """Clean up pipeline state."""
        _pipeline_active_local["active"] = False
        _bypass_local["count"] = 0

    @ctx.on("on_session_reset")
    def on_session_reset(session_id: str = "") -> None:
        """Reset on session reset."""
        _pipeline_active_local["active"] = False
        _bypass_local["count"] = 0

    # ── Command: /techne ─────────────────────────────────────────────────
    def _cmd_techne(args: str = "") -> str:
        """Activate pipeline mode or handle subcommands."""
        nonlocal _pipeline_active_local, _bypass_local
        args_lower = args.strip().lower() if args else ""

        if args_lower == "off":
            _pipeline_active_local["active"] = False
            _bypass_local["count"] = 0
            return "[techne] Pipeline mode deactivated. Tool enforcement disabled."

        if args_lower == "bypass":
            _bypass_local["count"] = 3  # allow 3 bypasses
            return (
                "[techne] Bypass granted for 3 write operations. "
                "Use sparingly — create a pipeline task instead."
            )

        if args_lower in ("status", "state"):
            lines = ["**Techne Pipeline Status**"]
            lines.append(f"Pipeline active: {'✅' if _pipeline_active_local['active'] else '❌'}")
            lines.append(f"Bypasses remaining: {_bypass_local['count']}")

            db_path = TASKS_DB
            if db_path.exists():
                try:
                    conn = sqlite3.connect(str(db_path))
                    row = conn.execute(
                        "SELECT status, COUNT(*) FROM tasks GROUP BY status"
                    ).fetchall()
                    conn.close()
                    if row:
                        lines.append("**Task statuses:**")
                        for status, count in row:
                            lines.append(f"  {status}: {count}")
                    else:
                        lines.append("No tasks found.")
                except sqlite3.Error:
                    lines.append("⚠️ Could not read task DB")
            else:
                lines.append("ℹ️ No task database found")

            if METAPROMPT_PATH.exists():
                lines.append(f"✓ Worker metaprompt present")
            else:
                lines.append("⚠️ Worker metaprompt not found")

            return "\n".join(lines)

        # Default: activate pipeline mode
        if not METAPROMPT_PATH.exists():
            return (
                "[techne] Worker metaprompt not found at "
                f"{METAPROMPT_PATH}. Clone techne repo first."
            )

        metaprompt = METAPROMPT_PATH.read_text()
        if not metaprompt.strip():
            return "[techne] Worker metaprompt is empty. Cannot activate pipeline mode."

        line_count = len(metaprompt.split("\n"))
        _pipeline_active_local["active"] = True
        _bypass_local["count"] = 0

        # Check revolver state for delegation info
        revolver_info = ""
        if REVOLVER_STATE_PATH.exists():
            try:
                state = json.loads(REVOLVER_STATE_PATH.read_text())
                delegations = state.get("delegations", [])
                if delegations:
                    delegation_summary = ", ".join(
                        f"{d.get('name', 'unnamed')}" for d in delegations[-3:]
                    )
                    revolver_info = (
                        f"\nRevolver delegation config ({len(delegations)} total, "
                        f"recent: {delegation_summary}): active."
                    )
            except (json.JSONDecodeError, OSError):
                revolver_info = "\nRevolver state file present but unreadable."

        ctx.inject_message(
            f"**Techne Pipeline Mode activated.**\n\n"
            f"Loaded worker metaprompt ({line_count} lines).\n"
            f"All code changes must go through the 11-phase pipeline:\n"
            f"RECALL → IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY "
            f"→ EVAL → RETRO → CONCLUDE → REFRESH_CONTEXT → DONE\n\n"
            f"⚠️ **Write enforcement active:** write_file, patch, and destructive "
            f"terminal commands (git commit/push, rm, mv, etc.) are BLOCKED "
            f"unless a pipeline task is active.\n\n"
            f"Pre-task checklist:\n"
            f"1. Create a task via task_db.create_task()\n"
            f"2. Drive through pipeline phases\n"
            f"3. To bypass enforcement: /techne bypass\n"
            f"4. To disable: /techne off"
            f"{revolver_info}",
            role="assistant",
        )

        return (
            f"[techne] Pipeline mode active with write enforcement. "
            f"Worker metaprompt loaded ({line_count} lines). "
            f"Use /techne status to check state, /techne bypass for exceptions."
        )

    # ── Commands ─────────────────────────────────────────────────────────
    ctx.register_command(
        "techne",
        _cmd_techne,
        description="Activate Techne pipeline mode — enables write enforcement via pre_tool_call hook",
    )

    logger.info(
        "[techne] Registered: /techne (pipeline + write enforcement), "
        "pre_tool_call hook (blocks writes without active task)"
    )
