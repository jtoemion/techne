#!/usr/bin/env python3
"""next.py — The ./next script: phase enforcement via disk artifacts.

Usage:
    cd /path/to/project
    python3 /path/to/techne/scripts/next.py

Or create a symlink so `./next` works from the project root.

What it does:
    1. Reads .techne/loop/state.json (current task + phase)
    2. Checks the expected artifact for the current phase
    3. Runs deterministic gates on the artifact
    4. Prints a plain-language summary the agent CANNOT manipulate
       (because it reads real filesystem state)
    5. Advances state to the next phase
    6. Prints what the next phase requires
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Ensure scripts/ is on the path so we can import sibling modules
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from next_state import (
    LoopState, read_state, write_state, state_path, loop_dir,
    PHASE_SEQUENCE, artifact_path_for,
)
from audit_chain import AuditEntry, append_entry as audit_append
from datetime import datetime, timezone


# ── Coloured terminal output ─────────────────────────────────────────────────
# ANSI codes — safe on Linux/macOS terminals
_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _ok(text: str) -> str:
    return f"{_GREEN}✓{_RESET} {text}"


def _fail(text: str) -> str:
    return f"{_RED}✗{_RESET} {text}"


def _warn(text: str) -> str:
    return f"{_YELLOW}⚠{_RESET} {text}"


def _heading(text: str) -> str:
    return f"{_BOLD}{_CYAN}◇{_RESET} {_BOLD}{text}{_RESET}"


# ── Gate helpers ─────────────────────────────────────────────────────────────

class GateResult:
    """Result of one gate check."""
    def __init__(self, name: str, passed: bool, detail: str = ""):
        self.name = name
        self.passed = passed
        self.detail = detail


def _check_artifact_exists(path: Path, phase: str) -> GateResult:
    """Gate: the expected artifact file exists and is non-empty."""
    if not path.exists():
        return GateResult(
            f"artifact: {path.name}",
            False,
            f"file not found at {path}",
        )
    size = path.stat().st_size
    if size == 0:
        return GateResult(
            f"artifact: {path.name}",
            False,
            "file is empty (0 bytes)",
        )
    return GateResult(
        f"artifact: {path.name}",
        True,
        f"{size} bytes on disk",
    )


def _check_no_forbidden_patterns(path: Path) -> list[GateResult]:
    """Gate: diff contains no forbidden patterns (TODO, console.log, etc.)."""
    results = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return [GateResult("forbidden patterns", False, "cannot read file")]

    # Only check lines that start with '+' (additions in a diff)
    added_lines = [l for l in text.split("\n") if l.startswith("+") and not l.startswith("+++")]

    patterns = [
        (r"console\.log\s*\(", "console.log()"),
        (r"\bTODO\b", "TODO marker"),
        (r"\bFIXME\b", "FIXME marker"),
        (r"@ts-ignore", "@ts-ignore"),
        (r"@ts-expect-error", "@ts-expect-error"),
        (r"eslint-disable", "eslint-disable"),
        (r"debugger\s*;?", "debugger statement"),
    ]

    # Also scan raw text for non-diff content (for non-IMPLEMENT phases)
    scan_lines = added_lines if path.name == "diff.txt" else text.split("\n")

    for pattern, label in patterns:
        matches = [l.strip() for l in scan_lines if re.search(pattern, l)]
        if matches:
            results.append(GateResult(
                f"no {label}",
                False,
                f"found {len(matches)} occurrence(s)",
            ))
        else:
            results.append(GateResult(f"no {label}", True))

    return results


def _check_recall_gates(path: Path) -> list[GateResult]:
    """Gates specific to the RECALL phase."""
    results = [GateResult("phase", True, "RECALL")]
    results.append(_check_artifact_exists(path, "RECALL"))

    if path.exists():
        text = path.read_text(encoding="utf-8", errors="replace")
        # Must contain evidence of Honcho context recall
        has_honcho = "HONCHO_CONTEXT:" in text or "HONCHO:" in text
        has_workshop = "WORKSHOP_CONTEXT:" in text
        has_evidence = has_honcho or has_workshop
        results.append(GateResult(
            "context recall evidence",
            has_evidence,
            "found HONCHO/WORKSHOP context" if has_evidence
            else "missing HONCHO_CONTEXT: or WORKSHOP_CONTEXT: line",
        ))

        # Check for substance (not empty filler)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        results.append(GateResult(
            "substance",
            len(lines) >= 3,
            f"{len(lines)} non-empty line(s)" if len(lines) >= 3
            else f"only {len(lines)} line(s) — need at least 3",
        ))

    return results


def _check_implement_gates(path: Path) -> list[GateResult]:
    """Gates specific to the IMPLEMENT phase."""
    results = [GateResult("phase", True, "IMPLEMENT")]
    results.append(_check_artifact_exists(path, "IMPLEMENT"))

    if path.exists():
        text = path.read_text(encoding="utf-8", errors="replace")

        # Must be a valid git diff (has @@ or --- / +++ markers)
        has_diff_markers = "@@ -" in text or "--- " in text
        results.append(GateResult(
            "valid diff format",
            has_diff_markers,
            "diff markers found" if has_diff_markers else "no @@ or --- markers",
        ))

        # Count added/deleted lines
        added = len([l for l in text.split("\n") if l.startswith("+") and not l.startswith("+++")])
        deleted = len([l for l in text.split("\n") if l.startswith("-") and not l.startswith("---")])
        results.append(GateResult(
            "changed lines",
            added + deleted > 0,
            f"+{added} / -{deleted} lines",
        ))

        # Forbidden patterns
        results.extend(_check_no_forbidden_patterns(path))

        # Scope estimation (files touched)
        files_changed = set()
        for line in text.split("\n"):
            if line.startswith("--- ") or line.startswith("+++ "):
                fname = line[6:].partition("\t")[0].strip()
                if fname and fname != "/dev/null":
                    files_changed.add(fname)
        scope = f"{len(files_changed)} file(s)" if files_changed else "unknown"
        results.append(GateResult(
            "scope estimation",
            len(files_changed) <= 10,
            scope,
        ))

    return results


def _check_verify_gates(path: Path) -> list[GateResult]:
    """Gates specific to the VERIFY phase."""
    results = [GateResult("phase", True, "VERIFY")]
    results.append(_check_artifact_exists(path, "VERIFY"))

    if path.exists():
        text = path.read_text(encoding="utf-8", errors="replace")

        # Must have test output (not blank)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        results.append(GateResult(
            "has output",
            len(lines) >= 2,
            f"{len(lines)} non-empty line(s)",
        ))

        # Check for failure keywords (but allow some context)
        has_failure = re.search(r"\bFAILED\b", text, re.I) and not re.search(
            r"(?:0\s+failed|all tests passed)", text, re.I
        )
        has_error = re.search(r"\bERROR\b", text, re.I) and not re.search(
            r"(?:0\s+errors?|no errors)", text, re.I
        )
        results.append(GateResult(
            "no test failures",
            not (has_failure or has_error),
            "test failures detected" if has_failure or has_error
            else "no failures found",
        ))

        # Pass indicator (PASS, ok, ✅, etc.)
        has_pass = bool(re.search(
            r"(?:passed|PASS|ok\s|\d+ passed|all tests|success)", text, re.I
        ))
        results.append(GateResult(
            "pass indicator",
            has_pass,
            "pass signal found" if has_pass else "no pass signal detected",
        ))

    return results


def _check_conclude_gates(path: Path) -> list[GateResult]:
    """Gates specific to the CONCLUDE phase."""
    results = [GateResult("phase", True, "CONCLUDE")]
    results.append(_check_artifact_exists(path, "CONCLUDE"))

    if path.exists():
        text = path.read_text(encoding="utf-8", errors="replace")

        # Must reference Honcho
        has_honcho = "HONCHO" in text or "honcho" in text
        results.append(GateResult(
            "honcho reference",
            has_honcho,
            "found" if has_honcho else "missing — include honcho conclusion ID",
        ))

        # Must be more than a stub
        has_content = len(text.strip()) >= 20
        results.append(GateResult(
            "substance",
            has_content,
            f"{len(text.strip())} chars" if has_content else "too short (< 20 chars)",
        ))

    return results


# ── Phase gate dispatch ──────────────────────────────────────────────────────

_PHASE_GATES = {
    "RECALL": _check_recall_gates,
    "IMPLEMENT": _check_implement_gates,
    "VERIFY": _check_verify_gates,
    "CONCLUDE": _check_conclude_gates,
}


def run_phase_gates(state: LoopState) -> list[GateResult]:
    """Run all gates for the current phase. Returns list of results."""
    gate_fn = _PHASE_GATES.get(state.phase)
    if gate_fn is None:
        return [GateResult("phase", True, state.phase)]

    path = artifact_path_for(state.phase)
    return gate_fn(path)


# ── Summary formatting ───────────────────────────────────────────────────────

def format_summary(phase: str, results: list[GateResult], next_phase: str | None) -> str:
    """Print a plain-language summary the agent cannot fabricate."""
    lines = [""]
    lines.append("=" * 54)
    lines.append(f"  NEXT — {phase} → {next_phase or 'DONE'}")
    lines.append("=" * 54)
    lines.append("")

    passed = sum(1 for r in results if r.passed)
    total = len(results)

    for r in results:
        if r.passed:
            lines.append(f"  {_ok(r.name)}")
        else:
            lines.append(f"  {_fail(r.name)}")
        if r.detail:
            lines.append(f"       {r.detail}")
    lines.append("")

    if passed == total:
        lines.append(f"  {_ok(f'All {total} gate(s) passed')}")
    else:
        lines.append(f"  {_fail(f'{passed}/{total} gate(s) passed — {total - passed} failed')}")
    lines.append("")

    if passed == total and next_phase:
        lines.append(f"  {_heading('NEXT PHASE: ' + next_phase)}")
        lines.append(f"  Requirements for {next_phase}:")
        for req in _phase_requirements(next_phase):
            lines.append(f"    • {req}")
        lines.append("")
    elif passed == total and next_phase is None:
        lines.append(f"  {_heading('TASK COMPLETE')}")
        lines.append("  All phases done.")
        lines.append("")

    lines.append("=" * 54)
    return "\n".join(lines)


def _phase_requirements(phase: str) -> list[str]:
    """Return human-readable requirements for a phase."""
    reqs = {
        "RECALL": [
            "Search Honcho context for this task",
            "Write findings to .techne/loop/recall.txt",
            "Include HONCHO_CONTEXT: or WORKSHOP_CONTEXT: evidence line",
        ],
        "IMPLEMENT": [
            "Write the implementation (code changes)",
            "Capture the diff: git diff > .techne/loop/diff.txt",
            "Then call ./next again",
        ],
        "VERIFY": [
            "Run the test suite",
            "Capture output: pytest > .techne/loop/test_output.txt",
            "Then call ./next again",
        ],
        "CONCLUDE": [
            "Run honcho_conclude to persist task outcome",
            "Write conclusion to .techne/loop/conclude.txt",
            "Include the honcho conclusion ID",
            "Then call ./next again",
        ],
    }
    return reqs.get(phase, [f"Complete the {phase} phase, write artifact, call ./next"])


def format_footer(phase: str, results: list[GateResult]) -> str:
    """Print a compact line suitable for tool output summary."""
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    symbol = _ok("") if passed == total else _fail("")
    return f"  {symbol} {phase}: {passed}/{total} gates passed"


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    cwd = Path.cwd()

    state = read_state(cwd)
    if state is None:
        print(_fail("No active loop found."))
        print(f"  Create .techne/loop/state.json or call create_task first.")
        print(f"  Expected at: {state_path(cwd)}")
        return 1

    if state.is_terminal():
        print(_ok("All phases complete. Task is DONE."))
        print(f"  Task ID: {state.task_id}")
        return 0

    # Run gates for the current phase
    results = run_phase_gates(state)
    all_passed = all(r.passed for r in results)

    next_phase = state.next_phase()

    # Print summary
    summary = format_summary(state.phase, results, next_phase)
    print(summary)

    # Only advance state if all gates passed
    if all_passed:
        old_phase = state.phase
        state.summary = summary
        state.phase = next_phase or state.phase
        write_state(state, cwd)

        # Append to audit chain
        try:
            audit_entry = AuditEntry(
                seq=0,
                timestamp=datetime.now(timezone.utc).isoformat(),
                task_id=state.task_id,
                phase=state.phase,
                gates=[{"name": r.name, "passed": r.passed, "detail": r.detail} for r in results],
                summary=summary,
                prev_hash="0" * 64,
            )
            audit_append(audit_entry)
        except Exception:
            # Audit append failure should not block phase advancement
            pass

        # Rebuild wikilink knowledge graph when CONCLUDE → DONE (or any
        # phase that completes the loop).  The wikilink index
        # (wikilinks.json + wikilinks.md) is rebuilt so the knowledge
        # graph stays current with mistakes, ledger, and task outcomes.
        if old_phase == "CONCLUDE":
            try:
                import json as _json
                sys.path.insert(0, str(Path(__file__).parent.parent / "harness"))
                from wikilink import build_graph, format_markdown as wl_md
                memory_dir = cwd / ".techne" / "memory"
                graph = build_graph()
                (memory_dir / "wikilinks.md").write_text(wl_md(graph), encoding="utf-8")
                (memory_dir / "wikilinks.json").write_text(
                    _json.dumps(graph, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:
                # Wikilink rebuild is best-effort
                pass

        return 0
    else:
        # Record the failed summary but do NOT advance
        state.summary = summary
        write_state(state, cwd)
        return 1


if __name__ == "__main__":
    sys.exit(main())
