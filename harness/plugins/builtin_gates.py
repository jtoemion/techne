"""
Built-in gates: the original five Techne gates (Next.js + TypeScript + general).

These were previously hardcoded in gates.py. As a plugin, they are registered
with the same names and behavior, but can now be individually disabled or
replaced by other plugins.

To disable the Next.js gates for a non-Next.js project, either:
  - Set gate-config.yaml active_stacks: ["general", "typescript"]
  - Or: registry.disable("nextjs/redirect") etc.
"""
import re

from harness.gates import GateViolation, _strip_diff_marker, _is_comment


def _gate_no_redirect_outside_middleware(diff: str):
    """Rule: redirect() only allowed in middleware.ts"""
    current_file = ""
    for i, line in enumerate(diff.splitlines()):
        if line.startswith("+++ b/") or line.startswith("+++ a/"):
            current_file = line[6:].strip()
            continue
        if line.startswith(("--- ", "+++", "diff ", "@@")):
            continue
        code = _strip_diff_marker(line)
        if _is_comment(code):
            continue
        if "redirect(" not in code:
            continue
        if "middleware.ts" not in current_file:
            raise GateViolation(
                f"GATE FAIL [nextjs/redirect]: redirect() on diff line {i+1} "
                f"is outside middleware.ts (current file: '{current_file or 'unknown'}')\n"
                f"  → {line.strip()}"
            )


def _gate_no_router_import(diff: str):
    """Rule: import from next/navigation, never next/router"""
    for i, line in enumerate(diff.splitlines()):
        code = _strip_diff_marker(line)
        if _is_comment(code):
            continue
        if re.search(r"from\s+['\"]next/router['\"]", code):
            raise GateViolation(
                f"GATE FAIL [nextjs/router-import]: found 'next/router' import on line {i+1}. "
                f"Use 'next/navigation' in App Router.\n"
                f"  → {line.strip()}"
            )


def _gate_no_gSSP(diff: str):
    """Rule: getServerSideProps removed in App Router"""
    for i, line in enumerate(diff.splitlines()):
        if line.startswith(("+++", "---", "@@", "diff ")):
            continue
        code = _strip_diff_marker(line)
        if _is_comment(code):
            continue
        if "getServerSideProps" in code:
            raise GateViolation(
                f"GATE FAIL [nextjs/gSSP]: getServerSideProps on line {i+1}. "
                f"Use async server components instead.\n"
                f"  → {line.strip()}"
            )


def _gate_no_ts_ignore(diff: str):
    """Rule: no @ts-ignore or @ts-nocheck suppressions"""
    for i, line in enumerate(diff.splitlines()):
        if re.search(r"@ts-(ignore|nocheck)", line):
            raise GateViolation(
                f"GATE FAIL [ts/suppress]: @ts-ignore or @ts-nocheck on line {i+1}. "
                f"Fix the type error instead.\n"
                f"  → {line.strip()}"
            )


def _gate_no_console_log(diff: str):
    """Rule: no console.log in production code paths"""
    for i, line in enumerate(diff.splitlines()):
        if not line.startswith("+") or line.startswith("+++"):
            continue
        code = _strip_diff_marker(line)
        if _is_comment(code):
            continue
        if "console.log" in code:
            raise GateViolation(
                f"GATE FAIL [general/console-log]: console.log added on line {i+1}. "
                f"Remove before merge.\n"
                f"  → {line.strip()}"
            )


def register(registry):
    """Register the five built-in gates."""
    registry.register(
        "nextjs/redirect", _gate_no_redirect_outside_middleware,
        stack="nextjs", description="redirect() only in middleware.ts",
    )
    registry.register(
        "nextjs/router-import", _gate_no_router_import,
        stack="nextjs", description="use next/navigation, not next/router",
    )
    registry.register(
        "nextjs/gSSP", _gate_no_gSSP,
        stack="nextjs", description="no getServerSideProps in App Router",
    )
    registry.register(
        "ts/suppress", _gate_no_ts_ignore,
        stack="typescript", description="no @ts-ignore or @ts-nocheck",
    )
    registry.register(
        "general/console-log", _gate_no_console_log,
        stack="general", description="no console.log in production",
    )
