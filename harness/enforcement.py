"""
enforcement.py — the shared deterministic enforcement core.

The pipeline can be driven two ways over the same phases:

  - orchestrator_loop.Loop     host-driven: a host agent delegates each phase
                               to a subagent (delegate_task) and submits the result
  - driver.run_plan            model-backed: an injected model produces each phase
                               artifact (autonomous / RL trajectory collection)

Both must run the *same* deterministic checks — gates, focus/scope
measurement, intent reasoning, and SHA test verification. This module extracts the
checks into pure functions that:

  - never print and never mutate global state
  - never raise (they catch GateViolation and report it structurally)
  - return dataclasses the caller acts on: retry, halt, or feed the RL reward

The orchestrator loop calls these functions so its reward signal reflects real
enforcement rather than hardcoded `gate_pass=True` signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from gates import GateViolation
from gate_registry import GateRegistry
from measure import run_measurements
from intent_reasoner import verdict_to_gate
from sha_gate import gate_test_output

HARNESS_DIR = Path(__file__).parent
MEMORY_DIR = HARNESS_DIR.parent / ".techne" / "memory"


# ─── Result dataclasses ──────────────────────────────────────────────────────

@dataclass
class GateResult:
    """Outcome of running the hard-gate registry against a diff."""
    passed: bool
    gate_name: str = ""        # name of the violated gate (parsed from "[name]")
    violation: str = ""        # full violation text, for retry feedback


@dataclass
class ScopeResult:
    """Outcome of focus/scope measurement + intent L1/L2 gate."""
    diff_focused: bool
    scope_creep: bool
    intent: dict = field(default_factory=dict)
    intent_mismatch: bool = False   # the intent gate fired (MISMATCH >= 70%)
    violation: str = ""

    @property
    def scope_clean(self) -> bool:
        """Single boolean for the RL reward signal."""
        return self.diff_focused and not self.scope_creep and not self.intent_mismatch


@dataclass
class VerifyResult:
    """Outcome of the SHA gate on captured test output."""
    passed: bool
    sha: str = ""
    error: str = ""


# ─── Registry construction ───────────────────────────────────────────────────

def build_registry() -> GateRegistry:
    """Construct the standard gate registry (plugins discovered, config applied)."""
    registry = GateRegistry()
    registry.discover_plugins()
    registry.load_config()
    return registry


# ─── The three checks ────────────────────────────────────────────────────────

def run_gates(diff: str, registry: GateRegistry | None = None) -> GateResult:
    """
    Run all enabled hard gates against a diff.

    Returns a GateResult — never raises. A caller that built its own registry
    (e.g. with host-injected gates) should pass it so those gates run too.
    """
    reg = registry or build_registry()
    try:
        reg.run_all(diff)
        return GateResult(passed=True)
    except GateViolation as e:
        msg = str(e)
        name = msg.split("[")[1].split("]")[0] if "[" in msg else "unknown"
        return GateResult(passed=False, gate_name=name, violation=msg)


def measure_scope(task: str, diff: str, semantic_verdict=None) -> ScopeResult:
    """
    Run focus + scope-creep measurement and the intent L1/L2 gate.

    Returns a ScopeResult — never raises. `intent_mismatch` is True when the
    intent gate would have halted the pipeline (MISMATCH at >= 70% confidence).
    """
    m = run_measurements(task, diff, semantic_verdict=semantic_verdict)
    intent = m["_intent"]
    mismatch = False
    violation = ""
    try:
        verdict_to_gate(intent, task)
    except GateViolation as e:
        mismatch = True
        violation = str(e)
    return ScopeResult(
        diff_focused=m["diff_focused"],
        scope_creep=m["scope_creep"],
        intent=intent,
        intent_mismatch=mismatch,
        violation=violation,
    )


def verify_tests(test_output: str, *, memory_dir: Path | None = None, review_only: bool = False) -> VerifyResult:
    """
    Persist test output and run the SHA gate (real tests ran, no fakes, unique
    hash). Returns a VerifyResult — never raises.
    """
    mdir = memory_dir or MEMORY_DIR
    reports_dir = mdir.parent / "reports" / "verify"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / "test_output.txt"
    out_path.write_text(test_output, encoding="utf-8")
    try:
        sha = gate_test_output(
            test_output_path=str(out_path),
            run_log_path=str(mdir / "run_log.json"),
            review_only=review_only,
        )
        return VerifyResult(passed=True, sha=sha)
    except Exception as e:
        return VerifyResult(passed=False, error=str(e))


if __name__ == "__main__":
    # Smoke test: the three checks on a trivial diff.
    diff = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n"
    g = run_gates(diff)
    print(f"run_gates: passed={g.passed} gate={g.gate_name or '-'}")
    s = measure_scope("update app.py", diff)
    print(f"measure_scope: focused={s.diff_focused} creep={s.scope_creep} clean={s.scope_clean}")
    import tempfile
    v = verify_tests(
        "ran 10 tests, all passed, 0 errors\n" + "detail line\n" * 5,
        memory_dir=Path(tempfile.mkdtemp()),
    )
    print(f"verify_tests: passed={v.passed} sha={v.sha[:12] if v.sha else v.error[:40]}")
    print("enforcement smoke test: OK")
