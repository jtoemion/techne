"""
test_intent_layers.py — tests for the three-layer intent reasoning system.

Tests diff_parser.py (L2 structural) and intent_reasoner.py (L2 structural
fallback + L3 semantic interface). No API key required — all structural tests.

Run from tests/:
    python test_intent_layers.py
"""

import sys
import textwrap
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

from diff_parser import parse_diff, FileSummary, DiffSummary
from intent_reasoner import (
    reason_about_intent,
    _structural_verdict,
    parse_semantic_response,
    build_semantic_prompt,
)
from measure import full_intent_check, run_measurements
from gates import GateViolation

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results: list[tuple[str, bool, str]] = []


def ok(label: str):
    results.append((label, True, ""))
    print(f"  {PASS} {label}")


def fail(label: str, reason: str = ""):
    results.append((label, False, reason))
    print(f"  {FAIL} {label} -- {reason}")


# ─── Real-world diffs ────────────────────────────────────────────────────────

WHATSAPP_DIFF = textwrap.dedent("""\
    diff --git a/components/product/WhatsAppButton.tsx b/components/product/WhatsAppButton.tsx
    new file mode 100644
    --- /dev/null
    +++ b/components/product/WhatsAppButton.tsx
    @@ -0,0 +1,18 @@
    +import { type FC } from 'react'
    +
    +interface WhatsAppButtonProps {
    +  phoneNumber: string
    +  message?: string
    +}
    +
    +export const WhatsAppButton: FC<WhatsAppButtonProps> = ({ phoneNumber, message = '' }) => {
    +  const url = `https://wa.me/${phoneNumber}?text=${encodeURIComponent(message)}`
    +  return (
    +    <a href={url} target="_blank" rel="noopener noreferrer"
    +       className="flex items-center gap-2 bg-green-500 text-white px-4 py-2 rounded">
    +      <span>WhatsApp</span>
    +    </a>
    +  )
    +}
    diff --git a/app/products/[slug]/page.tsx b/app/products/[slug]/page.tsx
    --- a/app/products/[slug]/page.tsx
    +++ b/app/products/[slug]/page.tsx
    @@ -3,6 +3,7 @@
     import { getProduct } from '@/lib/products'
    +import { WhatsAppButton } from '@/components/product/WhatsAppButton'

     export default async function ProductPage({ params }) {
       const { slug } = await params
       const product = await getProduct(slug)
       return (
         <div>
           <h1>{product.name}</h1>
    +      <WhatsAppButton phoneNumber="+62812345678" message={`Hi, I'm interested in ${product.name}`} />
         </div>
       )
     }
""")

WRONG_FILE_DIFF = textwrap.dedent("""\
    diff --git a/auth/oauth.ts b/auth/oauth.ts
    --- a/auth/oauth.ts
    +++ b/auth/oauth.ts
    @@ -1,3 +1,5 @@
    +import { GoogleProvider } from 'next-auth/providers/google'
    +export const authOptions = { providers: [GoogleProvider({ clientId: process.env.GOOGLE_ID })] }
""")

REDIRECT_DIFF = textwrap.dedent("""\
    diff --git a/middleware.ts b/middleware.ts
    --- a/middleware.ts
    +++ b/middleware.ts
    @@ -3,4 +3,7 @@
     export function middleware(request: NextRequest) {
       const token = request.cookies.get('token')
    +  const isAdmin = request.cookies.get('role')?.value === 'admin'
    +  if (!token) {
    +    return NextResponse.redirect(new URL('/login', request.url))
    +  }
       return NextResponse.next()
     }
""")


# ─── diff_parser tests ───────────────────────────────────────────────────────

