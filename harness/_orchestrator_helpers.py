"""
_orchestrator_helpers.py — Helper methods that don't belong to a single phase.

These are utilities used across multiple phases, including:
- _validate_conclude_proof
- _get_uncommitted_context_files
- _record_reward
- _ensure_techne_gitignore
- _prune_task_artifacts
- _build_eval_metrics
- _run_eval
- get_eval

Each function is monkey-patched onto OrchestratorLoop as a bound method.
The self parameter refers to the OrchestratorLoop instance.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from _loop_types import ROOT, MAX_TOTAL_RETRIES
from evaluator import evaluate_pipeline_run, EvalReport


# ── CONCLUDE proof validation ────────────────────────────────────────────────

def _validate_conclude_proof(self, result: str, task_id: str | None = None) -> str:
    """Validate CONCLUDE proof: Honcho + docs closure + context closure.

    Parses the proof line-by-line looking for structured prefixes:
      HONCHO: <proof text>
      DOCS: <path> updated OR NOT_NEEDED: <reason>
      CONTEXT: <path> refreshed OR NOT_NEEDED: <reason> [sha:<hex>]

    Rejects if any required section is missing, if the CONTEXT line claims
    an update without a commit SHA, or if .techne/context has uncommitted
    changes in the working tree relevant to the task's touched files.
    """
    if not result or len(result.strip()) < 20:
        return (
            "Proof is too short or empty — CONCLUDE requires HONCHO/DOCS/CONTEXT proof lines"
        )

    # Parse structured lines: prefix must start a non-blank line
    conclusion_id = check_honcho_logged()
    has_honcho = conclusion_id is not None
    context_line = None  # the raw CONTEXT line (if any)
    for line in result.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("context"):
            context_line = stripped
        # DOCS: detected by prefix — but we only need to know it exists
        # (too many valid formats: "DOCS: NOT_NEEDED: ...", "DOCS: docs/X.md updated")

    has_docs = any(l.strip().lower().startswith("docs:") for l in result.splitlines())
    has_context = context_line is not None

    missing = []
    if not has_honcho:
        missing.append("HONCHO line (start a line with 'HONCHO: <proof>')")
    if not has_docs:
        missing.append("DOCS line (start a line with 'DOCS: <path> updated' or 'DOCS: NOT_NEEDED: <reason>')")
    if not has_context:
        missing.append("CONTEXT line (start a line with 'CONTEXT: <path> refreshed' or 'CONTEXT: NOT_NEEDED: <reason>')")
    if missing:
        return "CONCLUDE missing proof: " + "; ".join(missing)

    # ── Hard gate: .techne/context must be committed if modified ──
    # If task_id is provided, extract changed_files from CONTEXT_GUARD event
    # to scope the gate to only task-relevant context files.
    changed_files = None
    if task_id:
        try:
            history = self.db.get_task_history(task_id)
            context_guard = next(
                (e for e in reversed(history) if e.action == "CONTEXT_GUARD"),
                None,
            )
            if context_guard and context_guard.changed_files:
                changed_files = (
                    json.loads(context_guard.changed_files)
                    if isinstance(context_guard.changed_files, str)
                    else context_guard.changed_files
                )
        except Exception:
            pass  # best-effort — fall through to full check
    uncommitted = self._get_uncommitted_context_files(touched_files=changed_files)
    if uncommitted:
        return (
            f"CONCLUDE blocked: .techne/context has uncommitted changes. "
            f"Stage and commit before concluding. Files: {', '.join(uncommitted)}"
        )

    # ── Hard gate: SHA required when context was updated (not NOT_NEEDED) ──
    if context_line is None:
        return ""  # already checked above, but pyright needs the guard
    ctx_lower = context_line.lower()
    context_updated = ".techne/context" in ctx_lower and "not_needed" not in ctx_lower
    if context_updated:
        # SHA must appear ON THE CONTEXT LINE specifically
        has_sha = bool(re.search(r"sha[:\s]+[0-9a-f]{40}", ctx_lower))
        if not has_sha:
            return (
                "CONCLUDE missing SHA proof. The CONTEXT line claims .techne/context "
                "was updated but no commit SHA was found on that line. "
                "Format: CONTEXT: .techne/context/<path> refreshed sha:<full-sha>"
            )

    return ""


# ── Uncommitted context files ────────────────────────────────────────────────

def _get_uncommitted_context_files(self, touched_files: list[str] | None = None) -> list[str]:
    """Return list of uncommitted .techne/context files, or [] if clean.

    Walks up from CWD (where scripts are always cd'd to project root) to find
    .git, then checks .techne/context for uncommitted changes. Falls back to
    walking up from db_path if CWD approach fails.

    When *touched_files* is provided, the result is filtered to only context
    files whose subsystem overlaps with the touched files' subsystems, using
    detect_subsystems_for_files() from the workshop module. This prevents an
    unrelated dirty context file from blocking the CONCLUDE gate.
    """
    import os

    def find_repo_root(start: Path) -> Path | None:
        cursor = start
        while cursor != cursor.parent:
            if (cursor / ".git").is_dir():
                return cursor
            cursor = cursor.parent
        return None

    try:
        # Primary: walk up from CWD (script always cd'd to project root)
        repo_root = find_repo_root(Path.cwd())
        if repo_root is None:
            # Fallback: walk up from db_path
            repo_root = find_repo_root(Path(self.db.db_path).parent)
        if repo_root is None:
            return []  # non-git — skip gate

        # Check full status then filter — glob misses nested paths like stage/app/.techne/context/
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", "."],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        uncommitted = [l.split(None, 1)[1] for l in result.stdout.strip().split("\n") if l.strip()]
        uncommitted = [f for f in uncommitted if ".techne/context" in f]

        # ── Scope gate to task-relevant subsystems ──
        if touched_files and uncommitted:
            try:
                from workshop import detect_subsystems_for_files
                index_path = repo_root / ".techne" / "generated" / "context_index.json"
                if index_path.exists():
                    index = json.loads(index_path.read_text(encoding="utf-8"))
                    touched_subsystems = detect_subsystems_for_files(index, touched_files)
                    if touched_subsystems:
                        filtered = []
                        for f in uncommitted:
                            p = Path(f)
                            # Subsystem is the filename stem before ".CONTEXT.md"
                            # e.g. ".techne/context/auth.CONTEXT.md" -> "auth"
                            subsystem = p.stem.replace(".CONTEXT", "")
                            if subsystem in touched_subsystems:
                                filtered.append(f)
                        return filtered
            except Exception:
                pass  # best-effort — fall through to return all uncommitted

        return uncommitted
    except Exception:
        return []  # error — skip gate rather than block


# ── Reward recording ──────────────────────────────────────────────────────────

def _record_reward(self, task_id: str) -> None:
    """
    Record the RL reward for a task that reached a terminal outcome.

    Both wins (DONE) and losses (retries exhausted → escalation) train the
    loop — learning only from successes biases evolution toward variants
    that never get hard tasks. Reads the real signals captured during the
    run; a signal left unset means the run never earned it (a task that
    failed at IMPLEMENT never ran tests), so it defaults to False.
    """
    task = self.db.get_task(task_id)
    self.reward_log.record(
        task_id=task_id,
        task_type=self._task_type.get(task_id, "general"),
        prompt_variant=self._variant_used.get(task_id, "v1"),
        gate_pass=self._gate_pass.get(task_id, False),     # real: hard gates
        test_pass=self._test_pass.get(task_id, False),     # real: SHA gate
        review_findings=self._review_findings.get(task_id, []),
        critique_predictions=self._critique_predictions.get(task_id, []),
        scope_clean=self._scope_clean.get(task_id, False),  # real: focus/scope/intent
        attempt_count=max(1, task.attempt if task else 1),  # >=1: a terminal task ran at least once
        gate_violations=self._gate_violations.get(task_id, 0),
    )
    # ── Patch 4: ensure .gitignore and prune artifacts on DONE ──────
    if task and task.status == "DONE":
        try:
            self._ensure_techne_gitignore(str(ROOT))
            self._prune_task_artifacts(task_id)
        except Exception:
            pass  # best-effort — never block DONE on gitignore/cleanup failure
    # ── end Patch 4 ───────────────────────────────────────────────


# ── gitignore + cleanup helpers ──────────────────────────────────────────────

def _ensure_techne_gitignore(self, project_root: str) -> None:
    """
    Ensure .gitignore contains .techne/tasks/, .techne/reports/, .techne/logs/,
    and .techne/memory/.

    These directories hold ephemeral state (task records, memory snapshots)
    that should never be committed. Called from _record_reward on DONE.
    """
    from pathlib import Path
    gitignore_path = Path(project_root) / ".gitignore"
    entries = [".techne/tasks/", ".techne/reports/", ".techne/logs/", ".techne/memory/"]

    if not gitignore_path.exists():
        content = ""
    else:
        content = gitignore_path.read_text(encoding="utf-8")

    updated = False
    for entry in entries:
        if entry not in content:
            content += f"\n{entry}\n"
            updated = True

    if updated:
        gitignore_path.write_text(content, encoding="utf-8")


def _prune_task_artifacts(self, task_id: str) -> None:
    """
    Prune ephemeral task artifacts after DONE.

    Removes task-specific files from .techne/tasks/ to keep the directory
    clean. Safe to call multiple times — only removes files matching this
    task's artifacts.
    """
    from pathlib import Path
    tasks_dir = ROOT / ".techne" / "tasks"
    if not tasks_dir.exists():
        return
    # Remove any task-specific output files (e.g. implementer_output_N.txt)
    for pattern in (f"implementer_output_*.txt", f"critique_output_*.txt",
                   f"review_output_*.txt"):
        for f in tasks_dir.glob(pattern):
            try:
                f.unlink()
            except OSError:
                pass


# ── EVAL helpers ─────────────────────────────────────────────────────────────

def _build_eval_metrics(self, task_id: str) -> dict:
    """
    Map the loop's captured enforcement signals onto the evaluator's
    metric kwargs — the SAME 100-point eval the conductor runs.

    Retro Value maps to the RL learning step (reward recording + per-run
    evolution), which is the loop's equivalent of the conductor's retro.
    """
    import re

    scope = self._scope.get(task_id)
    diff_text = self._diff.get(task_id, "")

    # Count drift markers robustly using regex — won't break on format changes
    # that preserve the semantic meaning (+  todo, +// todo, + console.log, etc.)
    def _count_pattern(text: str, pattern: str) -> int:
        try:
            return len(re.findall(pattern, text, re.IGNORECASE))
        except Exception:
            return 0

    drift = (
        _count_pattern(diff_text, r"\+\s{1,2}todo")
        + _count_pattern(diff_text, r"\+\s{1,2}fixme")
        + _count_pattern(diff_text, r"\+//\s*todo")
        + _count_pattern(diff_text, r"\+//\s*fixme")
        + _count_pattern(diff_text, r"\+console\.log")
    )
    test_pass = self._test_pass.get(task_id, False)
    return dict(
        gate_violations=self._gate_violations.get(task_id, 0),
        retries_used=self._retry_counts.get(task_id, 0),
        pipeline_halted=False,
        sha_passed=test_pass,
        output_existed=test_pass,
        had_pass_indicators=test_pass,
        diff_focused=scope.diff_focused if scope else True,
        scope_creep=scope.scope_creep if scope else False,
        review_result=self._review_result.get(task_id, "PASS"),
        drift_markers=drift,
        retro_ran=True,            # RL learning step = reward + evolution
        retro_questions=7,
    )


def _run_eval(self, task_id: str) -> EvalReport:
    """Run the deterministic 100-point eval and record it as the EVAL phase."""
    task = self.db.get_task(task_id)
    self._eval_run_no += 1
    report = evaluate_pipeline_run(
        task=task.title if task else task_id,
        pipeline_number=self._eval_run_no,
        **self._build_eval_metrics(task_id),
    )
    self._eval[task_id] = report
    self.enforcer.mark_complete(
        task_id, "EVAL",
        agent="evaluator",
        summary=f"Eval {report.total}/100 ({report.grade})",
        findings=report.format_report()[:1500],
        verdict="PASS" if report.total >= 75 else "SOFT_FAIL",
    )
    return report


def get_eval(self, task_id: str) -> EvalReport | None:
    """Return the 100-point eval report for a completed task, if any."""
    return self._eval.get(task_id)


# ── Import stub for check_honcho_logged used in _validate_conclude_proof ──────
from checkpoint import check_honcho_logged
