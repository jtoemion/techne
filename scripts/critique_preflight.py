#!/usr/bin/env python3
"""critique_preflight.py — Fetch and package inputs for the CRITIQUE phase.

Reads the implementer's diff + changed files + context-guard report from
tasks.db, runs deterministic anti-pattern checks, and outputs a structured
Critique Input Package for the CRITIQUE agent to analyze.

Usage:
    python3 scripts/critique_preflight.py                    # latest IMPLEMENTED task
    python3 scripts/critique_preflight.py --task <task_id>   # specific task
    python3 scripts/critique_preflight.py --task <id> --verbose  # with file contents
"""

from __future__ import annotations
import argparse, json, os, re, sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DEFAULT_DB = ROOT / ".techne" / "memory" / "tasks.db"

# Anti-pattern patterns
ANTI_PATTERNS: list[tuple[str, str, str]] = [
    ("TODO_LEFT", r"\bTODO\b", "TODO/FIXME/HACK comment left in code"),
    ("FIXME_LEFT", r"\bFIXME\b", "FIXME marker left in delivered code"),
    ("HACK_LEFT", r"\bHACK\b", "HACK marker — likely unfinished workaround"),
    ("DEBUG_LOG", r"console\.(log|debug)\(", "console.log/debug in production code"),
    ("DEBUGGER", r"\bdebugger\b", "debugger statement left in code"),
    ("EMPTY_CATCH", r"except\s+\w+\s*:\s*\n\s*(pass|#|$)", "Empty except block — error swallowing"),
    ("ANY_CAST", r"as\s+any\b", "TypeScript `as any` cast — type safety bypass"),
    ("NON_NULL_ASSERT", r"!\s*[.);\]]", "Non-null assertion (!) in TypeScript"),
    ("HARDCODED_SECRET", r"(password|secret|api_key|token)\s*=\s*['\"][^'\"]+['\"]",
     "Possible hardcoded credential"),
    ("SHELL_INJECTION", r"os\.(system|popen)\(", "Shell call — potential injection risk"),
    ("RAW_SQL", r"execute\(['\"]\s*(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER)",
     "Raw SQL — consider ORM/parameterised"),
    ("EVAL", r"\beval\s*\(", "eval() call — security risk"),
    ("OVERLY_BROAD_EXCEPT", r"except\s+Exception\s*:", "Overly broad exception handler"),
]

PROD_CODE_EXTS = {".ts", ".tsx", ".js", ".jsx", ".svelte", ".py", ".go", ".rs"}


def load_db(db_path: str | Path | None = None):
    """Load TaskDB — add harness to sys.path if needed."""
    db_path = Path(db_path) if db_path else DEFAULT_DB
    # Try adding harness/ to path
    harness_dir = ROOT / "harness"
    if harness_dir.exists() and str(harness_dir) not in sys.path:
        sys.path.insert(0, str(harness_dir))
    from task_db import TaskDB
    return TaskDB(str(db_path))


