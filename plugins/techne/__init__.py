"""
Plugin: techne — pipeline mode enabler with pre_tool_call enforcement.

/techne             — activate pipeline mode with write enforcement
/techne status      — show enforcement state + block log + task DB snapshot
/techne bypass      — grant 3 bypass writes for exceptions
/techne off         — disable enforcement

pre_tool_call hook  — blocks write_file/patch/terminal(git/rm/mv/cp)
                      unless an active pipeline task exists.
                      Allows writes to .techne/, /tmp/, and log paths
                      regardless of task state.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────

HOME = Path.home()
TECHNE_REPO = HOME / "repos" / "techne"
METAPROMPT_PATH = TECHNE_REPO / "docs" / "plans" / "techne-worker-metaprompt.md"
REVOLVER_STATE_PATH = HOME / ".hermes" / ".revolver_state.json"

# ── Hardened terminal patterns ───────────────────────────────────────────────
# Uses regex word boundaries to avoid false matches on substrings.
# Each entry: (pattern_name, compiled_regex, description)

_TERMINAL_BLOCK_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("git_commit", re.compile(r"\bgit\s+commit\b", re.I), "git commit"),
    ("git_push", re.compile(r"\bgit\s+push\b", re.I), "git push"),
    ("git_merge", re.compile(r"\bgit\s+merge\b", re.I), "git merge"),
    ("git_rebase", re.compile(r"\bgit\s+rebase\b", re.I), "git rebase"),
    ("git_reset", re.compile(r"\bgit\s+reset\b", re.I), "git reset (destructive)"),
    ("git_cherry_pick", re.compile(r"\bgit\s+cherry-pick\b", re.I), "git cherry-pick"),
    ("rm_rf", re.compile(r"\brm\s+-rf\b", re.I), "recursive force delete"),
    ("rm_r", re.compile(r"\brm\s+-r\b", re.I), "recursive delete"),
    ("mv", re.compile(r"\bmv\s+", re.I), "move (may overwrite)"),
    ("cp_force", re.compile(r"\bcp\s+-[a-zA-Z]*f", re.I), "force copy"),
    ("redirect_out", re.compile(r"(?<!\w)>(?!>)\s*/", re.I), "shell redirect to /path"),
    ("redirect_append", re.compile(r">>\s*/", re.I), "shell append redirect to /path"),
    ("tee_write", re.compile(r"\btee\s+", re.I), "tee write to file"),
    ("dd_write", re.compile(r"\bdd\s+if=", re.I), "dd (raw device write)"),
    ("chmod_recursive", re.compile(r"\bchmod\s+-R\b", re.I), "recursive chmod"),
    ("chown", re.compile(r"\bchown\b", re.I), "change owner"),
]

# File-write tools — blocked without active task
_WRITE_TOOLS = {"write_file", "patch"}

# Paths that are ALWAYS allowed regardless of task state.
# A path matches if it STARTS WITH any of these prefixes.
_ALLOWED_PATH_PREFIXES = (
    "/tmp/",
    str(HOME / ".hermes" / "logs"),
    str(HOME / ".hermes" / "audio_cache"),
    str(HOME / ".hermes" / "state.db"),
    str(HOME / ".hermes" / "sessions"),
    "/dev/null",
    "/proc/",
    "/sys/",
)

# Project-internal paths that are always allowed (context amortization, logs)
_TECHNE_ALWAYS_ALLOWED = {".techne", ".hermes"}


def _is_allowed_path(path_str: str) -> bool:
    """Check if a file path is always-allowed regardless of task state."""
    if not path_str:
        return False
    # Absolute path prefix check
    if path_str.startswith(_ALLOWED_PATH_PREFIXES):
        return True
    # Relative paths containing .techne/ or .hermes/
    path_parts = Path(path_str).parts
    for part in path_parts:
        if part in _TECHNE_ALWAYS_ALLOWED:
            return True
    return False


def _find_tasks_db() -> Path | None:
    """Walk up from CWD to find a project's tasks.db.

    Checks:
    1. CWD walk-up: look for <.techne/memory/tasks.db> in each parent
    2. Fallback: ~/repos/techne/.techne/memory/tasks.db
    """
    cwd = Path.cwd().resolve()
    for parent in [cwd] + list(cwd.parents):
        candidate = parent / ".techne" / "memory" / "tasks.db"
        if candidate.exists():
            return candidate
    # Fallback
    fallback = TECHNE_REPO / ".techne" / "memory" / "tasks.db"
    if fallback.exists():
        return fallback
    return None


def _has_active_task(db_path: Path | None) -> bool:
    """Check if there's an active (in-progress) pipeline task.

    A task is active if it has been started (status is past PENDING
    but not yet terminal). PENDING-only tasks don't count — they
    haven't been claimed by any agent yet.
    """
    if db_path is None or not db_path.exists():
        return False
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        row = conn.execute(
            """SELECT COUNT(*) FROM tasks
               WHERE status IN ('IN_PROGRESS', 'IMPLEMENTED',
                                'REVIEWED', 'VERIFIED', 'BLOCKED')"""
        ).fetchone()
        return row[0] > 0 if row else False
    except sqlite3.Error:
        return False
    finally:
        if conn:
            conn.close()


def _count_tasks_by_status(db_path: Path) -> list[tuple[str, int]] | None:
    """Return (status, count) pairs, or None on error."""
    if not db_path.exists():
        return None
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM tasks GROUP BY status"
        ).fetchall()
        return [(r[0], r[1]) for r in rows] if rows else []
    except sqlite3.Error:
        return None
    finally:
        if conn:
            conn.close()


def _is_write_file(tool_name: str, tool_input: dict) -> tuple[bool, str]:
    """Check if a tool call is a write operation.

    Returns (is_destructive, reason).
    """
    # Direct write tools
    if tool_name in _WRITE_TOOLS:
        # Check if the target path is in the allowlist
        path = ""
        if isinstance(tool_input, dict):
            path = tool_input.get("path", tool_input.get("file_path", ""))
            if tool_input.get("cross_profile", False):
                return (False, "")  # cross_profile writes are admin-only
        if path and _is_allowed_path(path):
            return (False, "")
        return (True, f"file write to {path}" if path else "file write")

    # Terminal with destructive commands
    if tool_name == "terminal":
        command = ""
        if isinstance(tool_input, dict):
            command = tool_input.get("command", "")
        elif isinstance(tool_input, str):
            command = tool_input
        if not command.strip():
            return (False, "")
        for name, pattern, desc in _TERMINAL_BLOCK_PATTERNS:
            if pattern.search(command):
                return (True, f"{desc} in: {command[:100]}")
        return (False, "")

    # execute_code containing write_file calls
    if tool_name == "execute_code":
        code = ""
        if isinstance(tool_input, dict):
            code = tool_input.get("code", "")
        if "write_file" in code:
            return (True, "write_file called inside execute_code")

    return (False, "")


def register(ctx) -> None:
    # ── Plugin state ──────────────────────────────────────────────────────
    _state = {
        "active": False,
        "bypass_count": 0,
        "block_log": [],  # list of (tool_name, reason, count)
        "total_blocks": 0,
        "db_not_found_warned": False,
    }

    def _log_block(tool_name: str, reason: str) -> None:
        """Record a blocked tool call for audit."""
        _state["total_blocks"] += 1
        _state["block_log"].append({
            "tool": tool_name,
            "reason": reason[:80],
        })
        # Keep log capped at 50
        if len(_state["block_log"]) > 50:
            _state["block_log"] = _state["block_log"][-50:]

    # ── pre_tool_call hook ────────────────────────────────────────────────
    @ctx.on("pre_tool_call")
    def on_pre_tool_call(
        tool_name: str = "",
        tool_input: dict = None,
        session_id: str = "",
        **kwargs,
    ) -> dict | None:
        """Block destructive tools if pipeline mode is active and no task exists."""
        if tool_input is None:
            tool_input = {}

        if not _state["active"]:
            return None  # pipeline not activated — allow everything

        if _state["bypass_count"] > 0:
            _state["bypass_count"] -= 1
            logger.info(
                "[techne] Bypass used for %s (remaining: %d)",
                tool_name, _state["bypass_count"],
            )
            return None

        # Check if this tool call is destructive
        is_destructive, reason = _is_write_file(tool_name, tool_input)
        if not is_destructive:
            return None

        # Find active task DB
        db_path = _find_tasks_db()

        # If no DB found in first 3 blocks, warn gracefully
        if db_path is None:
            if _state["total_blocks"] < 3:
                _log_block(tool_name, reason)
                return {
                    "action": "block",
                    "message": (
                        "Pipeline enforcement: no task database found.\n\n"
                        "Could not find `.techne/memory/tasks.db` in the current "
                        "project or the techne repo. Make sure you're working in "
                        "a project with techne pipeline set up.\n\n"
                        f"To bypass: /techne bypass\n"
                        f"To disable: /techne off"
                    ),
                }
            else:
                # After 3 blocks, allow — something is misconfigured
                logger.warning(
                    "[techne] Allowing %s despite no DB (block #%d)",
                    tool_name, _state["total_blocks"],
                )
                return None

        if _has_active_task(db_path):
            return None  # active task → writes allowed

        # Block
        _log_block(tool_name, reason)
        return {
            "action": "block",
            "message": (
                "Pipeline enforcement: no active task found.\n\n"
                "All file writes must go through a pipeline task. "
                "Create one:\n"
                "  1. /techne (if not already loaded)\n"
                "  2. task_db.create_task(title=\"...\", discipline=\"tdd\")\n"
                "  3. Drive through RECALL → IMPLEMENT → … → DONE\n\n"
                "Temporary bypass: /techne bypass (3 writes)\n"
                "Disable enforcement: /techne off\n"
                f"Active task DB: {db_path}"
            ),
        }

    # ── Session lifecycle hooks ───────────────────────────────────────────
    @ctx.on("on_session_start")
    def on_session_start(session_id: str = "") -> None:
        _state["active"] = False
        _state["bypass_count"] = 0
        _state["block_log"].clear()
        _state["total_blocks"] = 0
        _state["db_not_found_warned"] = False

    @ctx.on("on_session_end")
    def on_session_end(session_id: str = "") -> None:
        _state["active"] = False

    @ctx.on("on_session_reset")
    def on_session_reset(session_id: str = "") -> None:
        _state["active"] = False
        _state["bypass_count"] = 0
        _state["block_log"].clear()
        _state["total_blocks"] = 0
        _state["db_not_found_warned"] = False

    # ── /techne command ───────────────────────────────────────────────────
    def _cmd_techne(args: str = "") -> str:
        """Activate pipeline mode or handle subcommands."""
        args_lower = args.strip().lower() if args else ""

        if args_lower == "off":
            _state["active"] = False
            _state["bypass_count"] = 0
            return "[techne] Pipeline mode deactivated. Tool enforcement disabled."

        if args_lower == "bypass":
            _state["bypass_count"] = 3
            return (
                "[techne] Bypass granted for 3 write operations. "
                "Use sparingly — create a pipeline task instead."
            )

        if args_lower == "reset-block-log":
            _state["block_log"].clear()
            _state["total_blocks"] = 0
            return "[techne] Block log cleared."

        if args_lower in ("status", "state"):
            lines = ["**Techne Pipeline Status**"]
            lines.append(
                f"Pipeline active: {'✅' if _state['active'] else '❌'}"
            )
            lines.append(f"Bypasses remaining: {_state['bypass_count']}")
            lines.append(f"Total blocks this session: {_state['total_blocks']}")

            # Task DB
            db_path = _find_tasks_db()
            if db_path:
                lines.append(f"Task DB: `{db_path}`")
                statuses = _count_tasks_by_status(db_path)
                if statuses is not None:
                    lines.append("**Task statuses:**")
                    for status, count in statuses:
                        lines.append(f"  {status}: {count}")
                else:
                    lines.append("⚠️ Could not read task DB")
            else:
                lines.append("ℹ️ No task database found (no active project)")

            # Block log (last 10)
            if _state["block_log"]:
                lines.append("**Recent blocks:**")
                for entry in _state["block_log"][-10:]:
                    lines.append(
                        f"  ⛔ {entry['tool']} — {entry['reason'][:60]}"
                    )

            # Resources
            if METAPROMPT_PATH.exists():
                lines.append("✓ Worker metaprompt present")
            else:
                lines.append("⚠️ Worker metaprompt not found")

            return "\n".join(lines)

        # ── Default: activate ─────────────────────────────────────────────
        if not METAPROMPT_PATH.exists():
            return (
                "[techne] Worker metaprompt not found at "
                f"{METAPROMPT_PATH}. Clone techne repo first."
            )

        metaprompt = METAPROMPT_PATH.read_text()
        if not metaprompt.strip():
            return "[techne] Worker metaprompt is empty. Cannot activate pipeline mode."

        line_count = len(metaprompt.split("\n"))
        _state["active"] = True
        _state["bypass_count"] = 0

        # Check if a tasks.db is findable
        db_path = _find_tasks_db()
        db_status = ""
        if db_path:
            db_status = (
                f"\nTask DB found at `{db_path}` — "
                f"{'active tasks' if _has_active_task(db_path) else 'no active tasks'}."
            )
        else:
            db_status = (
                "\n⚠️ No task database found. Writes will be blocked after "
                "the first 3 attempts until a DB is available."
            )

        # Revolver state
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
                revolver_info = "\nRevolver state present but unreadable."

        ctx.inject_message(
            f"**Techne Pipeline Mode activated.**\n\n"
            f"Loaded worker metaprompt ({line_count} lines).{db_status}\n\n"
            f"⚠️ **Write enforcement active.** The following are BLOCKED "
            f"unless a pipeline task is active:\n"
            f"  • `write_file` / `patch` — except to `.techne/` and `/tmp/`\n"
            f"  • `terminal(git commit/push/merge/reset)`\n"
            f"  • `terminal(rm -rf, mv, cp -f)`\n"
            f"  • `execute_code(write_file(...))`\n\n"
            f"Commands:\n"
            f"  `/techne status` — show state + block log\n"
            f"  `/techne bypass` — grant 3 bypass writes\n"
            f"  `/techne off` — disable enforcement{revolver_info}",
            role="assistant",
        )

        return (
            f"[techne] Pipeline mode active with write enforcement. "
            f"Use /techne status to check state, /techne bypass for exceptions."
        )

    # ── Register commands ─────────────────────────────────────────────────
    ctx.register_command(
        "techne",
        _cmd_techne,
        description="Activate Techne pipeline mode — write enforcement, status, bypass, off",
    )

    logger.info(
        "[techne] Registered: /techne (enforcement: %d patterns, "
        "path allowlist, execode detection, block audit)",
        len(_TERMINAL_BLOCK_PATTERNS),
    )
