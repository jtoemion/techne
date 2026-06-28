#!/usr/bin/env python3
"""phase_guard_hook.py — PreToolUse hook for Claude Code (W1 Boundary + phase enforcement).

Claude Code calls this before Write/Edit/MultiEdit/NotebookEdit/Bash tool calls.
Reads the tool payload from stdin (JSON), runs two gate layers, and exits:
  0 = allow
  2 = block (deny the tool call)

Gate layers (in order):
  1. W1 Boundary (scripts/boundary.py) — four mandatory layers:
       L1 network egress, L2 filesystem scope, L3 secrets, L4 config protection
  2. Phase guard (harness/plugins/phase_guard.py) — phase-based write discipline

Fails open (exit 0) if:
  - stdin is not parseable JSON
  - the harness module can't be imported
  - no .techne/ directory is found in the project tree
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "harness"))
sys.path.insert(0, str(_REPO / "harness" / "plugins"))
sys.path.insert(0, str(_REPO / "scripts"))

try:
    from phase_guard import check_write_allowed
    _PHASE_GUARD_AVAILABLE = True
except ImportError:
    _PHASE_GUARD_AVAILABLE = False

try:
    from boundary import check_tool_call, log_violation
    _BOUNDARY_AVAILABLE = True
except ImportError:
    _BOUNDARY_AVAILABLE = False


_WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
_ALL_GATED_TOOLS = _WRITE_TOOLS | {"Bash"}


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except Exception:
        sys.exit(0)

    tool = payload.get("tool_name", "")
    if tool not in _ALL_GATED_TOOLS:
        sys.exit(0)

    inp = payload.get("tool_input", {})
    project_root = Path.cwd()

    # ── Layer 1: W1 Boundary (four mandatory layers) ──────────────────────────
    if _BOUNDARY_AVAILABLE:
        result = check_tool_call(tool, inp, project_root)
        if not result.allowed:
            for v in result.violations:
                log_violation(tool, v.layer, v.reason, project_root)
                print(f"[boundary] BLOCKED ({v.layer}): {v.reason}", file=sys.stderr)
            sys.exit(2)

    # ── Layer 2: Phase guard (write tools only) ───────────────────────────────
    if tool not in _WRITE_TOOLS:
        sys.exit(0)  # Bash passed boundary — nothing more to check

    if not _PHASE_GUARD_AVAILABLE:
        sys.exit(0)

    path = inp.get("file_path") or inp.get("notebook_path") or ""
    if not path:
        sys.exit(0)

    allowed, reason = check_write_allowed(path, cwd=str(project_root))
    if not allowed:
        print(f"[phase_guard] BLOCKED: {reason}", file=sys.stderr)
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
