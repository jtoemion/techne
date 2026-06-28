"""
test_harness.py — stress test every gate and sha_gate scenario.

Run from the harness/ directory:
    python test_harness.py

No API key required — tests the enforcement layer only, not the LLM.
"""

import hashlib
import json
import os
import sys
import tempfile
import textwrap
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

from harness.gates import (
    GateViolation,
    gate_no_console_log,
    gate_no_gSSP,
    gate_no_redirect_outside_middleware,
    gate_no_router_import,
    gate_no_ts_ignore,
    run_all_gates,
)
from sha_gate import gate_test_output, sha256_file

# ─── Test harness ─────────────────────────────────────────────────────────────

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results: list[tuple[str, bool, str]] = []


def expect_pass(label: str, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
        results.append((label, True, ""))
        print(f"  {PASS} {label}")
    except Exception as e:
        results.append((label, False, str(e)))
        print(f"  {FAIL} {label}\n       raised unexpectedly: {e}")


def expect_fail(label: str, expected_fragment: str, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
        results.append((label, False, "no exception raised"))
        print(f"  {FAIL} {label}\n       expected GateViolation, got nothing")
    except GateViolation as e:
        msg = str(e)
        if expected_fragment.lower() in msg.lower():
            results.append((label, True, ""))
            print(f"  {PASS} {label}")
        else:
            results.append((label, False, f"wrong message: {msg}"))
            print(f"  {FAIL} {label}\n       expected '{expected_fragment}' in: {msg}")
    except Exception as e:
        results.append((label, False, f"wrong exception type: {type(e).__name__}: {e}"))
        print(f"  {FAIL} {label}\n       wrong exception: {e}")


# ─── gate_no_redirect_outside_middleware ──────────────────────────────────────

def test_redirect_gate():
    print("\n[gate_no_redirect_outside_middleware]")

    clean_diff = textwrap.dedent("""\
        diff --git a/middleware.ts b/middleware.ts
        --- a/middleware.ts
        +++ b/middleware.ts
        @@ -1,4 +1,6 @@
         export function middleware(req) {
        +  if (!req.cookies.token) redirect('/login')
           return NextResponse.next()
         }
    """)
    expect_pass("redirect() inside middleware.ts → PASS", gate_no_redirect_outside_middleware, clean_diff)

    bad_diff = textwrap.dedent("""\
        diff --git a/app/page.tsx b/app/page.tsx
        --- a/app/page.tsx
        +++ b/app/page.tsx
        @@ -3,4 +3,5 @@
         export default function Page() {
        +  redirect('/dashboard')
           return <div>hello</div>
         }
    """)
    expect_fail(
        "redirect() in page.tsx → FAIL",
        "outside middleware.ts",
        gate_no_redirect_outside_middleware,
        bad_diff,
    )

    no_redirect = "const x = 1;\nconst y = 2;\n"
    expect_pass("diff with no redirect() → PASS", gate_no_redirect_outside_middleware, no_redirect)

    empty = ""
    expect_pass("empty diff → PASS", gate_no_redirect_outside_middleware, empty)


# ─── gate_no_router_import ────────────────────────────────────────────────────

def test_router_import_gate():
    print("\n[gate_no_router_import]")

    good = "import { useRouter } from 'next/navigation'\n"
    expect_pass("next/navigation import → PASS", gate_no_router_import, good)

    bad_single = "import { useRouter } from 'next/router'\n"
    expect_fail("next/router single-quote → FAIL", "next/router", gate_no_router_import, bad_single)

    bad_double = 'import { useRouter } from "next/router"\n'
    expect_fail("next/router double-quote → FAIL", "next/router", gate_no_router_import, bad_double)

    comment_line = "// import { useRouter } from 'next/router'\n"
    expect_pass("commented-out next/router → PASS", gate_no_router_import, comment_line)


# ─── gate_no_gSSP ─────────────────────────────────────────────────────────────

def test_gSSP_gate():
    print("\n[gate_no_gSSP]")

    good = "export default async function Page() { return <div/> }\n"
    expect_pass("async server component → PASS", gate_no_gSSP, good)

    bad = "export async function getServerSideProps() { return { props: {} } }\n"
    expect_fail("getServerSideProps usage → FAIL", "getServerSideProps", gate_no_gSSP, bad)

    in_comment = "# getServerSideProps is removed\n"
    expect_pass("getServerSideProps in comment → PASS", gate_no_gSSP, in_comment)


# ─── gate_no_ts_ignore ────────────────────────────────────────────────────────

def test_ts_ignore_gate():
    print("\n[gate_no_ts_ignore]")

    clean = "const x: string = getValue()\n"
    expect_pass("typed code without suppression → PASS", gate_no_ts_ignore, clean)

    ignore = "// @ts-ignore\nconst x = bad()\n"
    expect_fail("@ts-ignore → FAIL", "ts-ignore", gate_no_ts_ignore, ignore)

    nocheck = "// @ts-nocheck\n"
    expect_fail("@ts-nocheck → FAIL", "ts-nocheck", gate_no_ts_ignore, nocheck)


# ─── gate_no_console_log ─────────────────────────────────────────────────────

def test_console_log_gate():
    print("\n[gate_no_console_log]")

    clean = "+  return <Product />\n"
    expect_pass("no console.log → PASS", gate_no_console_log, clean)

    bad = "+  console.log('debug', value)\n"
    expect_fail("added console.log → FAIL", "console.log", gate_no_console_log, bad)

    context_line = "   console.log('existing, not added')\n"
    expect_pass("unchanged console.log line (no '+') → PASS", gate_no_console_log, context_line)


# ─── run_all_gates ────────────────────────────────────────────────────────────

def test_run_all_gates():
    print("\n[run_all_gates]")

    completely_clean = textwrap.dedent("""\
        diff --git a/components/Hero.tsx b/components/Hero.tsx
        +  return <section>Hello</section>
    """)
    expect_pass("clean diff passes all gates → PASS", run_all_gates, completely_clean)

    multi_violation = textwrap.dedent("""\
        import { useRouter } from 'next/router'
        // @ts-ignore
        +  console.log('bad')
    """)
    # Should fail on first violation found (router import)
    expect_fail("multi-violation diff → FAIL on first", "next/router", run_all_gates, multi_violation)


# ─── sha256_file ──────────────────────────────────────────────────────────────

def test_sha256_file():
    print("\n[sha256_file]")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="wb") as f:
        f.write(b"hello world")
        tmp = f.name

    try:
        h = sha256_file(tmp)
        expected = hashlib.sha256(b"hello world").hexdigest()
        if h == expected:
            results.append(("sha256_file correct hash", True, ""))
            print(f"  {PASS} sha256_file correct hash")
        else:
            results.append(("sha256_file correct hash", False, f"got {h}"))
            print(f"  {FAIL} sha256_file wrong hash: {h}")

        h2 = sha256_file(tmp)
        if h == h2:
            results.append(("sha256_file deterministic", True, ""))
            print(f"  {PASS} sha256_file deterministic")
        else:
            results.append(("sha256_file deterministic", False, ""))
            print(f"  {FAIL} sha256_file not deterministic")
    finally:
        os.unlink(tmp)


# ─── gate_test_output ─────────────────────────────────────────────────────────

def test_sha_gate():
    print("\n[gate_test_output]")

    with tempfile.TemporaryDirectory() as tmp_dir:
        output_path = os.path.join(tmp_dir, "test_output.txt")
        log_path = os.path.join(tmp_dir, "run_log.json")

        # 1. Missing file
        expect_fail(
            "missing test_output.txt → FAIL",
            "missing",
            gate_test_output,
            output_path,
            log_path,
        )

        # 2. Empty file
        Path(output_path).write_text("   ", encoding="utf-8")
        expect_fail(
            "empty test_output.txt → FAIL",
            "too short",
            gate_test_output,
            output_path,
            log_path,
        )

        # 3. Contains FAILED
        Path(output_path).write_text(
            "=== BUILD ===\n✗ FAILED: 2 tests failed\nsome long error output here",
            encoding="utf-8",
        )
        expect_fail(
            "test output with FAILED → FAIL",
            "failed",
            gate_test_output,
            output_path,
            log_path,
        )

        # 4. No pass indicator
        Path(output_path).write_text(
            "=== BUILD ===\nsome output without any indication\n" + "x" * 100,
            encoding="utf-8",
        )
        expect_fail(
            "no pass indicator → FAIL",
            "no pass indicator",
            gate_test_output,
            output_path,
            log_path,
        )

        # 5. Valid passing output
        passing = textwrap.dedent("""\
            === BUILD ===
            ✓ Compiled successfully in 2.4s

            === TYPE CHECK ===
            No issues found

            === LINT ===
            ✓ No ESLint warnings or errors
        """)
        Path(output_path).write_text(passing, encoding="utf-8")
        expect_pass(
            "valid passing test output → PASS",
            gate_test_output,
            output_path,
            log_path,
        )

        # 6. Log was written
        if os.path.exists(log_path):
            log = json.loads(Path(log_path).read_text())
            if len(log) == 1 and log[0]["status"] == "PASSED":
                results.append(("run_log.json written correctly", True, ""))
                print(f"  {PASS} run_log.json written correctly")
            else:
                results.append(("run_log.json written correctly", False, str(log)))
                print(f"  {FAIL} run_log.json malformed: {log}")
        else:
            results.append(("run_log.json written correctly", False, "file missing"))
            print(f"  {FAIL} run_log.json not written")

        # 7. Identical hash triggers warning (should still PASS, just warn)
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            try:
                gate_test_output(output_path, log_path)
                warned = "identical" in buf.getvalue().lower() or "same" in buf.getvalue().lower()
                if warned:
                    results.append(("identical hash triggers warning", True, ""))
                    print(f"  {PASS} identical hash triggers warning")
                else:
                    results.append(("identical hash triggers warning", False, buf.getvalue()))
                    print(f"  {FAIL} no warning for identical hash: {buf.getvalue()!r}")
            except GateViolation:
                results.append(("identical hash still passes gate", False, "raised GateViolation"))
                print(f"  {FAIL} identical hash raised GateViolation — should only warn")

        # 8. npm err! pattern
        Path(output_path).write_text(
            "npm ERR! code ELIFECYCLE\nnpm ERR! errno 1\n" + "err " * 20,
            encoding="utf-8",
        )
        expect_fail(
            "npm ERR! in output → FAIL",
            "npm err",
            gate_test_output,
            output_path,
            log_path,
        )

        # 9. TypeScript error pattern
        Path(output_path).write_text(
            "error TS2345: Argument of type 'string' is not assignable\n" + "x" * 60,
            encoding="utf-8",
        )
        expect_fail(
            "error TS in output → FAIL",
            "error ts",
            gate_test_output,
            output_path,
            log_path,
        )


# ─── conductor path resolution ────────────────────────────────────────────────

def test_conductor_paths():
    print("\n[conductor path resolution]")

    harness_dir = ROOT
    hermes_dir = Path.home() / ".hermes"

    agents = list((hermes_dir / "agents").glob("*.md"))
    if len(agents) >= 5 and any(a.name == "context-preflight.md" for a in agents):
        results.append(("agent files include context-preflight", True, ""))
        print(f"  {PASS} agent files include context-preflight: {[a.name for a in agents]}")
    else:
        results.append(("agent files include context-preflight", False, str([a.name for a in agents])))
        print(f"  {FAIL} expected context-preflight agent, found {len(agents)}: {[a.name for a in agents]}")

    skills = list((hermes_dir / "skills" / "techne-skills").glob("*.md"))
    if len(skills) >= 2:
        results.append(("skill files found", True, ""))
        print(f"  {PASS} skill files found: {[s.name for s in skills]}")
    else:
        results.append(("skill files found", False, str([s.name for s in skills])))
        print(f"  {FAIL} expected ≥2 skill files, found {len(skills)}")

    memory_dir = harness_dir / "memory"
    if memory_dir.exists():
        results.append(("memory/ directory exists", True, ""))
        print(f"  {PASS} memory/ directory exists")
    else:
        results.append(("memory/ directory exists", False, ""))
        print(f"  {FAIL} memory/ directory missing")

    for agent_md in agents:
        text = agent_md.read_text(encoding="utf-8")
        stale = ".claude/agents" in text or ".claude/skills" in text
        if stale:
            results.append((f"{agent_md.name} has stale paths", False, ""))
            print(f"  {FAIL} {agent_md.name} still references old .claude/ paths")
        else:
            results.append((f"{agent_md.name} paths clean", True, ""))
            print(f"  {PASS} {agent_md.name} paths clean")


# ─── skills file format validation ────────────────────────────────────────────

def test_skills_format():
    print("\n[skills file format]")

    harness_dir = ROOT
    # Rule files need weights + line limits; discipline files are process guides
    # RL-Proposed Additions section adds ~15 lines — raise limit to 80
    RULE_FILES = {"nextjs.md", "typescript.md"}
    RULE_LINE_LIMIT = 80  # was 50 — increased for RL-Proposed Additions section

    for skill_file in (harness_dir / "skills").glob("*.md"):
        text = skill_file.read_text(encoding="utf-8")
        lines = text.splitlines()
        is_rule_file = skill_file.name in RULE_FILES

        if is_rule_file:
            if len(lines) <= RULE_LINE_LIMIT:
                results.append((f"{skill_file.name} ≤{RULE_LINE_LIMIT} lines", True, ""))
                print(f"  {PASS} {skill_file.name}: {len(lines)} lines (≤{RULE_LINE_LIMIT})")
            else:
                results.append((f"{skill_file.name} ≤{RULE_LINE_LIMIT} lines", False, f"{len(lines)} lines"))
                print(f"  {FAIL} {skill_file.name}: {len(lines)} lines — exceeds {RULE_LINE_LIMIT} line limit")

            weight_entries = [l for l in lines if "weight:" in l]
            if weight_entries:
                results.append((f"{skill_file.name} has weight annotations", True, ""))
                print(f"  {PASS} {skill_file.name}: {len(weight_entries)} weight annotations")
            else:
                results.append((f"{skill_file.name} has weight annotations", False, ""))
                print(f"  {FAIL} {skill_file.name}: no weight annotations found")
        else:
            # Discipline files: just verify they exist and have content
            if len(lines) > 5:
                results.append((f"{skill_file.name} has content", True, ""))
                print(f"  {PASS} {skill_file.name}: {len(lines)} lines (discipline file)")
            else:
                results.append((f"{skill_file.name} has content", False, f"only {len(lines)} lines"))
                print(f"  {FAIL} {skill_file.name}: too short for a discipline file")


# ─── Run all ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("HARNESS STRESS TEST")
    print("=" * 60)

    test_redirect_gate()
    test_router_import_gate()
    test_gSSP_gate()
    test_ts_ignore_gate()
    test_console_log_gate()
    test_run_all_gates()
    test_sha256_file()
    test_sha_gate()
    test_conductor_paths()
    test_skills_format()

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = total - passed

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
        print("\nFailed tests:")
        for label, ok, reason in results:
            if not ok:
                print(f"  {FAIL} {label}: {reason}")
    else:
        print("  — all clear")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)
