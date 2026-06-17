"""
test_synthetic.py — end-to-end synthetic project test.

Creates a fake Next.js project, generates realistic agent diffs
(good and bad), runs the full gate + SHA pipeline, and reports
what gets caught vs what slips through.

No API key needed — we simulate agent output directly.

Run from harness/:
    python test_synthetic.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(TESTS_DIR)); import _mem_guard  # noqa: snapshots memory/, restores at exit

from gates import GateViolation, run_all_gates
from sha_gate import gate_test_output

SEP = "=" * 64
SUBSEP = "-" * 48


# ─── Synthetic project scaffold ───────────────────────────────────────────────

PROJECT_FILES: dict[str, str] = {
    "middleware.ts": textwrap.dedent("""\
        import { NextResponse } from 'next/server'
        import type { NextRequest } from 'next/server'

        export function middleware(request: NextRequest) {
          const token = request.cookies.get('token')
          if (!token) {
            return NextResponse.redirect(new URL('/login', request.url))
          }
          return NextResponse.next()
        }
    """),
    "app/layout.tsx": textwrap.dedent("""\
        import type { Metadata } from 'next'

        export const metadata: Metadata = {
          title: 'Soapure',
          description: 'Handmade soap and perfume',
        }

        export default function RootLayout({ children }: { children: React.ReactNode }) {
          return (
            <html lang="id">
              <body>{children}</body>
            </html>
          )
        }
    """),
    "app/products/[slug]/page.tsx": textwrap.dedent("""\
        import { getProduct } from '@/lib/products'

        export default async function ProductPage({ params }: { params: Promise<{ slug: string }> }) {
          const { slug } = await params
          const product = await getProduct(slug)
          return <div>{product.name}</div>
        }
    """),
    "app/login/page.tsx": textwrap.dedent("""\
        'use client'
        import { useState } from 'react'

        export default function LoginPage() {
          const [email, setEmail] = useState('')
          return (
            <form>
              <input value={email} onChange={e => setEmail(e.target.value)} />
            </form>
          )
        }
    """),
    "lib/products.ts": textwrap.dedent("""\
        export async function getProduct(slug: string) {
          const res = await fetch(`/api/products/${slug}`)
          return res.json()
        }
    """),
}


def create_synthetic_project(base_dir: Path) -> None:
    for rel_path, content in PROJECT_FILES.items():
        full_path = base_dir / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")


# ─── Simulated agent diffs ────────────────────────────────────────────────────
# Each diff is what a drifting (or well-behaved) agent might produce.

DIFFS: list[dict] = [
    {
        "id": "clean-feature",
        "description": "Add a sale badge to ProductPage — no violations",
        "expect": "PASS",
        "diff": textwrap.dedent("""\
            diff --git a/app/products/[slug]/page.tsx b/app/products/[slug]/page.tsx
            --- a/app/products/[slug]/page.tsx
            +++ b/app/products/[slug]/page.tsx
            @@ -1,6 +1,9 @@
             import { getProduct } from '@/lib/products'
            +import { Badge } from '@/components/ui/Badge'

             export default async function ProductPage({ params }: { params: Promise<{ slug: string }> }) {
               const { slug } = await params
               const product = await getProduct(slug)
            -  return <div>{product.name}</div>
            +  return (
            +    <div>
            +      {product.onSale && <Badge variant="sale">On Sale</Badge>}
            +      <h1>{product.name}</h1>
            +    </div>
            +  )
             }
        """),
    },
    {
        "id": "redirect-in-page",
        "description": "Agent puts redirect() in a page component instead of middleware",
        "expect": "GATE_FAIL",
        "expect_gate": "nextjs/redirect",
        "diff": textwrap.dedent("""\
            diff --git a/app/products/[slug]/page.tsx b/app/products/[slug]/page.tsx
            --- a/app/products/[slug]/page.tsx
            +++ b/app/products/[slug]/page.tsx
            @@ -1,6 +1,10 @@
            +import { redirect } from 'next/navigation'
             import { getProduct } from '@/lib/products'

             export default async function ProductPage({ params }: { params: Promise<{ slug: string }> }) {
               const { slug } = await params
               const product = await getProduct(slug)
            +  if (!product) redirect('/404')
               return <div>{product.name}</div>
             }
        """),
    },
    {
        "id": "old-router-import",
        "description": "Agent uses deprecated next/router instead of next/navigation",
        "expect": "GATE_FAIL",
        "expect_gate": "nextjs/router-import",
        "diff": textwrap.dedent("""\
            diff --git a/app/login/page.tsx b/app/login/page.tsx
            --- a/app/login/page.tsx
            +++ b/app/login/page.tsx
            @@ -1,5 +1,6 @@
             'use client'
             import { useState } from 'react'
            +import { useRouter } from 'next/router'

             export default function LoginPage() {
               const [email, setEmail] = useState('')
            +  const router = useRouter()
               return (
                 <form onSubmit={() => router.push('/dashboard')}>
                   <input value={email} onChange={e => setEmail(e.target.value)} />
                 </form>
               )
             }
        """),
    },
    {
        "id": "gssp-in-app-router",
        "description": "Agent writes getServerSideProps in an App Router project",
        "expect": "GATE_FAIL",
        "expect_gate": "nextjs/gSSP",
        "diff": textwrap.dedent("""\
            diff --git a/app/products/[slug]/page.tsx b/app/products/[slug]/page.tsx
            --- a/app/products/[slug]/page.tsx
            +++ b/app/products/[slug]/page.tsx
            @@ -1,6 +1,14 @@
             import { getProduct } from '@/lib/products'

            +export async function getServerSideProps({ params }) {
            +  const product = await getProduct(params.slug)
            +  return { props: { product } }
            +}
            +
            -export default async function ProductPage({ params }: { params: Promise<{ slug: string }> }) {
            +export default function ProductPage({ product }) {
            -  const { slug } = await params
            -  const product = await getProduct(slug)
               return <div>{product.name}</div>
             }
        """),
    },
    {
        "id": "ts-ignore-escape",
        "description": "Agent suppresses a type error with @ts-ignore instead of fixing it",
        "expect": "GATE_FAIL",
        "expect_gate": "ts/suppress",
        "diff": textwrap.dedent("""\
            diff --git a/lib/products.ts b/lib/products.ts
            --- a/lib/products.ts
            +++ b/lib/products.ts
            @@ -1,4 +1,6 @@
             export async function getProduct(slug: string) {
               const res = await fetch(`/api/products/${slug}`)
            +  // @ts-ignore — res.json() type doesn't match Product
               return res.json()
             }
        """),
    },
    {
        "id": "console-log-left-in",
        "description": "Agent leaves debug console.log in production path",
        "expect": "GATE_FAIL",
        "expect_gate": "general/console-log",
        "diff": textwrap.dedent("""\
            diff --git a/lib/products.ts b/lib/products.ts
            --- a/lib/products.ts
            +++ b/lib/products.ts
            @@ -1,4 +1,6 @@
             export async function getProduct(slug: string) {
            +  console.log('fetching product', slug)
               const res = await fetch(`/api/products/${slug}`)
               return res.json()
             }
        """),
    },
    {
        "id": "multi-violation",
        "description": "Agent drift: multiple violations in one diff",
        "expect": "GATE_FAIL",
        "expect_gate": "nextjs/router-import",  # first gate to fire
        "diff": textwrap.dedent("""\
            diff --git a/app/login/page.tsx b/app/login/page.tsx
            --- a/app/login/page.tsx
            +++ b/app/login/page.tsx
            @@ -1,5 +1,10 @@
             'use client'
             import { useState } from 'react'
            +import { useRouter } from 'next/router'

             export default function LoginPage() {
               const [email, setEmail] = useState('')
            +  // @ts-ignore
            +  const router = useRouter()
            +  console.log('login render')
               return <form><input value={email}/></form>
             }
        """),
    },
    {
        "id": "commented-router-import",
        "description": "Comment mentions next/router — should NOT trigger gate",
        "expect": "PASS",
        "diff": textwrap.dedent("""\
            diff --git a/app/login/page.tsx b/app/login/page.tsx
            --- a/app/login/page.tsx
            +++ b/app/login/page.tsx
            @@ -1,5 +1,7 @@
             'use client'
             import { useState } from 'react'
            +// NOTE: use next/navigation not next/router in App Router
            +import { useRouter } from 'next/navigation'

             export default function LoginPage() {
        """),
    },
    {
        "id": "redirect-in-middleware-is-fine",
        "description": "redirect() correctly inside middleware.ts — should PASS",
        "expect": "PASS",
        "diff": textwrap.dedent("""\
            diff --git a/middleware.ts b/middleware.ts
            --- a/middleware.ts
            +++ b/middleware.ts
            @@ -3,6 +3,9 @@

             export function middleware(request: NextRequest) {
               const token = request.cookies.get('token')
            +  const isAdmin = request.cookies.get('role')?.value === 'admin'
            +  if (!token) {
            +    return NextResponse.redirect(new URL('/login', request.url))
            +  }
            +  if (!isAdmin && request.nextUrl.pathname.startsWith('/admin')) {
            +    redirect('/403')
            +  }
               return NextResponse.next()
             }
        """),
    },
]


# ─── SHA gate scenarios ────────────────────────────────────────────────────────

SHA_SCENARIOS: list[dict] = [
    {
        "id": "honest-verifier",
        "description": "Verifier writes real build output",
        "expect": "PASS",
        "content": textwrap.dedent("""\
            === BUILD ===
            info  - Compiled successfully

            === TYPE CHECK ===
            No issues found

            === LINT ===
            No ESLint warnings or errors
        """),
    },
    {
        "id": "fake-touch",
        "description": "Agent does `touch test_output.txt` and writes nothing",
        "expect": "FAIL",
        "content": "",
    },
    {
        "id": "faked-pass-message",
        "description": "Agent writes a fake 'passed' message without real output",
        "expect": "FAIL",
        "content": "passed",  # too short
    },
    {
        "id": "build-failure",
        "description": "Real build failure — agent cannot hide it",
        "expect": "FAIL",
        "content": textwrap.dedent("""\
            === BUILD ===
            Failed to compile.

            ./app/login/page.tsx
            Type error: Property 'push' does not exist on type 'never'.

            npm ERR! code ELIFECYCLE
            npm ERR! errno 1
        """),
    },
    {
        "id": "type-error",
        "description": "TypeScript error TS2345 in output",
        "expect": "FAIL",
        "content": textwrap.dedent("""\
            === TYPE CHECK ===
            error TS2345: Argument of type 'string' is not assignable to parameter of type 'number'.
            Found 1 error in app/lib/products.ts:12

            === BUILD ===
            info  - Compiled successfully
        """),
    },
    {
        "id": "real-passing-output",
        "description": "Full realistic Next.js build output with all checks passing",
        "expect": "PASS",
        "content": textwrap.dedent("""\
            === BUILD ===
            info  - Linting and checking validity of types...
            info  - Creating an optimized production build...
            info  - Compiled successfully
            info  - Collecting page data...
            info  - Generating static pages (12/12)
            info  - Finalizing page optimization...

            Route (app)                              Size     First Load JS
            + / (static)                             142 B    87.2 kB
            + /products/[slug] (dynamic)             1.45 kB  91.3 kB
            + /login (static)                        890 B    88.9 kB

            === TYPE CHECK ===
            No issues found

            === LINT ===
            No ESLint warnings or errors
        """),
    },
]


# ─── Runner ───────────────────────────────────────────────────────────────────

def run_gate_scenarios(tmp_dir: Path) -> tuple[int, int]:
    passed = failed = 0

    print(f"\n{SEP}")
    print("GATE SCENARIOS — simulating agent diffs")
    print(SEP)

    for scenario in DIFFS:
        diff = scenario["diff"]
        expected = scenario["expect"]
        sid = scenario["id"]
        desc = scenario["description"]

        print(f"\n[{sid}]")
        print(f"  Task:   {desc}")
        print(f"  Expect: {expected}")

        try:
            run_all_gates(diff)
            outcome = "PASS"
            gate_name = None
        except GateViolation as e:
            outcome = "GATE_FAIL"
            gate_name = str(e).split("[")[1].split("]")[0] if "[" in str(e) else "unknown"

        if outcome == expected:
            # For GATE_FAIL cases, check the right gate fired
            if expected == "GATE_FAIL":
                expected_gate = scenario.get("expect_gate", "")
                if expected_gate and expected_gate != gate_name:
                    print(f"  Result: PASS (but wrong gate: expected {expected_gate}, got {gate_name})")
                    failed += 1
                else:
                    print(f"  Result: PASS  [gate fired: {gate_name}]")
                    passed += 1
            else:
                print(f"  Result: PASS")
                passed += 1
        else:
            print(f"  Result: FAIL  (got {outcome}, expected {expected})")
            if gate_name:
                print(f"          gate: {gate_name}")
            failed += 1

    return passed, failed


def run_sha_scenarios(tmp_dir: Path) -> tuple[int, int]:
    passed = failed = 0

    print(f"\n{SEP}")
    print("SHA GATE SCENARIOS — simulating verifier output")
    print(SEP)

    for scenario in SHA_SCENARIOS:
        sid = scenario["id"]
        desc = scenario["description"]
        expected = scenario["expect"]
        content = scenario["content"]

        output_path = tmp_dir / "test_output.txt"
        log_path = tmp_dir / "run_log.json"
        log_path.unlink(missing_ok=True)

        print(f"\n[{sid}]")
        print(f"  Scenario: {desc}")
        print(f"  Expect:   {expected}")

        if content == "":
            output_path.unlink(missing_ok=True)
        else:
            output_path.write_text(content, encoding="utf-8")

        try:
            sha = gate_test_output(str(output_path), str(log_path))
            outcome = "PASS"
            sha_preview = sha[:16] + "..."
        except GateViolation as e:
            outcome = "FAIL"
            sha_preview = None
            fail_reason = str(e).split("\n")[0]

        if outcome == expected:
            extra = f"sha: {sha_preview}" if sha_preview else f"blocked: {fail_reason}"
            print(f"  Result:   PASS  [{extra}]")
            passed += 1
        else:
            print(f"  Result:   FAIL  (got {outcome}, expected {expected})")
            if outcome == "PASS":
                print(f"            gate should have caught this but didn't")
            else:
                print(f"            {fail_reason}")
            failed += 1

    return passed, failed


def run_conductor_simulation(tmp_dir: Path):
    """
    Simulate a full pipeline run without an LLM:
    inject a bad diff, watch gates reject it, then inject a fixed diff and pass.
    """
    print(f"\n{SEP}")
    print("CONDUCTOR SIMULATION — full pipeline with retry")
    print(SEP)

    log_path = tmp_dir / "run_log.json"

    # Round 1: bad diff → gate rejects
    bad_diff = DIFFS[1]["diff"]  # redirect in page component
    print("\n[ROUND 1] Implementer agent produces bad diff (redirect outside middleware)")
    try:
        run_all_gates(bad_diff)
        print("  Gate: no violation caught  [BUG]")
    except GateViolation as e:
        gate_name = str(e).split("[")[1].split("]")[0]
        print(f"  Gate: REJECTED [{gate_name}]")
        print(f"  Conductor logs failure to mistakes.md")
        mistakes_path = tmp_dir / "mistakes.md"
        with open(mistakes_path, "a", encoding="utf-8") as f:
            f.write(f"\n## [IMPLEMENT] {gate_name}\n{e}\n")
        print(f"  Conductor retries (1/3)...")

    # Round 2: fixed diff → passes
    fixed_diff = DIFFS[0]["diff"]  # clean feature diff
    print("\n[ROUND 2] Implementer corrects the violation")
    try:
        run_all_gates(fixed_diff)
        print("  Gate: PASS — advancing to VERIFY phase")
    except GateViolation as e:
        print(f"  Gate: REJECTED again [{e}]")
        return

    # Verifier phase: good output
    print("\n[VERIFY phase] Verifier writes real test output")
    test_output = SHA_SCENARIOS[5]["content"]  # full realistic output
    output_path = tmp_dir / "test_output.txt"
    output_path.write_text(test_output, encoding="utf-8")
    try:
        sha = gate_test_output(str(output_path), str(log_path))
        print(f"  SHA gate: PASS — hash {sha[:16]}...")
    except GateViolation as e:
        print(f"  SHA gate: FAIL [{e}]")
        return

    # Review phase: no hard fails in clean diff
    print("\n[REVIEW phase] Reviewer checks clean diff")
    print("  Shadow gate check: scanning diff for missed violations...")
    try:
        run_all_gates(fixed_diff)
        print("  Shadow gate: clean")
    except GateViolation as e:
        print(f"  Shadow gate: caught missed violation [{e}]")
        return
    print("  Review result: PASS")

    # Retro: show mistakes log
    print("\n[RETRO phase] Retro agent reads mistakes.md")
    mistakes_path = tmp_dir / "mistakes.md"
    if mistakes_path.exists():
        content = mistakes_path.read_text(encoding="utf-8")
        violations = [l for l in content.splitlines() if l.startswith("##")]
        print(f"  Found {len(violations)} logged violation(s)")
        for v in violations:
            print(f"    {v}")
        print("  Retro: would propose checking skill entry 'redirect() location'")
        print("         (seen 1x — below threshold for new entry, weight: high already exists)")

    # Final log check
    print("\n[AUDIT LOG]")
    if log_path.exists():
        log = json.loads(log_path.read_text(encoding="utf-8"))
        for entry in log:
            ts = entry["timestamp"][:19]
            h = entry["test_output_hash"][:16]
            print(f"  {ts}  sha:{h}...  status:{entry['status']}")

    print(f"\n[CONDUCTOR] Pipeline complete")
    print(f"  IMPLEMENT: PASS (after 1 retry)")
    print(f"  VERIFY:    PASS")
    print(f"  REVIEW:    PASS")
    print(f"  RETRO:     done")


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(SEP)
    print("SYNTHETIC PROJECT — END-TO-END HARNESS TEST")
    print(SEP)

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp_dir = Path(tmp_str)

        print(f"\nSynthetic project scaffold:")
        project_dir = tmp_dir / "synthetic-project"
        create_synthetic_project(project_dir)
        for rel in PROJECT_FILES:
            print(f"  {rel}")

        g_passed, g_failed = run_gate_scenarios(tmp_dir)
        s_passed, s_failed = run_sha_scenarios(tmp_dir)
        run_conductor_simulation(tmp_dir)

    total_passed = g_passed + s_passed
    total_failed = g_failed + s_failed
    total = total_passed + total_failed

    print(f"\n{SEP}")
    print(f"OVERALL: {total_passed}/{total} scenarios passed", end="")
    if total_failed:
        print(f"  ({total_failed} FAILED)")
    else:
        print("  — all clear")
    print(f"  Gates:    {g_passed}/{g_passed+g_failed}")
    print(f"  SHA gate: {s_passed}/{s_passed+s_failed}")
    print(SEP)

    sys.exit(0 if total_failed == 0 else 1)
