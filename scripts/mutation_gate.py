#!/usr/bin/env python3
"""mutation_gate.py — model-independent test-strength gate (GRAND-PLAN-FINAL W3).

The mutation gate is the *only* HITL-free mechanism that catches a test that was
weak **from the start**. It mutates the target source, runs the (frozen) test
command, and asserts the tests **kill** each mutation. A mutation that *survives*
means the suite does not constrain that behavior — the test is weak/accommodating
-> the gate fails. This breaks the "cycle of self-deception" (LLM-written tests
sharing the blind spots of LLM-written code), because the mutation operators are
**mechanical, not LLM-authored** — model-independent ground truth.

Cost controls (2026 literature — Offutt/Untch "do fewer / smarter / faster"):
  • changed-lines-only scope (mutate the diff, not the repo)
  • a sufficient operator subset (not every operator)
  • a hard mutation cap
  • stop-on-first-survivor is NOT used (we want the full survivor list), but
    stop-on-first-kill per mutant keeps each trial short.

Usage:
    python mutation_gate.py --source FILE --test-cmd "pytest -q tests/foo.py"
    python mutation_gate.py --source FILE --test-cmd "..." --changed-lines 10,11,12
    python mutation_gate.py --source FILE --test-cmd "..." --json --max-mutants 25
    python mutation_gate.py --self-test       # prove a weak test is caught

Exit codes:
    0 — all mutations killed (tests are strong) OR no mutable sites in scope
    1 — at least one mutation survived (tests are weak) — BLOCK
"""
from __future__ import annotations

import argparse
import ast
import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

# ── Mutation operators (the sufficient subset) ───────────────────────────────
# Each maps an AST operator type to the type it is swapped with.
_COMPARE_SWAP = {
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
    ast.Lt: ast.GtE, ast.GtE: ast.Lt,
    ast.Gt: ast.LtE, ast.LtE: ast.Gt,
}
_BINOP_SWAP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult}
_BOOLOP_SWAP = {ast.And: ast.Or, ast.Or: ast.And}


def _candidates(tree: ast.AST) -> list[tuple[ast.AST, str, int]]:
    """Return mutable sites in deterministic (ast.walk) order: (node, kind, lineno).

    The same function is run on the original tree and on each deep-copied mutant
    tree; because ast.walk order is stable for identical trees, the k-th site in
    the copy corresponds to the k-th site in the original.
    """
    out: list[tuple[ast.AST, str, int]] = []
    for node in ast.walk(tree):
        ln = getattr(node, "lineno", 0)
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _COMPARE_SWAP:
            out.append((node, "compare", ln))
        elif isinstance(node, ast.BoolOp) and type(node.op) in _BOOLOP_SWAP:
            out.append((node, "boolop", ln))
        elif isinstance(node, ast.BinOp) and type(node.op) in _BINOP_SWAP:
            out.append((node, "binop", ln))
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            out.append((node, "bool", ln))
        elif isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
            out.append((node, "int", ln))
    return out


def _apply(node: ast.AST, kind: str) -> str:
    """Mutate `node` in place; return a short human label."""
    if kind == "compare":
        old = type(node.ops[0])           # type: ignore[attr-defined]
        node.ops[0] = _COMPARE_SWAP[old]()  # type: ignore[attr-defined]
        return f"compare {old.__name__}->{_COMPARE_SWAP[old].__name__}"
    if kind == "boolop":
        old = type(node.op)               # type: ignore[attr-defined]
        node.op = _BOOLOP_SWAP[old]()     # type: ignore[attr-defined]
        return f"boolop {old.__name__}->{_BOOLOP_SWAP[old].__name__}"
    if kind == "binop":
        old = type(node.op)               # type: ignore[attr-defined]
        node.op = _BINOP_SWAP[old]()      # type: ignore[attr-defined]
        return f"binop {old.__name__}->{_BINOP_SWAP[old].__name__}"
    if kind == "bool":
        node.value = not node.value       # type: ignore[attr-defined]
        return f"bool->{node.value}"       # type: ignore[attr-defined]
    if kind == "int":
        node.value = node.value + 1       # type: ignore[attr-defined]
        return f"int->{node.value}"        # type: ignore[attr-defined]
    return kind