def fetch_critique_data(task_id: str | None, db_path: Path) -> dict | None:
    """Fetch task + implementer + context-guard events from tasks.db."""
    db = load_db(db_path)

    # Find the task
    if task_id:
        task = db.get_task(task_id)
    else:
        # Find latest IMPLEMENTED task
        tasks = db.get_all_tasks()
        implemented = [t for t in tasks if t.status == "IMPLEMENTED"]
        if not implemented:
            implemented = [t for t in tasks if t.status not in ("PENDING", "DONE")]
        if not implemented:
            db.close()
            return None
        implemented.sort(key=lambda t: t.updated_at or t.created_at, reverse=True)
        task = implemented[0]

    if not task:
        db.close()
        return None

    # Fetch events from the DB directly
    import sqlite3
    conn = sqlite3.connect(str(db.db_path))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """SELECT agent, action, summary, changed_files, diff_summary, findings,
                  verdict, timestamp
           FROM task_events
           WHERE task_id = ?
           ORDER BY timestamp""",
        (task.id,)
    ).fetchall()

    events = []
    implement_event = None
    context_event = None
    for row in rows:
        e = {
            "agent": row["agent"],
            "action": row["action"],
            "summary": row["summary"] or "",
            "changed_files": row["changed_files"] or "[]",
            "diff_summary": row["diff_summary"] or "",
            "findings": row["findings"] or "",
            "verdict": row["verdict"] or "",
            "timestamp": row["timestamp"] or "",
        }
        events.append(e)
        if row["action"] in ("complete", "implement") and not implement_event:
            implement_event = e
        if row["action"] in ("context-guard", "context_guard") and not context_event:
            context_event = e

    conn.close()
    db.close()

    # Parse changed_files
    changed_files = []
    if implement_event:
        try:
            changed_files = json.loads(implement_event["changed_files"])
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "task": task,
        "implement_event": implement_event,
        "context_event": context_event,
        "changed_files": changed_files,
        "events": events,
    }


def scan_yagni(changed_files: list[str], project_root: Path, task_title: str,
                task_desc: str) -> list[dict]:
    """Check YAGNI compliance — did the implementation add unnecessary code?"""
    findings = []

    # 1. Unused imports in source files
    for f in changed_files:
        full = project_root / f
        if not full.exists() or full.suffix not in (".py", ".ts", ".tsx", ".js", ".jsx", ".svelte"):
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
        except Exception:
            continue

        # Check for commented-out code blocks
        comment_count = sum(1 for l in lines if l.strip().startswith("#") or
                            l.strip().startswith("//") or
                            l.strip().startswith("/*") or
                            l.strip().startswith("*"))
        total = len(lines)
        if total > 10 and comment_count / total > 0.25:
            findings.append({
                "file": f, "code": "YAGNI_EXCESS_COMMENTS",
                "detail": f"{comment_count}/{total} lines are comments ({comment_count/total*100:.0f}%) — gold-plating documentation"
            })

        # Check for speculative type params / generics that look unused
        if full.suffix in (".ts", ".tsx"):
            for lineno, line in enumerate(lines, 1):
                if re.search(r"<[A-Z]\w*(,\s*[A-Z]\w*)*>", line) and "function" not in line and "class" not in line:
                    # Generic type parameter on a non-function/class line — possibly speculative
                    pass  # too noisy to flag every generic

        # Check for pass-only blocks (stub methods)
        if full.suffix == ".py":
            for lineno, line in enumerate(lines, 1):
                if re.search(r"^\s+def\s+\w+\s*\(.*\):\s*$", line):
                    # Check next line for 'pass' or '...'
                    if lineno < total and lines[lineno].strip() in ("pass", "..."):
                        findings.append({
                            "file": f, "line": lineno + 1,
                            "code": "YAGNI_STUB_METHOD",
                            "detail": f"Stub method at line {lineno+1} — unimplemented, not YAGNI"
                        })

    # 2. Net line count vs task scope
    if len(changed_files) > 5:
        findings.append({
            "file": changed_files[0], "code": "YAGNI_HIGH_FILE_COUNT",
            "detail": f"{len(changed_files)} files changed — verify each file is necessary for: {task_title[:80]}"
        })

    # 3. Test files absent from changes when source files changed
    source_files = [f for f in changed_files
                    if not any(t in f for t in [".test.", ".spec.", "_test.", "/test_", "/tests/"])]
    test_files = [f for f in changed_files
                  if any(t in f for t in [".test.", ".spec.", "_test.", "/test_", "/tests/"])]
    if source_files and not test_files:
        has_test_ref = re.search(r"(test|spec|tdd|verify)", task_title + task_desc, re.I)
        if not has_test_ref:
            findings.append({
                "file": source_files[0], "code": "YAGNI_NO_TESTS_IN_CHANGES",
                "detail": f"{len(source_files)} source files changed, 0 test files — if this is TDD, tests should be in the change set"
            })

    # 4. Check for repeated import aliasing (import foo as bar) — speculative renaming
    for f in changed_files:
        full = project_root / f
        if not full.exists():
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        as_imports = re.findall(r"import\s+\w+\s+as\s+\w+", text)
        if len(as_imports) > 3:
            findings.append({
                "file": f, "code": "YAGNI_EXCESS_ALIASING",
                "detail": f"{len(as_imports)} aliased imports — speculative abstraction?"
            })

    return findings