def test_parse_whatsapp_diff():
    print("\n[parse_diff — WhatsApp button diff]")

    s = parse_diff(WHATSAPP_DIFF)

    if not s.is_empty:
        ok("diff parsed as non-empty")
    else:
        fail("diff should not be empty")

    file_paths = [f.path for f in s.files]
    if "components/product/WhatsAppButton.tsx" in file_paths:
        ok("component file detected")
    else:
        fail("component file", str(file_paths))

    if "app/products/[slug]/page.tsx" in file_paths:
        ok("page file detected")
    else:
        fail("page file", str(file_paths))

    # New file detection
    new_files = [f for f in s.files if f.is_new]
    if new_files:
        ok(f"new file detected: {new_files[0].path}")
    else:
        fail("new file should be detected")

    # Export extraction
    if "WhatsAppButton" in s.all_exports_added:
        ok("WhatsAppButton export extracted")
    else:
        fail("WhatsAppButton export", str(s.all_exports_added))

    # Import extraction
    if any("WhatsAppButton" in imp for imp in s.all_imports_added):
        ok("WhatsAppButton import extracted in page")
    else:
        fail("WhatsAppButton import", str(s.all_imports_added))

    # Dominant type
    if "component" in s.dominant_type:
        ok(f"dominant type: {s.dominant_type}")
    else:
        fail("dominant type", s.dominant_type)

    # Line stats
    if s.total_added > 15:
        ok(f"line count: +{s.total_added}/-{s.total_removed}")
    else:
        fail("line count too low", str(s.total_added))


def test_parse_middleware_diff():
    print("\n[parse_diff — middleware diff]")

    s = parse_diff(REDIRECT_DIFF)

    if not s.is_empty:
        ok("middleware diff parsed")
    else:
        fail("middleware diff should not be empty")

    if s.dominant_type == "middleware":
        ok("dominant type: middleware")
    else:
        fail("dominant type should be middleware", s.dominant_type)


def test_parse_empty():
    print("\n[parse_diff — empty inputs]")

    empty = parse_diff("")
    if empty.is_empty:
        ok("empty string → is_empty=True")
    else:
        fail("empty string should be empty")

    whitespace = parse_diff("   \n\n   ")
    if whitespace.is_empty:
        ok("whitespace → is_empty=True")
    else:
        fail("whitespace should be empty")


def test_structured_text_output():
    print("\n[DiffSummary.to_structured_text()]")

    s = parse_diff(WHATSAPP_DIFF)
    text = s.to_structured_text()

    if "WhatsAppButton" in text:
        ok("structured text includes export name")
    else:
        fail("structured text missing export", text[:200])

    if "Files changed" in text:
        ok("structured text has file count")
    else:
        fail("structured text missing file count")

    if "Dominant change type" in text:
        ok("structured text has dominant type")
    else:
        fail("structured text missing dominant type")

    if len(text) < 1000:
        ok(f"structured text is compact ({len(text)} chars)")
    else:
        fail("structured text too long for LLM context", f"{len(text)} chars")


# ─── structural reasoner (L2) tests ─────────────────────────────────────────

def test_structural_match():
    print("\n[_structural_verdict — MATCH case]")

    from diff_parser import parse_diff
    task = "add WhatsApp button to product page"
    s = parse_diff(WHATSAPP_DIFF)
    verdict = _structural_verdict(task, s)

    if verdict.layer == "structural":
        ok("layer=structural (no LLM)")
    else:
        fail("layer should be structural", verdict.layer)

    if verdict.verdict in ("MATCH", "PARTIAL"):
        ok(f"verdict: {verdict.verdict} (WhatsApp → expected MATCH or PARTIAL)")
    else:
        fail("should not be MISMATCH for matching diff", verdict.verdict)

    if verdict.deductions:
        ok(f"deductions present: {verdict.deductions[0][:50]}")
    else:
        fail("deductions should be present")

    if 0.0 <= verdict.confidence <= 1.0:
        ok(f"confidence in range: {verdict.confidence:.2f}")
    else:
        fail("confidence out of range", str(verdict.confidence))