def _run_tests(test_cmd: str, timeout: int) -> bool:
    """Run the test command. Return True if the suite FAILED (mutation killed)."""
    try:
        r = subprocess.run(test_cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode != 0
    except subprocess.TimeoutExpired:
        # A timeout under mutation is treated as a kill (the mutant broke something).
        return True


def run_gate(source: Path, test_cmd: str, changed_lines: set[int] | None = None,
             max_mutants: int = 25, timeout: int = 120) -> dict:
    """Mutate `source`, run `test_cmd` per mutant, report kills/survivors.

    Always restores the original file (try/finally), even on error/interrupt.
    """
    original = source.read_text(encoding="utf-8")
    try:
        tree = ast.parse(original)
    except SyntaxError as exc:
        return {"passed": True, "reason": f"unparseable source, skipped ({exc})",
                "killed": 0, "survived": 0, "survivors": []}

    sites = _candidates(tree)
    if changed_lines:
        scope = [i for i, (_, _, ln) in enumerate(sites) if ln in changed_lines]
    else:
        scope = list(range(len(sites)))
    scope = scope[:max_mutants]

    if not scope:
        return {"passed": True, "reason": "no mutable sites in scope",
                "killed": 0, "survived": 0, "survivors": []}

    killed = 0
    survivors: list[dict] = []
    try:
        for k in scope:
            mtree = copy.deepcopy(tree)
            msites = _candidates(mtree)
            node, kind, lineno = msites[k]
            label = _apply(node, kind)
            mutant = ast.unparse(ast.fix_missing_locations(mtree))
            source.write_text(mutant, encoding="utf-8")
            if _run_tests(test_cmd, timeout):
                killed += 1
            else:
                survivors.append({"line": lineno, "mutation": label})
    finally:
        source.write_text(original, encoding="utf-8")  # ALWAYS restore

    total = killed + len(survivors)
    kill_rate = (killed / total) if total else 1.0
    return {
        "passed": len(survivors) == 0,
        "killed": killed,
        "survived": len(survivors),
        "kill_rate": round(kill_rate, 3),
        "survivors": survivors,
        "reason": ("all mutations killed — tests are strong" if not survivors
                   else f"{len(survivors)} mutation(s) survived — tests do not constrain this behavior"),
    }


# ── Self-test: prove a weak suite is caught, a strong suite passes ───────────
def _self_test() -> int:
    src = "def is_adult(age):\n    return age >= 18\n"
    weak = "from mod import is_adult\n\ndef test_weak():\n    assert is_adult(40)\n"
    strong = ("from mod import is_adult\n\n"
              "def test_boundary():\n"
              "    assert is_adult(18)\n"
              "    assert not is_adult(17)\n"
              "    assert not is_adult(0)\n")
    ok = True
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        (dp / "mod.py").write_text(src)
        (dp / "test_weak.py").write_text(weak)
        (dp / "test_strong.py").write_text(strong)
        py = sys.executable

        weak_res = run_gate(dp / "mod.py",
                            f'"{py}" -m pytest -q "{dp / "test_weak.py"}"', timeout=60)
        strong_res = run_gate(dp / "mod.py",
                              f'"{py}" -m pytest -q "{dp / "test_strong.py"}"', timeout=60)

    print("  weak suite   ->", "BLOCKED (survivors found) [correct]" if not weak_res["passed"]
          else "PASSED [WRONG: gate failed to catch weak test]", "|", weak_res["survivors"])
    print("  strong suite ->", "PASSED [correct]" if strong_res["passed"]
          else f"BLOCKED [WRONG: false positive] {strong_res['survivors']}")

    if weak_res["passed"]:
        print("  SELF-TEST FAIL: weak test was not caught"); ok = False
    if not strong_res["passed"]:
        print("  SELF-TEST FAIL: strong test false-positived"); ok = False
    print("  SELF-TEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(description="Model-independent mutation-strength gate")
    p.add_argument("--source", help="Source file to mutate")
    p.add_argument("--test-cmd", help="Command that runs the frozen tests")
    p.add_argument("--changed-lines", help="Comma-separated line numbers to scope mutation to")
    p.add_argument("--max-mutants", type=int, default=25)
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--json", action="store_true")
    p.add_argument("--self-test", action="store_true", help="Prove the gate catches a weak test")
    args = p.parse_args()

    if args.self_test:
        return _self_test()

    if not args.source or not args.test_cmd:
        p.error("--source and --test-cmd are required (or use --self-test)")

    changed = None
    if args.changed_lines:
        changed = {int(x) for x in args.changed_lines.split(",") if x.strip()}

    res = run_gate(Path(args.source), args.test_cmd, changed,
                  args.max_mutants, args.timeout)

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        mark = "PASS" if res["passed"] else "FAIL"
        print(f"  [{mark}] mutation gate: {res['reason']}")
        print(f"    killed={res['killed']} survived={res['survived']} kill_rate={res.get('kill_rate')}")
        for s in res["survivors"][:10]:
            print(f"    SURVIVED line {s['line']}: {s['mutation']}")
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