def scan_tdd(changed_files: list[str], project_root: Path, task_title: str,
             task_desc: str, diff_summary: str, discipline: str = "") -> list[dict]:
    """Check TDD compliance — were tests written? Do they validate the change?"""
    findings = []

    source_files = [f for f in changed_files
                    if not any(t in f for t in [".test.", ".spec.", "_test.", "/test_", "/tests/"])]
    test_files = [f for f in changed_files
                  if any(t in f for t in [".test.", ".spec.", "_test.", "/test_", "/tests/"])]

    # 1. Does task mention TDD / test?
    mentions_tdd = bool(re.search(r"(tdd|test.?driven|write test|add test|unit test|spec|verify)",
                                   task_title + task_desc, re.I))
    # Also check if discipline field explicitly says tdd
    has_tdd_discipline = discipline.lower() == "tdd"
    if has_tdd_discipline:
        mentions_tdd = True

    mentions_tdd_in_diff = bool(re.search(r"(test|spec|tdd|pass|fail|assert)",
                                           diff_summary, re.I))

    # Also check if task discipline is tdd (from DB)
    # (passed as empty string here since we don't have it in this scope)

    # 2. No test files at all
    if not test_files and mentions_tdd:
        findings.append({
            "file": "task", "code": "TDD_MISSING_TESTS",
            "detail": "Task mentions testing/TDD but no test files in the change set"
        })

    # 3. For each source file, is there a corresponding test file?
    if source_files:
        test_basenames = {Path(t).stem.replace(".test", "").replace(".spec", "")
                          for t in test_files}
        missing_test_pairs = []
        for sf in source_files:
            stem = Path(sf).stem
            # Remove common suffixes like .server, .page
            base = re.sub(r"\.(server|page|layout|store|util|helper|api)$", "", stem)
            if base not in test_basenames and stem not in test_basenames:
                # Check if a test file exists on disk
                expected_test_paths = [
                    project_root / sf.replace(f".{Path(sf).suffix}", f".test{Path(sf).suffix}"),
                    project_root / sf.replace(f".{Path(sf).suffix}", f".spec{Path(sf).suffix}"),
                    project_root / sf.replace("/", "/test_"),
                ]
                exists_on_disk = any(p.exists() for p in expected_test_paths)
                if exists_on_disk:
                    missing_test_pairs.append(sf)

        if missing_test_pairs and mentions_tdd:
            findings.append({
                "file": missing_test_pairs[0], "code": "TDD_TEST_FILE_EXISTS_BUT_NOT_IN_CHANGES",
                "detail": f"Test file exists on disk for {len(missing_test_pairs)} source files but wasn't included in the change — TDD requires the test to be part of the submission"
            })

    # 4. No test assertions mentioned in diff summary
    if not mentions_tdd_in_diff and mentions_tdd:
        findings.append({
            "file": "diff_summary", "code": "TDD_NO_TEST_REF_IN_DIFF",
            "detail": "Diff summary doesn't mention tests or assertions despite TDD task"
        })

    # 5. TDD order check — are test files listed before source files?
    # (convention: tests committed first)
    if test_files and source_files:
        first_test_idx = min(changed_files.index(t) for t in test_files if t in changed_files)
        first_source_idx = min(changed_files.index(s) for s in source_files if s in changed_files)
        if first_source_idx < first_test_idx:
            findings.append({
                "file": changed_files[first_test_idx], "code": "TDD_ORDER",
                "detail": "Source file committed before test file — TDD says test first"
            })

    # 6. Test count vs source count
    if test_files and source_files:
        ratio = len(test_files) / len(source_files)
        if ratio < 0.3 and len(source_files) > 2:
            findings.append({
                "file": "summary", "code": "TDD_LOW_TEST_RATIO",
                "detail": f"{len(test_files)} test files for {len(source_files)} source files ({ratio:.0%}) — low coverage ratio"
            })

    return findings