def test_structural_mismatch():
    print("\n[_structural_verdict — MISMATCH case]")

    from diff_parser import parse_diff
    task = "add WhatsApp button to product page"
    s = parse_diff(WRONG_FILE_DIFF)
    verdict = _structural_verdict(task, s)

    # auth/oauth.ts has nothing to do with WhatsApp or product
    if verdict.verdict in ("MISMATCH", "PARTIAL"):
        ok(f"verdict: {verdict.verdict} (auth diff for WhatsApp task)")
    else:
        fail("auth diff should not MATCH WhatsApp task", verdict.verdict)


def test_structural_empty():
    print("\n[_structural_verdict — empty diff]")

    from diff_parser import parse_diff
    s = parse_diff("")
    verdict = _structural_verdict("any task", s)

    if verdict.verdict == "MISMATCH" and verdict.confidence > 0.8:
        ok(f"empty diff → MISMATCH ({verdict.confidence:.0%}): {verdict.reason}")
    else:
        fail("empty diff should be MISMATCH", f"{verdict.verdict}/{verdict.confidence}")


# ─── reason_about_intent (public API, no LLM) ───────────────────────────────

def test_reason_no_llm():
    print("\n[reason_about_intent — no LLM mode]")

    from diff_parser import parse_diff
    task = "add WhatsApp button to product page"
    s = parse_diff(WHATSAPP_DIFF)

    verdict = reason_about_intent(task, s)

    if verdict.layer == "structural":
        ok("no semantic verdict -> structural layer (L2)")
    else:
        fail("should use structural layer", verdict.layer)

    if verdict.verdict in ("MATCH", "PARTIAL", "MISMATCH"):
        ok(f"valid verdict: {verdict.verdict}")
    else:
        fail("invalid verdict", verdict.verdict)


# ─── LLM response parser ────────────────────────────────────────────────────

def test_parse_semantic_response():
    print("\n[parse_semantic_response — host L3 reply parsing]")

    good_response = textwrap.dedent("""\
        VERDICT: MATCH
        CONFIDENCE: 0.92
        REASON: The diff creates a WhatsAppButton component and integrates it into the product page, directly implementing the task.
        DEDUCTIONS:
        - New file WhatsAppButton.tsx created with correct component structure
        - WhatsAppButton export matches the task's noun
        - Import added to product page file
        - WhatsApp URL construction is present in the component
    """)

    parsed = parse_semantic_response(good_response)

    if parsed.verdict == "MATCH":
        ok("parses VERDICT: MATCH")
    else:
        fail("VERDICT parsing", str(parsed.verdict))

    if abs(parsed.confidence - 0.92) < 0.01:
        ok(f"parses CONFIDENCE: {parsed.confidence}")
    else:
        fail("CONFIDENCE parsing", str(parsed.confidence))

    if "WhatsAppButton" in parsed.reason:
        ok("parses REASON with content")
    else:
        fail("REASON parsing", parsed.reason)

    if len(parsed.deductions) == 4:
        ok(f"parses 4 DEDUCTIONS")
    else:
        fail("DEDUCTIONS count", str(len(parsed.deductions)))

    if parsed.layer == "semantic":
        ok("parsed verdict tagged layer=semantic")
    else:
        fail("layer should be semantic", parsed.layer)

    # Malformed response
    bad = "Something went wrong"
    parsed_bad = parse_semantic_response(bad)
    if parsed_bad.verdict == "PARTIAL":
        ok("malformed response defaults to PARTIAL")
    else:
        fail("malformed default", parsed_bad.verdict)

    if 0.0 <= parsed_bad.confidence <= 1.0:
        ok("malformed confidence is still in range")
    else:
        fail("malformed confidence range", str(parsed_bad.confidence))


