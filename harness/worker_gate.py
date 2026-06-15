"""
worker_gate.py — the deterministic FLOOR gate for a returned Kanban deliverable.

The authoritative ANCHOR under the verification panel (skills/kanban/roles.md): a
host-run, model-free acceptance check a worker CANNOT fake — it runs on what came BACK,
not inside the worker. It checks STRUCTURE ("done correctly"), never quality:

  EXISTS    the promised file is present.
  PERSISTENT it's in a durable dir, not scratch/tmp (the stranded-file footgun).
  NON-STUB  not empty / a TODO placeholder / an "I was unable to…" bail.
  CONTRACT  matches the card's declared shape (parses as the format; required fields present).
  GROUNDED  if the card requires sources, at least one source link is present.

"Is the research GOOD / is EVERY claim sourced?" is JUDGMENT — that's the reviewer +
bug-scout panel, not this gate. This is the cheap deterministic floor that runs on EVERY
deliverable; the panel is earned by items that clear it. Pass/fail + the per-check board
feed reward.py / mistakes.py. Mirrors gates.py (GateViolation + a per-check report).
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from gates import GateViolation

# A non-durable location. SINGLE-segment markers match a whole path component exactly
# (so "templates"/"attempt" are NOT flagged); multi-segment markers match as substrings.
_SCRATCH_SEGMENTS = {"tmp", "temp", "scratch", ".cache"}
_SCRATCH_SUBPATHS = ("var/folders",)
# Short bail phrases a worker emits when it gives up — strong non-delivery signal.
_BAIL_RE = re.compile(
    r"\b(i (couldn't|could not|was unable to|cannot|can't)\b.*\b(do|complete|finish|build|implement)"
    r"|not implemented|unable to complete|placeholder|tbd|to be determined)\b",
    re.IGNORECASE,
)
_PLACEHOLDER_ONLY = {"", "todo", "tbd", "n/a", "na", "...", "placeholder", "-"}
_SOURCE_RE = re.compile(r"(https?://\S+|\]\(\s*https?://)", re.IGNORECASE)


@dataclass
class Acceptance:
    """A card's machine-checkable definition-of-done. Without one, the gate has
    nothing to check — the board must put this on the card (see skills/kanban/roles.md)."""
    deliverable_path: str
    must_persist: bool = True
    fmt: str | None = None                 # "json" | "markdown" | None
    required_fields: list[str] = field(default_factory=list)
    require_sources: bool = False
    min_chars: int = 1


@dataclass
class GateResult:
    passed: bool
    checks: dict[str, bool]                 # per-check board: name -> passed
    failures: list[str]                     # one reason per failed check


# ─── individual checks (all deterministic, no model) ────────────────────────────

def _is_persistent(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()   # always absolute, so the tmp_root comparison holds
    tmp_root = Path(tempfile.gettempdir()).resolve()
    try:
        if resolved == tmp_root or tmp_root in resolved.parents:
            return False
    except OSError:
        pass
    parts = {p.lower() for p in resolved.parts}
    joined = str(resolved).replace("\\", "/").lower()
    if parts & _SCRATCH_SEGMENTS or any(m in joined for m in _SCRATCH_SUBPATHS):
        return False
    return True


def _check_non_stub(text: str, min_chars: int) -> tuple[bool, str]:
    stripped = text.strip()
    if len(stripped) < min_chars:
        return False, f"deliverable empty / under {min_chars} chars"
    if stripped.lower() in _PLACEHOLDER_ONLY:
        return False, f"deliverable is a placeholder token: {stripped[:20]!r}"
    # A bail phrase in a SHORT deliverable = the worker gave up. Length-gated to avoid
    # flagging a long legit report that merely quotes "I couldn't get it to work".
    if len(stripped) < 280 and _BAIL_RE.search(stripped):
        return False, "deliverable reads as a non-delivery / bail"
    return True, ""


def _check_contract(text: str, fmt: str | None, required_fields: list[str]) -> tuple[bool, str]:
    if fmt == "json":
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return False, "contract: declared json but does not parse"
        missing = [f for f in required_fields if not (isinstance(obj, dict) and f in obj)]
        if missing:
            return False, f"contract: json missing required field(s): {missing}"
        return True, ""
    # markdown / unknown: presence check only (the floor is structural, not semantic).
    low = text.lower()
    missing = [f for f in required_fields if f.lower() not in low]
    if missing:
        return False, f"contract: missing required section/field(s): {missing}"
    return True, ""


def _has_source_link(text: str) -> bool:
    return bool(_SOURCE_RE.search(text))


# ─── the gate ───────────────────────────────────────────────────────────────────

def check_deliverable(acc: Acceptance) -> GateResult:
    """Run every floor check; return the full per-check board (does not raise)."""
    checks: dict[str, bool] = {}
    failures: list[str] = []
    path = Path(acc.deliverable_path)

    exists = path.exists() and path.is_file()
    checks["exists"] = exists
    if not exists:
        failures.append(f"deliverable missing: {acc.deliverable_path}")

    if acc.must_persist:
        persistent = _is_persistent(path)
        checks["persistent"] = persistent
        if not persistent:
            failures.append(f"deliverable in a scratch/tmp location: {path}")

    if exists:
        text = path.read_text(encoding="utf-8", errors="replace")
        non_stub, why = _check_non_stub(text, acc.min_chars)
        checks["non_stub"] = non_stub
        if not non_stub:
            failures.append(why)

        ok_contract, why = _check_contract(text, acc.fmt, acc.required_fields)
        checks["contract"] = ok_contract
        if not ok_contract:
            failures.append(why)

        if acc.require_sources:
            grounded = _has_source_link(text)
            checks["grounded"] = grounded
            if not grounded:
                failures.append("grounded: card requires sources but no source link found")

    return GateResult(passed=not failures, checks=checks, failures=failures)


def enforce(acc: Acceptance) -> GateResult:
    """Hard enforcement: raise GateViolation if any floor check fails (parity with gates.py)."""
    result = check_deliverable(acc)
    if not result.passed:
        raise GateViolation("GATE FAIL [worker/floor]: " + "; ".join(result.failures))
    return result


def format_result(result: GateResult) -> str:
    """ASCII-safe per-check board (Windows-console friendly)."""
    n = len(result.checks)
    passed = sum(1 for v in result.checks.values() if v)
    lines = [f"FLOOR GATE ({passed}/{n} checks passed):"]
    for name, ok in result.checks.items():
        lines.append(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    for f in result.failures:
        lines.append(f"         -> {f}")
    return "\n".join(lines)
