#!/usr/bin/env python3
"""phase_guard_hook.py — PreToolUse hook for Claude Code.

Claude Code calls this before any Write/Edit/MultiEdit tool call.
Reads the tool payload from stdin (JSON), checks if the write is allowed
given the current Techne pipeline phase, and exits:
  0 = allow
  2 = deny (block the tool call)

Fails open (exit 0) if:
  - stdin is not parseable JSON
  - the harness module can't be imported
  - the tool isn't a write-class tool
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
except ImportError:
    sys.exit(0)


_WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except Exception:
        sys.exit(0)

    tool = payload.get("tool_name", "")
    if tool not in _WRITE_TOOLS:
        sys.exit(0)

    inp = payload.get("tool_input", {})
    path = inp.get("file_path") or inp.get("notebook_path") or ""
    if not path:
        sys.exit(0)

    allowed, reason = check_write_allowed(path, cwd=str(Path.cwd()))
    if not allowed:
        print(f"[phase_guard] BLOCKED: {reason}", file=sys.stderr)
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
