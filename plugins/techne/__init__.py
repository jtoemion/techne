"""Plugin: techne — pipeline mode enforcer with pre_tool_call enforcement.
       Enhanced: phase-aware artifact enforcement + tool-count tracking.
       Production: delegated to phase_guard.py for write enforcement,
       persistent blocked.log, state.json-based task activation, phase timeout.

/techne             — activate pipeline mode with write enforcement
/techne status      — show enforcement state + block log + task DB snapshot
/techne bypass      — grant 3 bypass writes for exceptions
/techne off         — disable enforcement

pre_tool_call hook  — blocks write_file/patch/terminal(git/rm/mv/cp)
                      unless an active pipeline task exists.
                      Delegates path checks to harness/plugins/phase_guard.py
                      - Reads .techne/loop/state.json for current phase
                      - Blocks writes to artifact paths that don't match phase
                      - Blocks writes to .techne/audit/ entirely
                      - Forces ./next after tool-count threshold
                      - Phase timeout: blocks if no ./next call > timeout_min
                      - Logs every block to .techne/audit/blocked.log
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

# Import phase_guard from the techne repo — bypass harness/plugins/__init__.py
# to avoid triggering the full plugin chain (builtin_gates → gates import)
_PHASE_GUARD_PATH = TECHNE_REPO / "harness" / "plugins" / "phase_guard.py"
_HAS_PHASE_GUARD = False
if _PHASE_GUARD_PATH.exists():
    import importlib.util as _importlib_util
    _spec = _importlib_util.spec_from_file_location("_techne_phase_guard", str(_PHASE_GUARD_PATH))
    _pg_mod = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_pg_mod)
    _pg_check_write = _pg_mod.check_write_allowed
    _pg_log_blocked = _pg_mod.log_blocked
    _pg_get_blocked_log = _pg_mod.get_blocked_log
    _HAS_PHASE_GUARD = True
    logger.info("[techne] phase_guard loaded from %s", _PHASE_GUARD_PATH)

# Phase artifact map — sourced from phase_guard.py (canonical)
# When phase_guard is loaded, use its map. Fallback for inline enforcement.
if _HAS_PHASE_GUARD:
    _PHASE_ARTIFACT_MAP = _pg_mod._PHASE_ARTIFACT_MAP
else:
    _PHASE_ARTIFACT_MAP = {
        "RECALL": "recall.txt",
        "IMPLEMENT": None,
        "VERIFY": "test_output.txt",
        "CONCLUDE": "conclude.txt",
        "DONE": None,
    }

# Tool-count thresholds per phase — after this many tools, force ./next call
_PHASE_TOOL_LIMITS = {
    "RECALL":   15,
    "IMPLEMENT": 25,
    "VERIFY":    8,
    "CONCLUDE":  10,
    "DONE":      0,  # no limit — task is finished
}

# Default phase timeout (minutes) — stall detection in the plugin itself
_DEFAULT_PHASE_TIMEOUT_MIN = 30

# Commands that count as "./next" calls (phase transitions)
_NEXT_PATTERNS = [
    re.compile(r"python3\s+.*next\.py", re.I),
    re.compile(r"\./next\b", re.I),
    re.compile(r"bash\s+.*next\.", re.I),
]

# ── Hardened terminal patterns ───────────────────────────────────────────────

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
    ("sed_inplace", re.compile(r"\bsed\s+.*-i\b", re.I), "sed -i (in-place edit)"),
    ("install_write", re.compile(r"\binstall\s+", re.I), "install (copy with perms)"),
    ("bash_dev_tcp", re.compile(r"/dev/(tcp|udp)/", re.I), "/dev/tcp reverse shell"),
    ("nc_shell", re.compile(r"\bnc\s+.*\-[eč]\b", re.I), "netcat reverse shell"),
    ("bash_i_redirect", re.compile(r"bash\s+.*\-i\s+.*>&", re.I), "bash -i reverse shell"),
    ("exec_redir_shell", re.compile(r"exec\s+\d+<>", re.I), "exec redirect reverse shell"),
    ("socat_shell", re.compile(r"\bsocat\s+.*(?:exec:|system:)", re.I), "socat reverse shell"),
    ("python_revshell", re.compile(r"(?:socket\.connect|pty\.spawn)\s*\(.*\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", re.I), "python reverse shell"),
    ("telnet_shell", re.compile(r"\btelnet\s+\S+\s+\d+\s*[|&]", re.I), "telnet reverse shell"),
    ("curl_bash", re.compile(r"\bcurl\s+.*[||]\s*(?:bash|sh)\b", re.I), "curl-to-bash pipe"),
]

# Additional source file extensions to detect shell-level writes
_SOURCE_FILE_EXTS = re.compile(
    r"\.(?:py|js|ts|jsx|tsx|json|ya?ml|toml|md|css|scss|sass|less|html|vue|svelte"
    r"|env|txt|cfg|ini|conf|xml|svg|sh|bash|zsh|fish|rb|go|rs|c|cpp|h|hpp"
    r"|java|kt|swift|php|pl|lua|sql|graphql|prisma|proto|gradle|makefile|dockerfile)$",
    re.I,
)


def _is_shell_source_write(command: str) -> tuple[bool, str]:
    """Check if a terminal command writes to a source file via shell redirect.

    Detects patterns like:
      echo '...' > file.py
      cat > file.py << '...'
      printf '...' > file.ts
      somecommand > src/app.js
      >> src/data.json

    Returns (is_write, reason) or (False, '').
    """
    # Strip obvious non-write redirects (devnull, pipes, stderr merge)
    stripped = re.sub(r'>\s*/dev/null\b', '', command, flags=re.I)

    # Skip redirects to /tmp/ and .hermes/ paths
    if re.search(r'>\s*(/tmp/|~/.hermes)', stripped, re.I):
        return (False, '')

    # Find all redirect targets (> path or >> path)
    matches = re.findall(r'(?:>|>>)\s*((?:\./)?(?:[^\s;|&`(){}<>]+))', stripped)
    for target in matches:
        target = target.strip()
        # Skip if target contains .techne/ or .hermes/
        if '.techne' in target or '.hermes' in target:
            continue
        # Check if target has a source file extension
        if _SOURCE_FILE_EXTS.search(target):
            return (True, f'shell redirect write to {target}')

    # Check cat/echo/printf heredoc patterns
    heredoc = re.search(r'\b(?:cat|echo|printf)\s+.*(?:>\s*|<<\s*)([^\s;|&`(){}<>]+\.\w+)', command, re.I)
    if heredoc:
        target = heredoc.group(1)
        if '.techne' not in target and '.hermes' not in target:
            return (True, f'shell write via {command[:60]}...')

    return (False, '')


# File-write tools
_WRITE_TOOLS = {"write_file", "patch"}

# Always-allowed paths
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

_TECHNE_ALWAYS_ALLOWED = {".techne", ".hermes"}

# ── Loop state tracking ─────────────────────────────────────────────────────

_LAST_PHASE = ""       # phase tracked on last pre_tool_call
_TOOL_COUNT = 0        # tool calls in current phase
_PHASE_CHANGED = False # flag: phase just changed (reset tool count next call)

# ── Path to the techne repo for CWD-independent resolution ──────────────────

_TECHNE_REPO_STR = str(TECHNE_REPO)


def _find_audit_log_path() -> Path | None:
    """Find .techne/audit/blocked.log by walking up from CWD."""
    cwd = Path.cwd().resolve()
    for parent in [cwd] + list(cwd.parents):
        candidate = parent / ".techne" / "audit" / "blocked.log"
        if candidate.parent.exists():
            return candidate
        if (parent / ".techne").is_dir():
            return parent / ".techne" / "audit" / "blocked.log"
    return None


def _read_loop_state() -> tuple[str, str, dict | None]:
    """Read .techne/loop/state.json by finding .techne root first.

    Returns (phase, task_id, raw_state_dict) or ("", "", None) if no state file.
    Returns the raw dict so callers can check updated_at, phase_timeout_min, etc.
    """
    if _HAS_PHASE_GUARD:
        root = _pg_mod._find_techne_root()
    else:
        # Inline version of root finding
        cwd = Path.cwd().resolve()
        root = None
        for parent in [cwd] + list(cwd.parents):
            if (parent / ".techne").is_dir():
                root = parent
                break

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


def _increment_tool_count(phase: str) -> int:
    """Increment the tool-use counter for the current phase.

    Resets to 0 if phase changed since last call.
    """
    global _LAST_PHASE, _TOOL_COUNT, _PHASE_CHANGED

    if phase != _LAST_PHASE:
        _TOOL_COUNT = 0
        _LAST_PHASE = phase
        _PHASE_CHANGED = True
    else:
        _TOOL_COUNT += 1
        _PHASE_CHANGED = False

    return _TOOL_COUNT


def _is_next_command(command: str) -> bool:
    """Check if a terminal command is calling ./next."""
    for pattern in _NEXT_PATTERNS:
        if pattern.search(command):
            return True
    return False


def _reset_phase_tracking() -> None:
    """Reset phase tracking state — called on session start/reset."""
    global _LAST_PHASE, _TOOL_COUNT, _PHASE_CHANGED
    _LAST_PHASE = ""
    _TOOL_COUNT = 0
    _PHASE_CHANGED = False


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
    """Check if there's an active pipeline task.

    Checks BOTH:
    1. Old SQLite task DB for active tasks (old pipeline)
    2. .techne/loop/state.json for active loop (new ./next pipeline)

    A task is active if EITHER check passes.
    """
    # Check new loop first (no SQLite needed)
    phase, tid, raw = _read_loop_state()
    if phase and phase not in ("DONE", "FAILED", ""):
        return True

    # Fallback: old SQLite task DB
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


def _rl_health() -> dict:
    """Quick RL health check from rewards.db."""
    import sqlite3
    from pathlib import Path

    cwd = Path.cwd().resolve()
    for parent in [cwd] + list(cwd.parents):
        db = parent / '.techne' / 'memory' / 'rewards.db'
        if db.exists():
            try:
                conn = sqlite3.connect(str(db))
                count = conn.execute('SELECT COUNT(*) FROM rewards').fetchone()[0]
                pending = conn.execute('SELECT COUNT(*) FROM rewards WHERE advantage != 0.0').fetchone()[0]
                types = conn.execute('SELECT COUNT(DISTINCT task_type) FROM rewards').fetchone()[0]
                conn.close()
                return {'rewards': count, 'scored': pending, 'task_types': types, 'db': str(db)}
            except Exception:
                return {'rewards': 0, 'scored': 0, 'task_types': 0, 'db': 'error'}
    return {'rewards': 0, 'scored': 0, 'task_types': 0, 'db': 'not found'}


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
        # Also block shell-level writes to source files (echo/cat/printf redirect)
        is_write, reason = _is_shell_source_write(command)
        if is_write:
            return (True, reason)

    # execute_code containing write_file calls
    if tool_name == "execute_code":
        code = ""
        if isinstance(tool_input, dict):
            code = tool_input.get("code", "")
        if "write_file" in code:
            return (True, "write_file called inside execute_code")
        # Reverse shell detection in execute_code
        if re.search(r"(?:socket\.connect|subprocess\.Popen|pty\.spawn|os\.system)\s*\(.*\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", code, re.I):
            return (True, "reverse shell pattern in execute_code")

    return (False, "")


def _check_phase_timeout(state_raw: dict | None) -> str | None:
    """Check if the current phase has timed out.

    Returns a block message if timed out, None if healthy.
    """
    if not state_raw:
        return None
    from datetime import datetime, timezone

    phase = state_raw.get("phase", "")
    if phase in ("DONE", "FAILED"):
        return None

    updated_raw = state_raw.get("updated_at")
    if not updated_raw:
        return None

    try:
        updated = datetime.fromisoformat(updated_raw)
    except (ValueError, TypeError):
        return None

    timeout_min = state_raw.get("phase_timeout_min", _DEFAULT_PHASE_TIMEOUT_MIN)
    now = datetime.now(timezone.utc)
    elapsed_min = (now - updated).total_seconds() / 60.0

    if elapsed_min > timeout_min:
        task_id = state_raw.get("task_id", "?")
        return (
            f"⏰ Phase timeout: phase {phase} has been active for "
            f"{int(elapsed_min)} min (limit: {timeout_min} min).\n\n"
            f"Task {task_id} has not called ./next in over {timeout_min} min.\n"
            f"Call ./next to advance or acknowledge:\n"
            f"  python3 {_TECHNE_REPO_STR}/scripts/next.py\n\n"
            f"Temporary bypass: /techne bypass"
        )

    return None


def register(ctx) -> None:
    # ── Plugin state ──────────────────────────────────────────────────────
    _state = {
        "active": False,
        "bypass_count": 0,
        "block_log": [],  # list of (tool_name, reason, count)
        "total_blocks": 0,
        "db_not_found_warned": False,
    }

    def _log_block(tool_name: str, reason: str, persist: bool = True) -> None:
        """Record a blocked tool call for audit (in-memory + persistent)."""
        _state["total_blocks"] += 1
        _state["block_log"].append({
            "tool": tool_name,
            "reason": reason[:80],
        })
        # Keep in-memory log capped at 50
        if len(_state["block_log"]) > 50:
            _state["block_log"] = _state["block_log"][-50:]

        # Persistent log via phase_guard
        if persist and _HAS_PHASE_GUARD:
            try:
                _pg_log_blocked(f"tool:{tool_name}", reason[:200])
            except Exception:
                pass

    # ── pre_tool_call hook ────────────────────────────────────────────────
    @ctx.on("pre_tool_call")
    def on_pre_tool_call(
        tool_name: str = "",
        tool_input: dict = None,
        session_id: str = "",
        **kwargs,
    ) -> dict | None:
        """Block destructive tools if pipeline mode is active and no task exists.
        ALSO: enforce phase-aware artifact paths, force ./next after limit,
        detect phase timeout, log every block to disk.
        """
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

        # ── Read loop state for phase-aware enforcement ───────────────
        current_phase, task_id, state_raw = _read_loop_state()

        # ── No-state check: block source-file writes when no pipeline active ─
        # This fires FIRST so the agent gets a clear signal to run ./next --init
        # rather than a confusing host-direct-write error.
        if not current_phase and tool_name in _WRITE_TOOLS:
            path = ""
            if isinstance(tool_input, dict):
                path = tool_input.get("path", tool_input.get("file_path", ""))
            # Only block project source files (skip .techne/, .hermes/, /tmp/)
            if path and not _is_allowed_path(path) and _SOURCE_FILE_EXTS.search(path):
                _log_block(tool_name, f"no-pipeline source write: {path}")
                return {
                    "action": "block",
                    "message": (
                        f"[TECHNE] WRITE BLOCKED: {path}\n"
                        f"[TECHNE] Reason: No active pipeline\n"
                        f"[TECHNE] Fix: Run './next --init <task-id>' to start\n"
                    ),
                }

        # ── Host-direct-write detection ────────────────────────────────
        # The techne plugin only loads in the host agent session.
        # Subagents spawned via delegate_task do NOT load this plugin,
        # so any write_file/patch intercepted here is the HOST agent
        # attempting a direct source-file write — which must be routed
        # through delegate_task(MODE=IMPLEMENT) instead.
        if tool_name in _WRITE_TOOLS:
            path = ""
            if isinstance(tool_input, dict):
                path = tool_input.get("path", tool_input.get("file_path", ""))
            if path and _SOURCE_FILE_EXTS.search(path) and not _is_allowed_path(path):
                _log_block(tool_name, f"host-direct write: {path}")
                return {
                    "action": "block",
                    "message": (
                        f"[TECHNE] WRITE BLOCKED: {path}\n"
                        f"[TECHNE] Reason: Host agent attempted direct write. Use delegate_task for implementation.\n"
                        f"[TECHNE] Fix: Delegate to a subagent via delegate_task with MODE: IMPLEMENT\n"
                    ),
                }

        # ── Phase timeout check ────────────────────────────────────────
        if current_phase and state_raw:
            timeout_msg = _check_phase_timeout(state_raw)
            if timeout_msg:
                _log_block(tool_name, f"phase timeout in {current_phase}")
                return {
                    "action": "block",
                    "message": timeout_msg,
                }

        # ── Phase-guard write check (delegated to phase_guard.py) ─────
        if current_phase and tool_name in _WRITE_TOOLS:
            path = ""
            if isinstance(tool_input, dict):
                path = tool_input.get("path", tool_input.get("file_path", ""))

            if path:
                # Check via phase_guard if available
                if _HAS_PHASE_GUARD:
                    allowed, reason = _pg_check_write(path, cwd=str(Path.cwd()))
                    if not allowed:
                        _log_block(tool_name, reason)
                        return {
                            "action": "block",
                            "message": (
                                f"Write blocked: {reason}\n\n"
                                f"Current phase: {current_phase}\n"
                                f"Target path: {path}\n\n"
                                f"Call `./next` to advance to the next phase.\n"
                                f"  python3 {_TECHNE_REPO_STR}/scripts/next.py\n\n"
                                f"Temporary bypass: /techne bypass"
                            ),
                        }
                else:
                    # Inline fallback (same logic as phase_guard)
                    # Block .techne/audit/ entirely
                    if ".techne" in Path(path).parts and "audit" in Path(path).parts:
                        _log_block(tool_name, f"audit dir write: {path}")
                        return {
                            "action": "block",
                            "message": (
                                f"[TECHNE] WRITE BLOCKED: {path}\n"
                                f"[TECHNE] Reason: .techne/audit/ is append-only — direct writes forbidden\n"
                                f"[TECHNE] Fix: The audit log is written automatically by the pipeline\n"
                            ),
                        }

                    # Check phase artifact using _PHASE_ARTIFACT_MAP
                    artifact_name = _PHASE_ARTIFACT_MAP.get(current_phase)
                    if artifact_name is None:
                        # IMPLEMENT or DONE — any path allowed
                        pass
                    elif artifact_name and artifact_name in path:
                        # Correct artifact for this phase — allowed
                        pass
                    else:
                        # Wrong artifact or no state
                        _log_block(tool_name, f"wrong-phase artifact: {path}")
                        return {
                            "action": "block",
                            "message": (
                                f"[TECHNE] WRITE BLOCKED: {path}\n"
                                f"[TECHNE] Reason: Artifact belongs to a different phase\n"
                                f"[TECHNE] Current phase: {current_phase}\n"
                                f"[TECHNE] Fix: Run './next' to advance phases\n"
                            ),
                        }

        # ── If we have a phase, track tool count and check limits ──────
        if current_phase:
            count = _increment_tool_count(current_phase)
            limit = _PHASE_TOOL_LIMITS.get(current_phase, 0)

            # Check if this terminal command is a ./next call → reset counter
            if tool_name == "terminal":
                command = ""
                if isinstance(tool_input, dict):
                    command = tool_input.get("command", "")
                if _is_next_command(command):
                    _LAST_PHASE = ""  # force reset on next call
                    _TOOL_COUNT = 0

            # Check tool-count threshold
            if limit > 0 and count >= limit:
                _log_block(tool_name, f"tool-count {count} >= limit {limit} in {current_phase}")
                return {
                    "action": "block",
                    "message": (
                        f"Phase enforcement: {count} tool calls in {current_phase} phase.\n\n"
                        f"Call `./next` to advance to the next phase.\n"
                        f"  python3 {_TECHNE_REPO_STR}/scripts/next.py\n\n"
                        f"Temporary bypass: /techne bypass\n"
                    ),
                }

        # ── Check if this tool call is destructive ────────────────────
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
        path_for_msg = ""
        if isinstance(tool_input, dict):
            path_for_msg = tool_input.get("path", tool_input.get("file_path", "<unknown>"))
        return {
            "action": "block",
            "message": (
                f"[TECHNE] WRITE BLOCKED: {path_for_msg}\n"
                f"[TECHNE] Reason: No active pipeline task\n"
                f"[TECHNE] Fix: Run './next --init <task-id>' to start a pipeline\n"
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
        _reset_phase_tracking()

        # Auto-activate if .techne/ directory is found by walking up from CWD
        cwd = Path.cwd().resolve()
        techne_found = False
        for parent in [cwd] + list(cwd.parents):
            if (parent / ".techne").is_dir():
                techne_found = True
                break
            # Stop if we hit a filesystem root (avoid scanning entire filesystem)
            if parent == parent.parent:
                break

        if techne_found:
            _state["active"] = True
            ctx.inject_message(
                "╔══════════════════════════════════════════════════╗\n"
                "║   TECHNE WORKSHOP DETECTED                      ║\n"
                "║   Pipeline enforcement is ACTIVE                ║\n"
                "║   Start: ./next --init <task-id>                ║\n"
                "║   Status: ./next (shows current phase)          ║\n"
                "╚══════════════════════════════════════════════════╝",
                role="assistant",
            )

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
        _reset_phase_tracking()

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
            return "[techne] Block log cleared."

        if args_lower in ("status", "state"):
            lines = ["**Techne Pipeline Status**"]
            lines.append(
                f"Pipeline active: {'✅' if _state['active'] else '❌'}"
            )
            lines.append(f"Bypasses remaining: {_state['bypass_count']}")
            lines.append(f"Total blocks this session: {_state['total_blocks']}")

            # Loop phase state
            phase, tid, raw = _read_loop_state()
            if phase:
                lines.append(f"Loop phase: **{phase}** (task: {tid})")
                limit = _PHASE_TOOL_LIMITS.get(phase, 0)
                if limit > 0:
                    lines.append(f"Tool count: {_TOOL_COUNT}/{limit} (call ./next at limit)")
                else:
                    lines.append(f"Tool count: {_TOOL_COUNT} (no limit)")

                # Phase timeout info
                if raw:
                    timeout_min = raw.get("phase_timeout_min", _DEFAULT_PHASE_TIMEOUT_MIN)
                    lines.append(f"Phase timeout: {timeout_min} min")
            else:
                lines.append("Loop phase: none (no .techne/loop/state.json)")

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

            # RL Health
            rl = _rl_health()
            lines.append('')
            lines.append('**RL Health:**')
            lines.append(f'  Rewards logged: {rl["rewards"]}')
            lines.append(f'  Tasks with advantage scores: {rl["scored"]}')
            lines.append(f'  Task types seen: {rl["task_types"]}')
            if rl['rewards'] > 0:
                lines.append('  RL loop: ACTIVE')
            else:
                lines.append('  RL loop: IDLE (no rewards yet)')

            # Last RL event
            events_path = None
            for parent in [Path.cwd().resolve()] + list(Path.cwd().resolve().parents):
                ep = parent / '.techne' / 'events' / 'rl.jsonl'
                if ep.exists():
                    events_path = ep
                    break
            if events_path:
                try:
                    ev_lines = events_path.read_text().strip().split('\n')
                    if ev_lines:
                        import json
                        last = json.loads(ev_lines[-1])
                        lines.append(f'  Last RL event: {last.get("event", "?")} ({last.get("ts", "?")[:19]})')
                except Exception:
                    pass

            # In-memory block log (last 10)
            if _state["block_log"]:
                lines.append("**Recent in-memory blocks:**")
                for entry in _state["block_log"][-10:]:
                    lines.append(
                        f"  ⛔ {entry['tool']} — {entry['reason'][:60]}"
                    )

            # Persistent block log (last 5)
            if _HAS_PHASE_GUARD:
                try:
                    persistent = _pg_get_blocked_log()
                    if persistent:
                        lines.append("**Persistent blocked.log (last 5):**")
                        for entry in persistent[-5:]:
                            ts = entry.get("timestamp", "")[11:19] if entry.get("timestamp") else ""
                            p = entry.get("path", "")
                            r = entry.get("reason", "")[:50]
                            lines.append(f"  📝 {ts} {p} — {r}")
                except Exception:
                    pass

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

        # Check active task status
        db_path = _find_tasks_db()
        phase, tid, _ = _read_loop_state()
        has_active = bool(phase and phase not in ("DONE", "FAILED", ""))
        if not has_active and db_path:
            has_active = _has_active_task(db_path)

        db_status = ""
        if db_path:
            db_status = (
                f"\nTask DB found at `{db_path}` — "
                f"{'active tasks' if has_active else 'no active tasks'}."
            )
        else:
            db_status = (
                "\n⚠️ No task database found. Writes will be blocked after "
                "the first 3 attempts until a DB is available."
            )

        # Phase guard status
        pg_status = "✓ phase_guard module loaded" if _HAS_PHASE_GUARD else "⚠️ phase_guard not available"

        # Audit trail
        audit_path = _find_audit_log_path()
        audit_status = ""
        if audit_path and audit_path.parent.exists():
            # Count entries in audit chain
            chain_path = audit_path.parent / "chain.jsonl"
            if chain_path.exists():
                try:
                    chain_count = len(chain_path.read_text().splitlines())
                    audit_status = f"\nAudit chain: {chain_count} entries at {chain_path}"
                except Exception:
                    audit_status = "\nAudit chain: present (unreadable)"

        ctx.inject_message(
            f"**Techne Pipeline Mode activated.**\n\n"
            f"Loaded worker metaprompt ({line_count} lines).{db_status}\n\n"
            f"⚠️ **Write enforcement active.** The following are BLOCKED "
            f"unless a pipeline task is active:\n"
            f"  • `write_file` / `patch` — except to `.techne/` and `/tmp/`\n"
            f"  • `terminal(git commit/push/merge/reset)`\n"
            f"  • `terminal(rm -rf, mv, cp -f)`\n"
            f"  • `execute_code(write_file(...))`\n\n"
            f"**Enforcement features:**\n"
            f"  • {pg_status}\n"
            f"  • Phase timeout detection ({_DEFAULT_PHASE_TIMEOUT_MIN} min default)\n"
            f"  • Persistent block logging to .techne/audit/blocked.log"
            f"{audit_status}\n\n"
            f"Commands:\n"
            f"  `/techne status` — show state + block log\n"
            f"  `/techne bypass` — grant 3 bypass writes\n"
            f"  `/techne off` — disable enforcement",
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
