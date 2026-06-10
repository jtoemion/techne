"""
gates.py — all greppable rule enforcement for this project.

Every skill rule that can be detected in a diff lives here as a gate function.
Add a new gate when you add a `gate: yes` entry to a skills file.
Never put subjective rules here — only patterns you can grep.
"""

import re


class GateViolation(Exception):
    pass


# ─── Diff-line helpers ─────────────────────────────────────────────────────────

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


def gate_no_router_import(diff: str):
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


def gate_no_gSSP(diff: str):
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
    for i, line in enumerate(diff.splitlines()):
        # added lines only; skip the +++ file header
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


# ─── Per-gate report (visibility — does not stop on first failure) ──────────────

def run_all_gates_report(diff: str) -> list[dict]:
    """Run EVERY gate and collect a per-gate pass/fail board (does not raise).

    Use for showing the human the whole gate board; use run_all_gates() for
    enforcement (which stops on the first failure).
    """
    results = []
    for gate in ALL_GATES:
        try:
            gate(diff)
            results.append({"gate": gate.__name__, "passed": True, "detail": ""})
        except GateViolation as e:
            first = str(e).splitlines()[0] if str(e) else ""
            results.append({"gate": gate.__name__, "passed": False, "detail": first})
    return results


def format_gate_report(results: list[dict]) -> str:
    """ASCII-safe rendering of the gate board (Windows-console friendly)."""
    passed = sum(1 for r in results if r["passed"])
    lines = [f"GATES ({passed}/{len(results)} passed):"]
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        name = r["gate"].replace("gate_", "")
        lines.append(f"  [{mark}] {name}")
        if not r["passed"] and r["detail"]:
            lines.append(f"         -> {r['detail']}")
    return "\n".join(lines)
