"""
gates.py — shared gate utilities and the GateViolation exception.

Gate functions live in plugins/builtin_gates.py and user-created plugins.
This module provides the building blocks they all use:
  - GateViolation exception (the universal gate failure signal)
  - _strip_diff_marker / _is_comment helpers (used by all gate plugins)

For the full gate registry system, see gate_registry.py.
"""

import re


class GateViolation(Exception):
    pass


def _strip_diff_marker(line: str) -> str:
    """Remove a leading +/- diff marker (and surrounding whitespace),
    returning the underlying code content."""
    if line[:1] in ("+", "-"):
        line = line[1:]
    return line.strip()


def _is_comment(code: str) -> bool:
    """True if a stripped code line is a JS/TS or shell comment.
    `code` must already have its diff marker removed (see _strip_diff_marker)."""
    return code.startswith(("//", "#", "/*", "*"))


# ─── Legacy shim — keeps old callers working during migration ──────────────

def run_all_gates(diff: str) -> bool:
    """
    Legacy shim. Prefer GateRegistry.run_all() for new code.

    Creates a default registry, discovers plugins, and runs all gates.
    The conductor.py will be updated to use the registry directly.
    """
    from gate_registry import GateRegistry

    registry = GateRegistry()
    registry.discover_plugins()
    registry.load_config()
    return registry.run_all(diff)


# ─── Backward-compat re-exports from builtin_gates plugin ─────────────────
# Old tests import gate functions directly from gates.py. These re-exports
# point to the plugin versions so existing imports keep working.

def gate_no_redirect_outside_middleware(diff: str):
    from plugins.builtin_gates import _gate_no_redirect_outside_middleware
    return _gate_no_redirect_outside_middleware(diff)

def gate_no_router_import(diff: str):
    from plugins.builtin_gates import _gate_no_router_import
    return _gate_no_router_import(diff)

def gate_no_gSSP(diff: str):
    from plugins.builtin_gates import _gate_no_gSSP
    return _gate_no_gSSP(diff)

def gate_no_ts_ignore(diff: str):
    from plugins.builtin_gates import _gate_no_ts_ignore
    return _gate_no_ts_ignore(diff)

def gate_no_console_log(diff: str):
    from plugins.builtin_gates import _gate_no_console_log
    return _gate_no_console_log(diff)
