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

import argparse
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
from hash_gate import validate_diff_context
from datetime import datetime, timezone

# ── Configurable scope limit (read from .techne/config.yaml) ─────────────────
_SCOPE_LIMIT = 10
_STRICT_NODES = False  # Set via --strict-nodes flag

def _load_config() -> None:
    """Read scope_limit from .techne/config.yaml if present."""
    global _SCOPE_LIMIT
    try:
        cfg_path = Path.cwd() / ".techne" / "config.yaml"
        if cfg_path.exists():
            for line in cfg_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("scope_limit:"):
                    _SCOPE_LIMIT = int(line.split(":", 1)[1].strip())
                    break
    except Exception:
        pass


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
    
    # Fallback for documentation-only tasks: check .techne/context/ for new docs
    _doc_files: list[Path] = []
    _context_dir = Path.cwd() / ".techne" / "context"
    if _context_dir.exists():
        _doc_files = sorted(_context_dir.glob("*.md"))

    # Doc-task artifact check — accept context files when diff is empty
    if _doc_files and (not path.exists() or path.stat().st_size == 0):
        total_bytes = sum(f.stat().st_size for f in _doc_files)
        results.append(GateResult("artifact: docs in .techne/context/", True,
            f"{len(_doc_files)} file(s), {total_bytes} bytes"))
    else:
        results.append(_check_artifact_exists(path, "IMPLEMENT"))

    if path.exists():
        text = path.read_text(encoding="utf-8", errors="replace")
        is_empty = not text.strip()

        # Empty diff with context docs → documentation task mode
        if is_empty and _doc_files:
            doc_summary = []
            total_bytes = 0
            for df in _doc_files:
                sz = df.stat().st_size
                total_bytes += sz
                doc_summary.append(f"  {df.name} ({sz} bytes)")
            doc_text = "\n".join(doc_summary)

            results.append(GateResult("valid diff format", True,
                f"doc task: {len(_doc_files)} file(s) in .techne/context/"))
            results.append(GateResult("changed lines", True,
                f"{len(_doc_files)} doc(s), {total_bytes} bytes"))
            # Skip forbidden-patterns check for doc tasks (docs are markdown)
            results.append(GateResult("no console.log()", True))
            results.append(GateResult("no TODO marker", True))
            results.append(GateResult("no FIXME marker", True))
            results.append(GateResult("no @ts-ignore", True))
            results.append(GateResult("no @ts-expect-error", True))
            results.append(GateResult("no eslint-disable", True))
            results.append(GateResult("no debugger statement", True))
            results.append(GateResult("scope estimation", True,
                f"{len(_doc_files)} doc(s)"))
            return results

        # Must be a valid git diff (has @@ or --- / +++ markers)
        has_diff_markers = "@@ -" in text or "--- " in text
        results.append(GateResult(
            "valid diff format",
            has_diff_markers,
            "diff markers found" if has_diff_markers else "no @@ or --- markers",
        ))

        # Hashline gate: context lines in diff must match actual file content
        if has_diff_markers:
            _hg_passed, _hg_detail = validate_diff_context(text, Path.cwd())
            results.append(GateResult(
                "hashline: context matches file",
                _hg_passed,
                _hg_detail if _hg_passed else f"stale read — {_hg_detail} — re-read the file",
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
            len(files_changed) <= _SCOPE_LIMIT,
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

    # ── Node-discipline gate (soft by default; hard block with --strict-nodes) ──
    try:
        node_gate_script = _HERE / "node_gate.py"
        if node_gate_script.exists():
            import subprocess
            node_result = subprocess.run(
                [sys.executable, str(node_gate_script),
                 "--project-dir", str(Path.cwd()), "--json"],
                capture_output=True, text=True, timeout=60,
            )
            if node_result.returncode == 0:
                results.append(GateResult(
                    "node discipline",
                    True,
                    "all module boundaries respected",
                ))
            else:
                try:
                    import json as _json
                    report = _json.loads(node_result.stdout)
                    high = report.get("counts", {}).get("high", 0)
                    total = report.get("counts", {}).get("total", 0)
                    msg = f"{high} HIGH / {total} total violation(s)"
                    if _STRICT_NODES and high > 0:
                        results.append(GateResult("node discipline", False, msg))
                    else:
                        results.append(GateResult("node discipline", True, msg))
                except Exception:
                    results.append(GateResult(
                        "node discipline", True, "scan completed (parse warnings)"
                    ))
    except Exception as exc:
        results.append(GateResult(
            "node discipline", True, f"scan skipped ({exc})"
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


# Phase artifact map (mirrors phase_guard.py — kept to avoid import coupling)
_PHASE_ARTIFACT_MAP = {
    "RECALL":     "recall.txt",
    "IMPLEMENT":  "diff.txt",
    "VERIFY":     "test_output.txt",
    "CONCLUDE":   "conclude.txt",
}


def format_footer(phase: str, results: list[GateResult]) -> str:
    """Print a compact line suitable for tool output summary."""
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    symbol = _ok("") if passed == total else _fail("")
    return f"  {symbol} {phase}: {passed}/{total} gates passed"


def _read_rl_delta(cwd: Path) -> str | None:
    """Return a one-line RL summary from rl.jsonl, or None if unavailable."""
    rl_log = cwd / ".techne" / "events" / "rl.jsonl"
    if not rl_log.exists():
        return None
    try:
        entries = [
            __import__("json").loads(l)
            for l in rl_log.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
    except Exception:
        return None
    if not entries:
        return None
    last = entries[-1]
    r = last.get("reward", "?")
    adv = last.get("advantage", "?")
    return f"{len(entries)} events — last reward={r} advantage={adv}"


def format_phase_report(state: LoopState, old_phase: str, results: list[GateResult],
                        cwd: Path) -> str:
    """Generate a detailed phase completion report for the user.

    Printed after successful phase transition. The agent MUST forward this
    to the user verbatim — it is actionable intelligence, not internal log.
    """
    artifact_name = _PHASE_ARTIFACT_MAP.get(old_phase, "N/A")
    artifact_path = cwd / ".techne" / "loop" / artifact_name
    artifact_size = artifact_path.stat().st_size if artifact_path.exists() else 0

    gates_pass = sum(1 for r in results if r.passed)
    gates_total = len(results)
    gate_lines = "\n".join(
        f"    {'✓' if r.passed else '✗'} {r.name}"
        + (f": {r.detail}" if r.detail else "")
        for r in results
    )

    next_reqs = _phase_requirements(state.phase)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines: list[str] = [
        "",
        "╔" + "═" * 62 + "╗",
        f"  PHASE COMPLETE  {old_phase} → {state.phase}",
        "╠" + "═" * 62 + "╣",
        f"  Task:    {state.task_id}",
        f"  Project: {cwd.name}",
        f"  Time:    {now_str}",
        "",
        "  GATES:",
        gate_lines,
        f"  └─ {gates_pass}/{gates_total} passed",
        "",
    ]

    # ── Artifact section ────────────────────────────────────────────────────
    lines.extend([
        "  ARTIFACT:",
        f"    .techne/loop/{artifact_name}  ({artifact_size} bytes)",
    ])

    if artifact_path.exists():
        artifact_lines = artifact_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
        preview_lines = artifact_lines[:6]
        if preview_lines:
            lines.append("    ┌─ preview ─────────────────────────────────────────")
            for pl in preview_lines:
                lines.append(f"    │ {pl[:80]}")
            if len(artifact_lines) > 6:
                lines.append(f"    │ … ({len(artifact_lines) - 6} more lines)")
            lines.append("    └──────────────────────────────────────────────────")

    # ── Phase-specific metrics ───────────────────────────────────────────────
    if old_phase == "VERIFY" and artifact_path.exists():
        text = artifact_path.read_text(encoding="utf-8", errors="replace")
        passed_m = re.search(r"(\d+)\s+passed", text)
        failed_m = re.search(r"(\d+)\s+failed", text)
        error_m  = re.search(r"(\d+)\s+error", text)
        if passed_m or failed_m:
            p  = passed_m.group(1) if passed_m else "?"
            f  = failed_m.group(1) if failed_m else "0"
            e  = error_m.group(1) if error_m else "0"
            lines.append(f"  TESTS:    {p} passed  {f} failed  {e} errors")

    if old_phase == "IMPLEMENT" and artifact_path.exists():
        text = artifact_path.read_text(encoding="utf-8", errors="replace")
        from hash_gate import parse_diff_files
        parsed = parse_diff_files(text)
        n_files = len(parsed)
        added   = sum(1 for l in text.splitlines() if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in text.splitlines() if l.startswith("-") and not l.startswith("---"))
        lines.append(f"  DIFF:     {n_files} file(s)  +{added} -{removed} lines")

    if old_phase == "CONCLUDE" and artifact_path.exists():
        text = artifact_path.read_text(encoding="utf-8", errors="replace")
        honcho_m = re.search(r"HONCHO[:\s]+(\S+)", text)
        if honcho_m:
            lines.append(f"  HONCHO:   {honcho_m.group(1)}")

    # ── RL delta ────────────────────────────────────────────────────────────
    rl_summary = _read_rl_delta(cwd)
    if rl_summary:
        lines.append(f"  RL:       {rl_summary}")

    # ── Next phase ──────────────────────────────────────────────────────────
    lines.extend([
        "",
        "╠" + "═" * 62 + "╣",
        f"  NEXT: {state.phase}",
        "",
    ])
    for req in next_reqs:
        lines.append(f"    • {req}")
    lines.extend([
        "",
        "  Run:  techne next",
        "╚" + "═" * 62 + "╝",
        "",
    ])

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    cwd = Path.cwd()

    parser = argparse.ArgumentParser(
        description="Advance the Techne ./next loop to the next phase.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--init", metavar="TASK_ID",
        help="Initialize a new task in RECALL phase and create state.json"
    )
    parser.add_argument(
        "--help-phases", action="store_true",
        help="Show requirements for each pipeline phase"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Allow --init to overwrite existing state.json"
    )
    parser.add_argument(
        "--strict-nodes", action="store_true",
        help="Block VERIFY phase if node-discipline violations found (default: soft report)"
    )
    args, remaining = parser.parse_known_args()

    # Propagate strict-nodes to gate functions
    if args.strict_nodes:
        global _STRICT_NODES
        _STRICT_NODES = True

    if args.help_phases:
        print("Techne ./next pipeline phases:\n")
        for phase in ["RECALL", "IMPLEMENT", "VERIFY", "CONCLUDE", "DONE"]:
            reqs = _phase_requirements(phase)
            print(f"  {phase}:")
            for r in reqs:
                print(f"    • {r}")
            print()
        return 0

    if args.init:
        from next_state import create_initial_state, state_path as _state_path
        sp = _state_path(cwd)
        if sp.exists() and not args.force:
            print(f"Error: state.json already exists at {sp}")
            print("Use --force to overwrite.")
            return 1
        state = create_initial_state(args.init, cwd=cwd)
        write_state(state, cwd)
        print(f"Task '{args.init}' initialized in RECALL phase")
        print()
        print("Next steps:")
        for r in _phase_requirements("RECALL"):
            print(f"  • {r}")
        print("Then call ./next again.")
        return 0

    state = read_state(cwd)
    _load_config()
    if state is None:
        print(_fail("No active loop found."))
        print()
        print("To start a new task:")
        print(f"  {sys.argv[0]} --init <task-id>")
        print()
        print("Or manually create .techne/loop/state.json")
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
                # Build graph from this project's .techne/memory/
                graph = build_graph(root=cwd)
                (memory_dir / "wikilinks.md").write_text(wl_md(graph), encoding="utf-8")
                (memory_dir / "wikilinks.json").write_text(
                    _json.dumps(graph, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:
                # Wikilink rebuild is best-effort
                pass

            # Conclude context amortization — refresh derived context files
            # (project_digest.md, commands.md, file_roles.md) so the next
            # RECALL sees current project state. Human-owned files
            # (risk_boundaries.md, docs/) are preserved.
            try:
                sys.path.insert(0, str(Path(__file__).parent.parent / "harness"))
                from context_build import conclude_context
                conclude_context(cwd)
            except Exception:
                # Context conclude is best-effort
                pass

            # Persist retro (lessons learned) to the retro store
            try:
                sys.path.insert(0, str(Path(__file__).parent.parent / "harness"))
                from _retro_conclude import _persist_retro
                conclude_text = (cwd / ".techne" / "loop" / "conclude.txt").read_text()
                _persist_retro(state.task_id, conclude_text, state.task_id)
            except Exception:
                # best-effort — never block DONE on retro failure
                pass

        # Print detailed phase report for the user
        report = format_phase_report(state, old_phase, results, cwd)
        print(report)

        return 0
    else:
        # Record the failed summary but do NOT advance
        state.summary = summary
        write_state(state, cwd)
        return 1


if __name__ == "__main__":
    sys.exit(main())