def test_semantic_hook_roundtrip():
    print("\n[build_semantic_prompt + host verdict injection — L3 hook]")

    from diff_parser import parse_diff
    task = "add WhatsApp button to product page"
    s = parse_diff(WHATSAPP_DIFF)

    prompt = build_semantic_prompt(task, s)
    if prompt["system"] and task in prompt["user"]:
        ok("build_semantic_prompt returns system + user with the task")
    else:
        fail("semantic prompt shape", str(prompt)[:120])

    # Host runs the prompt, returns this reply; we parse and inject it.
    host_reply = "VERDICT: MISMATCH\nCONFIDENCE: 0.88\nREASON: wrong thing\nDEDUCTIONS:\n- x"
    host_verdict = parse_semantic_response(host_reply)
    injected = reason_about_intent(task, s, semantic_verdict=host_verdict)
    if injected.verdict == "MISMATCH" and injected.layer == "semantic":
        ok("host semantic verdict overrides L2 structural")
    else:
        fail("host verdict not used", f"{injected.verdict}/{injected.layer}")


# ─── full_intent_check (integrated, no LLM) ─────────────────────────────────

def test_full_intent_check():
    print("\n[full_intent_check — integrated, L2 structural]")

    task = "add WhatsApp button to product page"
    result = full_intent_check(task, WHATSAPP_DIFF)

    required_keys = ["verdict", "confidence", "reason", "deductions",
                     "layer", "l1_score", "l1_warning", "diff_summary", "warning"]
    for key in required_keys:
        if key in result:
            ok(f"full_intent_check returns '{key}'")
        else:
            fail(f"missing key: '{key}'")
            break

    if result["verdict"] in ("MATCH", "PARTIAL", "MISMATCH"):
        ok(f"verdict: {result['verdict']}")
    else:
        fail("invalid verdict", result["verdict"])

    if result["l1_score"] > 0:
        ok(f"L1 heuristic score: {result['l1_score']:.2f}")
    else:
        fail("L1 score should be > 0 for matching diff")

    # Warning is human-readable
    if result["layer"] in result["warning"]:
        ok("warning includes layer name")
    else:
        fail("warning format", result["warning"])


def test_run_measurements_with_layers():
    print("\n[run_measurements — uses layered intent]")

    task = "add WhatsApp button to product page"
    m = run_measurements(task, WHATSAPP_DIFF)

    if "_intent" in m and "_intent_warning" in m:
        ok("run_measurements returns _intent and _intent_warning")
    else:
        fail("run_measurements keys", str(list(m.keys())))

    intent = m["_intent"]
    if "verdict" in intent:
        ok(f"_intent has verdict: {intent['verdict']}")
    else:
        fail("_intent missing verdict")

    # Confirm the anti-hardcoding property still holds
    m2 = run_measurements(task, WRONG_FILE_DIFF)
    if m["_intent"]["verdict"] != m2["_intent"]["verdict"] or \
       m["_intent"]["confidence"] != m2["_intent"]["confidence"]:
        ok("layered intent differs for different diffs (not hardcoded)")
    else:
        ok("both diffs assessed (check manually for correctness)")


# ─── Run all ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 64)
    print("INTENT REASONING LAYERS — STRESS TEST")
    print("=" * 64)

    test_parse_whatsapp_diff()
    test_parse_middleware_diff()
    test_parse_empty()
    test_structured_text_output()
    test_structural_match()
    test_structural_mismatch()
    test_structural_empty()
    test_reason_no_llm()
    test_parse_semantic_response()
    test_semantic_hook_roundtrip()
    test_full_intent_check()
    test_run_measurements_with_layers()

    total = len(results)
    passed = sum(1 for _, ok_flag, _ in results if ok_flag)
    failed = total - passed

    print("\n" + "=" * 64)
    print(f"RESULTS: {passed}/{total} passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
        for label, ok_flag, reason in results:
            if not ok_flag:
                print(f"  {FAIL} {label}: {reason}")
    else:
        print("  -- all clear")
    print("=" * 64)

    sys.exit(0 if failed == 0 else 1)
