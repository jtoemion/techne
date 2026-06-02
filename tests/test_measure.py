"""
test_measure.py — tests for actual behavioral measurements.

Verifies that scope_creep and diff_focused are measured from real diff
content, not hardcoded. Also tests intent scoring and gate_intent.

Run from tests/:
    python test_measure.py
"""

import sys
import textwrap
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

from measure import (
    extract_changed_files,
    count_added_lines,
    extract_task_keywords,
    measure_diff_focus,
    measure_scope_creep,
    measure_intent,
    gate_intent,
    run_measurements,
)
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


# ─── Diff parsing ────────────────────────────────────────────────────────────

def test_extract_changed_files():
    print("\n[extract_changed_files]")

    diff = textwrap.dedent("""\
        diff --git a/app/products/page.tsx b/app/products/page.tsx
        --- a/app/products/page.tsx
        +++ b/app/products/page.tsx
        @@ -1,3 +1,4 @@
        +import { Badge } from '@/components/ui/Badge'
        diff --git a/middleware.ts b/middleware.ts
        --- a/middleware.ts
        +++ b/middleware.ts
        @@ -1,2 +1,3 @@
        +// updated
    """)

    files = extract_changed_files(diff)
    if files == ["app/products/page.tsx", "middleware.ts"]:
        ok("extracts 2 correct files from diff headers")
    else:
        fail("extracts files", str(files))

    empty_files = extract_changed_files("")
    if empty_files == []:
        ok("empty diff returns empty list")
    else:
        fail("empty diff", str(empty_files))

    dedup = extract_changed_files(
        "+++ b/app/page.tsx\n+++ b/app/page.tsx\n+++ b/lib/util.ts\n"
    )
    if len(dedup) == 2:
        ok("deduplicates repeated file headers")
    else:
        fail("deduplicates", str(dedup))


def test_count_added_lines():
    print("\n[count_added_lines]")

    diff = "+++ b/file.ts\n+const x = 1\n+const y = 2\n context\n-removed\n"
    if count_added_lines(diff) == 2:
        ok("counts 2 added lines (excludes +++ header)")
    else:
        fail("count added", str(count_added_lines(diff)))


# ─── Keyword extraction ──────────────────────────────────────────────────────

def test_extract_keywords():
    print("\n[extract_task_keywords]")

    kws = extract_task_keywords("add sale badge to product page")
    if "badge" in kws and "product" in kws and "sale" in kws:
        ok("extracts meaningful keywords from task")
    else:
        fail("keyword extraction", str(kws))

    # Stopwords filtered
    kws2 = extract_task_keywords("fix the bug in the login page")
    if "fix" not in kws2 and "the" not in kws2:
        ok("filters stopwords (fix, the)")
    else:
        fail("stopwords filtered", str(kws2))

    # Paths preserved
    kws3 = extract_task_keywords("update app/products/[slug]/page.tsx component")
    if "app/products/[slug]/page.tsx" in kws3:
        ok("preserves path-like tokens")
    else:
        fail("path tokens", str(kws3))


# ─── measure_diff_focus ──────────────────────────────────────────────────────

def test_measure_diff_focus():
    print("\n[measure_diff_focus]")

    # Focused: small diff for short task
    small_diff = "+++ b/app/products/page.tsx\n" + "+line\n" * 10
    focused, reason = measure_diff_focus(small_diff, "add sale badge to product")
    if focused:
        ok(f"small diff for short task → focused ({reason})")
    else:
        fail("small diff should be focused", reason)

    # Unfocused: huge diff for 5-word task
    huge_diff = "+++ b/app/page.tsx\n" + "+line\n" * 250
    focused2, reason2 = measure_diff_focus(huge_diff, "fix button color")
    if not focused2:
        ok(f"250 lines for 3-word task → unfocused ({reason2})")
    else:
        fail("huge diff should be unfocused", reason2)

    # 9 files → unfocused
    many_files = "\n".join(f"+++ b/file{i}.ts\n+line" for i in range(9))
    focused3, reason3 = measure_diff_focus(many_files, "small fix")
    if not focused3:
        ok(f"9 files touched → unfocused ({reason3})")
    else:
        fail("9 files should be unfocused", reason3)

    # Empty diff
    _, reason_empty = measure_diff_focus("", "any task")
    if "empty" in reason_empty.lower():
        ok("empty diff flagged as unfocused")
    else:
        fail("empty diff reason", reason_empty)


# ─── measure_scope_creep ─────────────────────────────────────────────────────

def test_measure_scope_creep():
    print("\n[measure_scope_creep]")

    # No creep: badge task touches products page
    task = "add sale badge to product page"
    diff = "+++ b/app/products/page.tsx\n+const badge = 'sale'\n"
    crept, reason = measure_scope_creep(task, diff)
    if not crept:
        ok(f"on-topic diff → no scope creep ({reason})")
    else:
        fail("on-topic diff should not creep", reason)

    # Scope creep: badge task touches unrelated auth files
    diff_unrelated = (
        "+++ b/auth/login.tsx\n+const x = 1\n"
        "+++ b/api/payments.ts\n+const y = 2\n"
        "+++ b/middleware.ts\n+const z = 3\n"
    )
    crept2, reason2 = measure_scope_creep(task, diff_unrelated)
    if crept2:
        ok(f"unrelated files → scope creep detected ({reason2})")
    else:
        fail("unrelated files should trigger scope creep", reason2)

    # Empty diff → no creep
    crept3, reason3 = measure_scope_creep("any task", "")
    if not crept3:
        ok(f"empty diff → no creep ({reason3})")
    else:
        fail("empty diff scope creep", reason3)