def scan_file_for_antipatterns(file_path: str, project_root: Path) -> list[dict]:
    """Scan a single changed file for deterministic anti-patterns."""
    full_path = project_root / file_path
    if not full_path.exists() or not full_path.is_file():
        return []

    is_test = any(t in file_path for t in
                  [".test.", ".spec.", "_test.", "/test_", "/tests/", "/__tests__/"])
    ext = full_path.suffix
    is_prod = ext in PROD_CODE_EXTS and not is_test

    try:
        lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return [{"file": file_path, "code": "FILE_UNREADABLE", "detail": "Could not read file"}]

    findings = []
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()

        for code, pattern, desc in ANTI_PATTERNS:
            if code == "DEBUG_LOG" and not is_prod:
                continue
            if code == "HARDCODED_SECRET" and is_test:
                continue

            if re.search(pattern, stripped):
                findings.append({
                    "file": file_path,
                    "line": lineno,
                    "code": code,
                    "detail": desc,
                    "snippet": stripped[:120],
                })
                break

    return findings


def scan_structural_risks(changed_files: list[str], project_root: Path) -> list[dict]:
    """Check file-level structural risks."""
    risks = []
    for f in changed_files:
        full_path = project_root / f
        if not full_path.exists():
            continue
        try:
            text = full_path.read_text(encoding="utf-8", errors="replace")
            lines = len(text.splitlines())
            if lines > 300:
                risks.append({
                    "file": f, "code": "LARGE_FILE",
                    "detail": f"{lines} lines — large change surface, risk of missed issues",
                })
            if text.strip() and not text.strip().endswith("\n"):
                risks.append({
                    "file": f, "code": "NO_TRAILING_NEWLINE",
                    "detail": "File does not end with a newline",
                })
        except Exception:
            pass
    return risks


