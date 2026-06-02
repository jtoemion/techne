"""
gates.py — all greppable rule enforcement for this project.

Every skill rule that can be detected in a diff lives here as a gate function.
Add a new gate when you add a `gate: yes` entry to a skills file.
Never put subjective rules here — only patterns you can grep.
"""

import re


class GateViolation(Exception):
    pass


# ─── Next.js gates ─────────────────────────────────────────────────────────────

def gate_no_redirect_outside_middleware(diff: str):
    """Rule: redirect() only allowed in middleware.ts"""
    current_file = ""
    for i, line in enumerate(diff.splitlines()):
        # Track which file this hunk belongs to via diff headers
        if line.startswith("+++ b/") or line.startswith("+++ a/"):
            current_file = line[6:].strip()
            continue
        if line.startswith("--- ") or line.startswith("+++ ") or line.startswith("diff ") or line.startswith("@@"):
            continue
        if "redirect(" not in line:
            continue
        if "middleware.ts" not in current_file:
            raise GateViolation(
                f"GATE FAIL [nextjs/redirect]: redirect() on diff line {i+1} "
                f"is outside middleware.ts (current file: '{current_file or 'unknown'}')\n"
                f"  → {line.strip()}"
            )


def gate_no_router_import(diff: str):
    """Rule: import from next/navigation, never next/router"""
    for i, line in enumerate(diff.splitlines()):
        if line.lstrip().startswith("//") or line.lstrip().startswith("#"):
            continue
        if re.search(r"from\s+['\"]next/router['\"]", line):
            raise GateViolation(
                f"GATE FAIL [nextjs/router-import]: found 'next/router' import on line {i+1}. "
                f"Use 'next/navigation' in App Router.\n"
                f"  → {line.strip()}"
            )


def gate_no_gSSP(diff: str):
    """Rule: getServerSideProps removed in App Router"""
    for i, line in enumerate(diff.splitlines()):
        if "getServerSideProps" in line and not line.strip().startswith("#"):
            raise GateViolation(
                f"GATE FAIL [nextjs/gSSP]: getServerSideProps on line {i+1}. "
                f"Use async server components instead.\n"
                f"  → {line.strip()}"
            )


# ─── TypeScript gates ───────────────────────────────────────────────────────────

def gate_no_ts_ignore(diff: str):
    """Rule: no @ts-ignore or @ts-nocheck suppressions"""
    for i, line in enumerate(diff.splitlines()):
        if re.search(r"@ts-(ignore|nocheck)", line):
            raise GateViolation(
                f"GATE FAIL [ts/suppress]: @ts-ignore or @ts-nocheck on line {i+1}. "
                f"Fix the type error instead.\n"
                f"  → {line.strip()}"
            )


# ─── General gates ──────────────────────────────────────────────────────────────

def gate_no_console_log(diff: str):
    """Rule: no console.log in production code paths"""
    skip_patterns = re.compile(r"(\.test\.|\.spec\.|\.stories\.|__tests__)")
    for i, line in enumerate(diff.splitlines()):
        if "console.log" in line and line.strip().startswith("+"):
            # allow in test/story files (checked via context — limited heuristic)
            raise GateViolation(
                f"GATE FAIL [general/console-log]: console.log added on line {i+1}. "
                f"Remove before merge.\n"
                f"  → {line.strip()}"
            )


# ─── Aggregated runner ──────────────────────────────────────────────────────────

ALL_GATES = [
    gate_no_redirect_outside_middleware,
    gate_no_router_import,
    gate_no_gSSP,
    gate_no_ts_ignore,
    gate_no_console_log,
]


def run_all_gates(diff: str) -> bool:
    """Run every gate. Raises GateViolation on first failure."""
    for gate in ALL_GATES:
        gate(diff)
    return True