# ─── measure_intent ──────────────────────────────────────────────────────────

def test_measure_intent():
    print("\n[measure_intent]")

    # Strong match: task keywords appear in diff
    task = "add WhatsApp button to product page"
    diff = textwrap.dedent("""\
        +++ b/components/product/WhatsAppButton.tsx
        +export function WhatsAppButton() {
        +  return <button>WhatsApp</button>
        +}
    """)
    result = measure_intent(task, diff)
    if result["score"] >= 0.5:
        ok(f"strong match scores {result['score']}: {result['warning']}")
    else:
        fail(f"strong match score", f"{result['score']}: {result['warning']}")

    # No match: task about badge, diff about auth
    task2 = "add sale badge to product listing"
    diff2 = "+++ b/auth/login.tsx\n+const jwt = require('jsonwebtoken')\n"
    result2 = measure_intent(task2, diff2)
    if result2["score"] < 0.5:
        ok(f"mismatch scores {result2['score']}: {result2['warning']}")
    else:
        fail("mismatch should score low", f"{result2['score']}")

    if result2["missing"]:
        ok(f"missing keywords identified: {result2['missing'][:3]}")
    else:
        fail("missing keywords should be populated")


# ─── gate_intent ─────────────────────────────────────────────────────────────

def test_gate_intent():
    print("\n[gate_intent]")

    # Strong match → passes
    task = "update middleware to redirect unauthenticated users"
    good_diff = textwrap.dedent("""\
        +++ b/middleware.ts
        +  if (!token) redirect('/login')
    """)
    try:
        gate_intent(task, good_diff, threshold=0.25)
        ok("on-target diff passes intent gate")
    except GateViolation as e:
        fail("on-target diff should pass gate", str(e))

    # Clear mismatch → fails at strict threshold
    task2 = "add sale badge to product listing page"
    bad_diff = "+++ b/auth/oauth.ts\n+const provider = 'google'\n"
    try:
        gate_intent(task2, bad_diff, threshold=0.6)
        fail("off-target diff should fail strict intent gate")
    except GateViolation:
        ok("off-target diff fails strict intent gate (threshold=0.6)")

    # Empty diff → fails
    try:
        gate_intent("anything", "", threshold=0.25)
        fail("empty diff should fail intent gate")
    except GateViolation:
        ok("empty diff fails intent gate")


# ─── run_measurements (integration) ─────────────────────────────────────────

def test_run_measurements():
    print("\n[run_measurements — integration]")

    task = "add WhatsApp button to product page"
    diff = textwrap.dedent("""\
        +++ b/components/product/WhatsAppButton.tsx
        +export function WhatsAppButton() { return <a href='https://wa.me/'>WhatsApp</a> }
        +++ b/app/products/[slug]/page.tsx
        +import { WhatsAppButton } from '@/components/product/WhatsAppButton'
        +  <WhatsAppButton />
    """)

    m = run_measurements(task, diff)

    required_keys = ["diff_focused", "scope_creep", "_focus_reason", "_creep_reason", "_intent"]
    for key in required_keys:
        if key in m:
            ok(f"run_measurements returns '{key}'")
        else:
            fail(f"run_measurements returns '{key}'")

    if isinstance(m["diff_focused"], bool):
        ok(f"diff_focused is bool: {m['diff_focused']}")
    else:
        fail("diff_focused should be bool", str(type(m["diff_focused"])))

    if isinstance(m["scope_creep"], bool):
        ok(f"scope_creep is bool: {m['scope_creep']}")
    else:
        fail("scope_creep should be bool", str(type(m["scope_creep"])))

    intent = m["_intent"]
    if 0.0 <= intent["score"] <= 1.0:
        ok(f"intent score in range: {intent['score']}")
    else:
        fail("intent score range", str(intent["score"]))


# ─── Key property: not hardcoded ─────────────────────────────────────────────

def test_not_hardcoded():
    """Megumi's point: these must be measurements, not assumptions."""
    print("\n[measurements are not hardcoded — differ for different inputs]")

    task = "add badge to product page"
    focused_diff = "+++ b/app/products/page.tsx\n" + "+code\n" * 5
    huge_diff    = "+++ b/app/products/page.tsx\n" + "+code\n" * 300

    m_focused = run_measurements(task, focused_diff)
    m_huge    = run_measurements(task, huge_diff)

    if m_focused["diff_focused"] != m_huge["diff_focused"]:
        ok("diff_focused actually differs for focused vs huge diff")
    else:
        fail("diff_focused should differ (not hardcoded)",
             f"both={m_focused['diff_focused']}")

    on_topic  = "+++ b/app/products/page.tsx\n+code\n"
    off_topic = "+++ b/auth/login.tsx\n+code\n"

    m_on  = run_measurements(task, on_topic)
    m_off = run_measurements(task, off_topic)

    if m_on["scope_creep"] != m_off["scope_creep"]:
        ok("scope_creep actually differs for on-topic vs off-topic diff")
    else:
        fail("scope_creep should differ (not hardcoded)",
             f"on={m_on['scope_creep']} off={m_off['scope_creep']}")


# ─── Run all ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 64)
    print("MEASURE.PY — STRESS TEST")
    print("=" * 64)

    test_extract_changed_files()
    test_count_added_lines()
    test_extract_keywords()
    test_measure_diff_focus()
    test_measure_scope_creep()
    test_measure_intent()
    test_gate_intent()
    test_run_measurements()
    test_not_hardcoded()

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