def main():
    parser = argparse.ArgumentParser(
        description="Critique Preflight — package inputs for CRITIQUE agent"
    )
    parser.add_argument("--task", help="Task ID (default: latest IMPLEMENTED task)")
    parser.add_argument("--db", default=str(DEFAULT_DB),
                        help=f"Task DB path (default: {DEFAULT_DB})")
    parser.add_argument("--verbose", action="store_true",
                        help="Include file content snippets (EXPERIMENTAL)")
    parser.add_argument("--project", default=str(ROOT),
                        help="Project root for file scanning")
    args = parser.parse_args()

    db_path = Path(args.db)
    project_root = Path(args.project)

    if not db_path.exists():
        print(f"ERROR: Task DB not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    data = fetch_critique_data(args.task, db_path)
    if not data:
        print("ERROR: No task found. Specify --task <id> or complete an IMPLEMENT phase first.",
              file=sys.stderr)
        sys.exit(1)

    task = data["task"]
    implement = data["implement_event"]
    context = data["context_event"]
    changed_files = data["changed_files"]

    # === OUTPUT: Critique Input Package ===

    print("# CRITIQUE INPUT PACKAGE")
    print(f"## Task: {task.id[:12]} | {task.title}")
    print(f"## Status: {task.status} | Mode: {task.phase_mode}")
    print(f"## Attempt: #{task.attempt}/{task.max_attempts}")
    if task.description:
        print(f"## Description: {task.description[:200]}")
    print()

    # Implementer submission
    if implement:
        print("## IMPLEMENTER SUBMISSION")
        print(f"  Agent: {implement.get('agent', '?')}")
        print(f"  Summary: {implement.get('summary', '(none)')[:300]}")
        ds = implement.get("diff_summary", "")
        if ds:
            print(f"\n  Diff summary:\n{ds[:2000]}")
        print()
    else:
        print("## IMPLEMENTER SUBMISSION — none found\n")

    # Changed files
    if changed_files:
        print(f"## CHANGED FILES ({len(changed_files)})")
        for f in changed_files:
            full = project_root / f
            src_lines = -1
            if full.exists():
                try:
                    src_lines = len(full.read_text(encoding="utf-8",
                                                   errors="replace").splitlines())
                except Exception:
                    pass
            print(f"  {f}  ({src_lines} lines)" if src_lines >= 0 else f"  {f}")
        print()

    # Context-guard report
    if context:
        print(f"## CONTEXT-GUARD REPORT")
        print(f"  Summary: {context.get('summary', '(none)')[:500]}")
        findings = context.get("findings", "")
        if findings:
            print(f"  Findings: {findings[:1000]}")
        print()
    else:
        print("## CONTEXT-GUARD REPORT — none found (may not have run yet)\n")

    # YAGNI check
    if changed_files:
        print("## YAGNI COMPLIANCE CHECK")
        yagni_findings = scan_yagni(changed_files, project_root,
                                     task.title, task.description or "")
        if yagni_findings:
            for finding in yagni_findings:
                f = finding["file"]
                line = finding.get("line", "")
                code = finding["code"]
                detail = finding["detail"]
                loc = f":{line}" if line else ""
                print(f"  [{code}] {f}{loc} — {detail}")
            print(f"\n  Total: {len(yagni_findings)} YAGNI items")
        else:
            print("  Clean — nothing obviously speculative.")
        print()

    # TDD check
    if changed_files:
        print("## TDD COMPLIANCE CHECK")
        ds = implement.get("diff_summary", "") if implement else ""
        tdd_findings = scan_tdd(changed_files, project_root,
                                 task.title, task.description or "", ds,
                                 discipline=task.discipline or "tdd")
        if tdd_findings:
            for finding in tdd_findings:
                f = finding["file"]
                code = finding["code"]
                detail = finding["detail"]
                print(f"  [{code}] {f} — {detail}")
            print(f"\n  Total: {len(tdd_findings)} TDD items")
        else:
            print("  Clean — tests present and in order.")
        print()

    # Deterministic scan
    if changed_files:
        print("## DETERMINISTIC ANTI-PATTERN SCAN")
        all_findings = []
        for f in changed_files:
            all_findings.extend(scan_file_for_antipatterns(f, project_root))
            all_findings.extend(scan_structural_risks([f], project_root))

        if all_findings:
            # Group by code for summary
            by_code: dict[str, int] = {}
            for finding in all_findings:
                code = finding["code"]
                by_code[code] = by_code.get(code, 0) + 1
                f = finding["file"]
                line = finding.get("line", "?")
                detail = finding["detail"]
                snippet = finding.get("snippet", "")
                print(f"  [{code}] {f}:{line} — {detail}")
                if snippet:
                    print(f"    > {snippet}")

            print(f"\n  Total: {len(all_findings)} findings")
            print(f"  By type: {', '.join(f'{c}={n}' for c, n in sorted(by_code.items()))}")
        else:
            print("  No anti-patterns detected.")
        print()

    # Event history
    events = data.get("events", [])
    if events:
        print("## TASK EVENT HISTORY")
        for e in events:
            agent = e.get("agent", "?")[:12]
            action = e.get("action", "?")
            ts = e.get("timestamp", "?")[:19]
            sm = e.get("summary", "")[:80]
            print(f"  [{ts}] {action:15} by {agent:12} — {sm}")
        print()

    print("## END CRITIQUE INPUT PACKAGE")
    print(f"# Task: {task.id[:12]} | Ready for CRITIQUE agent analysis")


if __name__ == "__main__":
    main()
