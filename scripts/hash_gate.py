"""
hash_gate.py — Hashline-style diff context validation.

When diff.txt is submitted at the IMPLEMENT phase, validate that each hunk's
context lines (the unchanged lines, ` ` prefix) actually appear in the real
file at the expected position. If they don't, the agent read a stale copy or
the patch tool mangled whitespace — reject before VERIFY, not after.

Inspired by OMO's Hashline (6.7% → 68.3% edit success improvement).

Public API:
  validate_diff_context(diff_text, project_root) -> (bool, str)
  parse_diff_files(diff_text)                    -> list[(target_file, list[(start, context_lines)])]
"""
from __future__ import annotations

import re
from pathlib import Path


def parse_diff_files(
    diff_text: str,
) -> list[tuple[str, list[tuple[int, list[str]]]]]:
    """
    Parse a unified diff into (target_file, hunks) pairs.
    Each hunk is (old_line_start, context_lines).
    Context lines are the unchanged ` ` lines with the leading space stripped.
    """
    files: list[tuple[str, list[tuple[int, list[str]]]]] = []
    current_file: str | None = None
    current_hunks: list[tuple[int, list[str]]] = []
    hunk_start: int | None = None
    hunk_ctx: list[str] = []

    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            _flush_hunk(current_hunks, hunk_start, hunk_ctx)
            if current_file is not None:
                files.append((current_file, current_hunks))
            raw = line[4:].strip().partition("\t")[0]
            current_file = raw[2:] if raw.startswith(("b/", "a/")) else raw
            current_hunks = []
            hunk_start = None
            hunk_ctx = []

        elif line.startswith("@@ "):
            _flush_hunk(current_hunks, hunk_start, hunk_ctx)
            m = re.match(r"@@ -(\d+)", line)
            hunk_start = int(m.group(1)) if m else 1
            hunk_ctx = []

        elif line.startswith(" ") and hunk_start is not None:
            hunk_ctx.append(line[1:])  # strip leading space

    _flush_hunk(current_hunks, hunk_start, hunk_ctx)
    if current_file is not None:
        files.append((current_file, current_hunks))

    return files


def _flush_hunk(
    hunks: list[tuple[int, list[str]]],
    start: int | None,
    ctx: list[str],
) -> None:
    if start is not None and ctx:
        hunks.append((start, list(ctx)))


def _context_in_file(context_lines: list[str], file_lines: list[str]) -> bool:
    """True if context_lines appear as a contiguous block anywhere in file_lines."""
    if not context_lines:
        return True
    ctx = [l.rstrip() for l in context_lines]
    flines = [l.rstrip() for l in file_lines]
    n = len(ctx)
    for i in range(len(flines) - n + 1):
        if flines[i : i + n] == ctx:
            return True
    return False


def validate_diff_context(
    diff_text: str,
    project_root: Path | None = None,
) -> tuple[bool, str]:
    """
    Validate each hunk's context lines against the real file on disk.

    Returns (True, detail) when all context matches, or (False, reason) when
    context is stale or corrupted.

    Fails open (True) when:
    - A file doesn't exist on disk (new file creation — nothing to compare)
    - A hunk has no context lines (pure addition)
    - The diff has no hunks at all
    """
    root = project_root or Path.cwd()
    files = parse_diff_files(diff_text)

    if not files:
        return (True, "no hunks to validate")

    mismatches: list[str] = []
    checked = 0

    for target_file, hunks in files:
        if not target_file or target_file == "/dev/null":
            continue

        file_path = root / target_file
        if not file_path.exists():
            continue  # new file — no context to check

        try:
            file_lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue  # can't read — fail open

        for hunk_start, ctx_lines in hunks:
            if not ctx_lines:
                continue
            checked += 1

            # First try a position-anchored window (±15 lines around expected start)
            idx = hunk_start - 1  # 0-indexed
            window_s = max(0, idx - 15)
            window_e = min(len(file_lines), idx + len(ctx_lines) + 15)
            found = _context_in_file(ctx_lines, file_lines[window_s:window_e])

            # Fall back to full-file scan (handles drift from earlier hunks)
            if not found:
                found = _context_in_file(ctx_lines, file_lines)

            if not found:
                first = ctx_lines[0][:70].rstrip()
                mismatches.append(
                    f"{target_file} hunk@{hunk_start}: context not in file "
                    f"(first ctx line: {first!r})"
                )

    if mismatches:
        return (False, "; ".join(mismatches[:3]))

    detail = f"{checked} hunk context(s) verified" if checked else "no context to validate (new file)"
    return (True, detail)
