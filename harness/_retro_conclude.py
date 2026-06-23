"""
_retro_conclude.py — EVAL, RETRO, CONCLUDE, REFRESH_CONTEXT phase handlers.

Each function is monkey-patched onto OrchestratorLoop as a bound method.
The self parameter refers to the OrchestratorLoop instance.
"""

from __future__ import annotations

import json
from pathlib import Path

from _loop_types import LoopAction, LoopOutcome, MAX_PHASE_RETRIES, ROOT
from pipeline_enforcer import PHASE_DESCRIPTIONS


# ── EVAL ─────────────────────────────────────────────────────────────────────

def _submit_eval(self, task_id: str, _ignored: str = "") -> LoopOutcome:
    """EVAL phase — the deterministic 100-point score. No model: computed from the
    real signals captured during the run (_run_eval also records the phase).
    Advances to RETRO so reflection has the objective score to reason about."""
    report = self._run_eval(task_id)   # computes the score AND marks EVAL complete

    # Micro mode: skip RETRO, CONCLUDE, REFRESH_CONTEXT — go directly to DONE
    task = self.db.get_task(task_id)
    if task and task.phase_mode == "micro":
        self.enforcer.mark_complete(
            task_id, "DONE", agent="evaluator",
            summary=f"Micro-mode pipeline complete (eval {report.total}/100)",
        )
        self._record_reward(task_id)
        outcome = LoopOutcome(
            action=LoopAction.DONE, phase="DONE", task_id=task_id,
            message=f"Scored {report.total}/100 ({report.grade}) — micro pipeline complete",
        )
        self._print_phase_summary("EVAL", task_id, outcome)
        return outcome

    outcome = LoopOutcome(
        action=LoopAction.RUN_PHASE, phase="RETRO", task_id=task_id,
        message=f"Scored {report.total}/100 ({report.grade}) — advancing to retro",
    )
    self._print_phase_summary("EVAL", task_id, outcome)
    return outcome


# ── RETRO ────────────────────────────────────────────────────────────────────

def _parse_retro_markers(reflection: str) -> dict:
    """Extract DECISION / LESSON / DISCIPLINE markers from retro text.

    Expected format:
        - DECISION: <what> — <why>
        - LESSON: <what>
        - DISCIPLINE: <what>
    Returns dict with keys 'decisions', 'lessons', 'disciplines' each a list of dicts.
    """
    import re
    result = {"decisions": [], "lessons": [], "disciplines": []}
    pattern = re.compile(r'^\s*[-*]\s+(DECISION|LESSON|DISCIPLINE)[:\s]+(.+)$', re.MULTILINE)
    for m in pattern.finditer(reflection):
        kind = m.group(1).lower() + "s"
        text = m.group(2).strip()
        # Split on em dash or en dash for what/why separation
        parts = re.split(r'\s*[—–]\s*', text, maxsplit=1)
        what = parts[0].strip()
        why = parts[1].strip() if len(parts) > 1 else ""
        if kind == "decisions":
            result["decisions"].append({"what": what, "why": why})
        elif kind == "lessons":
            result["lessons"].append({"what": what, "why": why})
        elif kind == "disciplines":
            result["disciplines"].append({"what": what, "why": why})
    return result


def _persist_retro(task_id: str, reflection: str, task_title: str) -> None:
    """Persist retro content to ledger.md, mistakes.md, and retros/ archive.

    Three outputs:
    1. ARCHIVE — full retro text saved to .techne/memory/retros/{task_id}.md
    2. LEDGER — DECISION/LESSON/DISCIPLINE markers extracted and logged
    3. MISTAKES — any error/cause/lesson patterns logged if format matches
    """
    from datetime import datetime, timezone
    from pathlib import Path

    memory_dir = Path(__file__).parent.parent / ".techne" / "memory"
    retros_dir = memory_dir / "retros"
    retros_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Archive full retro text
    retro_file = retros_dir / f"{task_id}.md"
    retro_file.write_text(
        f"# Retro — {task_title}\n"
        f"**Task:** {task_id}\n"
        f"**Date:** {now}\n\n"
        f"{reflection.strip()}\n",
        encoding="utf-8",
    )

    # 2. Extract and persist markers to ledger
    markers = _parse_retro_markers(reflection)
    try:
        from ledger import log_decision, log_lesson, log_discipline
        for d in markers["decisions"]:
            log_decision(what=d["what"], why=d["why"], source=f"retro:{task_id[:12]}")
        for l in markers["lessons"]:
            log_lesson(what=l["what"], why=l["why"], source=f"retro:{task_id[:12]}")
        for d in markers["disciplines"]:
            log_discipline(what=d["what"], why=d["why"], source=f"retro:{task_id[:12]}")
    except Exception as e:
        print(f"[RETRO] Warning: ledger write failed: {e}")

    # 3. Log mistake patterns (entries with Error/Cause/Lesson structure)
    try:
        from mistakes import log_mistake
        # Also log any explicit mistake patterns from the retro
        import re
        for m in re.finditer(
            r'^\s*[-*]\s+Error\s*:\s*(.+)$',
            reflection, re.MULTILINE,
        ):
            log_mistake(
                phase="RETRO",
                error=m.group(1).strip(),
                source=f"retro:{task_id[:12]}",
            )
    except Exception as e:
        print(f"[RETRO] Warning: mistakes write failed: {e}")


def _submit_retro(self, task_id: str, reflection: str) -> LoopOutcome:
    """RETRO phase — record the run's reflection, then advance to CONCLUDE.

    The retro agent (agents/retro.md) answers the structured questions, reflects on
    the EVAL score + per-skill recurrence, and STAGES skill-edit proposals
    (ratify-gated, never auto-applied). Here we record it and advance to CONCLUDE.

    Gate: retro must be substantive, not a checkbox.

    Retry leak fix: if RETRO exhausts its retry budget, we set _retro_skipped
    and advance to CONCLUDE rather than blocking the task permanently.
    """
    # Gate: reject checkbox retros
    if len(reflection.strip()) < 100:
        if self._bump_retry(task_id, "RETRO"):
            # Exhausted — skip RETRO, advance to CONCLUDE
            self._retro_skipped = getattr(self, '_retro_skipped', {})
            self._retro_skipped[task_id] = True
            outcome = LoopOutcome(
                action=LoopAction.RUN_PHASE, phase="CONCLUDE", task_id=task_id,
                message=(
                    f"RETRO exhausted after {MAX_PHASE_RETRIES['RETRO']} attempts. "
                    "Skipping retro — advancing to conclude."
                ),
            )
        else:
            outcome = LoopOutcome(
                action=LoopAction.RETRY, phase="RETRO", task_id=task_id,
                message=(
                    "RETRO too short (< 100 chars). Answer the 7 questions, reference "
                    "completed phases, and record lessons learned. This is not a checkbox."
                ),
            )
        self._print_phase_summary("RETRO", task_id, outcome)
        return outcome

    # Gate: must reference at least one completed phase (shows it looked at the run)
    history = self.db.get_task_history(task_id)
    completed_phases = [e.action for e in history if e.action in PHASE_DESCRIPTIONS]
    reflection_lower = reflection.lower()
    referenced = [p for p in completed_phases if p.lower() in reflection_lower]
    if not referenced:
        if self._bump_retry(task_id, "RETRO"):
            # Exhausted — skip RETRO, advance to CONCLUDE
            self._retro_skipped = getattr(self, '_retro_skipped', {})
            self._retro_skipped[task_id] = True
            outcome = LoopOutcome(
                action=LoopAction.RUN_PHASE, phase="CONCLUDE", task_id=task_id,
                message=(
                    f"RETRO exhausted after {MAX_PHASE_RETRIES['RETRO']} attempts. "
                    "Skipping retro — advancing to conclude."
                ),
            )
        else:
            outcome = LoopOutcome(
                action=LoopAction.RETRY, phase="RETRO", task_id=task_id,
                message=(
                    "RETRO doesn't reference any completed phase. "
                    f"Phases this run: {', '.join(completed_phases)}. "
                    "Reference what happened — what went well, what broke, what to change."
                ),
            )
        self._print_phase_summary("RETRO", task_id, outcome)
        return outcome

    self._reset_phase_retry(task_id, "RETRO")
    self.enforcer.mark_complete(
        task_id, "RETRO", agent="retro",
        summary=reflection[:200], findings=reflection,
    )

    # Persist retro to ledger, mistakes, and archive
    try:
        task = self.db.get_task(task_id)
        task_title = task.title if task else task_id
        _persist_retro(task_id, reflection, task_title)
    except Exception as e:
        print(f"[RETRO] Warning: persistence failed: {e}")

    report = self._eval.get(task_id)
    total = report.total if report else 0

    # Fast-mode tasks skip CONCLUDE — advance directly to DONE
    task = self.db.get_task(task_id)
    if task and task.phase_mode == "fast":
        self.enforcer.mark_complete(
            task_id, "DONE", agent="retro",
            summary=f"Fast-mode pipeline complete (eval {total}/100)",
        )
        outcome = LoopOutcome(
            action=LoopAction.DONE, phase="DONE", task_id=task_id,
            message=f"Reflection recorded (eval {total}/100) — pipeline complete (fast mode)",
        )
        self._print_phase_summary("RETRO", task_id, outcome)
        return outcome

    outcome = LoopOutcome(
        action=LoopAction.RUN_PHASE, phase="CONCLUDE", task_id=task_id,
        message=f"Reflection recorded (eval {total}/100) — advancing to conclude",
    )
    self._print_phase_summary("RETRO", task_id, outcome)
    return outcome


# ── CONCLUDE ─────────────────────────────────────────────────────────────────

def _submit_conclude(self, task_id: str, result: str) -> LoopOutcome:
    """CONCLUDE phase — durable write-back and context/doc closure.

    The host must write durable facts back to Honcho and close the context-guard
    punch list: docs updated or explicitly not needed, .techne/context refreshed
    or explicitly not needed. Then we mark DONE and record the RL reward.
    """
    validation_error = self._validate_conclude_proof(result, task_id)
    if validation_error:
        if self._bump_retry(task_id, "CONCLUDE"):
            outcome = LoopOutcome(
                action=LoopAction.FAILED, phase="CONCLUDE", task_id=task_id,
                message=f"CONCLUDE failed after {MAX_PHASE_RETRIES['CONCLUDE']} attempts. Escalating.",
            )
        else:
            outcome = LoopOutcome(
                action=LoopAction.RETRY, phase="CONCLUDE", task_id=task_id,
                message=validation_error,
            )
        self._print_phase_summary("CONCLUDE", task_id, outcome)
        return outcome

    self._reset_phase_retry(task_id, "CONCLUDE")
    self.enforcer.mark_complete(
        task_id, "CONCLUDE", agent="concluder",
        summary=f"Closure proof: {result[:150]}",
        findings=result,
    )

    # ── Retro-learn trigger ──
    # After every CONCLUDE, snapshot the per-skill mistake counts so retro-learn
    # can decide whether to propose a skill edit (>=2 ACTIVE on one skill) or
    # a new gate (>=4). The host reads the snapshot — no LLM call here.
    try:
        from mistakes import count_by_skill
        from ledger import count_by_kind as ledger_by_kind
        recurrence = count_by_skill()
        if any(n >= 2 for n in recurrence.values()):
            self._log_retro_learn_trigger(task_id, recurrence, ledger_by_kind())
    except Exception:
        pass  # retro-learn is best-effort — don't block CONCLUDE on a snapshot error

    report = self._eval.get(task_id)
    total = report.total if report else 0
    outcome = LoopOutcome(
        action=LoopAction.RUN_PHASE, phase="REFRESH_CONTEXT", task_id=task_id,
        message=f"Conclusion recorded (eval {total}/100) — advancing to context refresh",
    )
    self._print_phase_summary("CONCLUDE", task_id, outcome)
    return outcome


# ── REFRESH_CONTEXT ──────────────────────────────────────────────────────────

def _submit_refresh_context(self, task_id: str, result: str = "") -> LoopOutcome:
    """REFRESH_CONTEXT phase — rebuild generated workshop artifacts.

    Runs refresh_generated_docs.py as a subprocess, passing touched files
    from the CONTEXT_GUARD phase. On success, marks REFRESH_CONTEXT complete,
    records the RL reward, and transitions to DONE.

    Fast-mode tasks skip the script execution entirely.

    Patch 3: If .techne/config.yaml does not exist, skip gracefully instead
    of failing — projects without a workshop setup should still complete.
    """
    import subprocess

    task = self.db.get_task(task_id)

    # Fast-mode: skip the full refresh, just record reward and mark DONE
    if task and task.phase_mode == "fast":
        self.enforcer.mark_complete(
            task_id, "DONE", agent="orchestrator",
            summary="Fast-mode pipeline complete — context refresh skipped",
        )
        self._record_reward(task_id)
        outcome = LoopOutcome(
            action=LoopAction.DONE, phase="DONE", task_id=task_id,
            message="Context refresh skipped (fast mode) — task complete",
        )
        self._print_phase_summary("REFRESH_CONTEXT", task_id, outcome)
        return outcome

    # ── Patch 3: Graceful skip when no .techne/config.yaml ─────────────
    config_path = ROOT / ".techne" / "config.yaml"
    if not config_path.exists():
        self.enforcer.mark_complete(
            task_id, "REFRESH_CONTEXT", agent="refresh_context",
            summary="No .techne/config.yaml — context refresh skipped",
            findings="",
        )
        self._record_reward(task_id)
        outcome = LoopOutcome(
            action=LoopAction.DONE, phase="DONE", task_id=task_id,
            message="Context refresh skipped (no workshop config) — task complete",
        )
        self._print_phase_summary("REFRESH_CONTEXT", task_id, outcome)
        return outcome
    # ── end Patch 3 ─────────────────────────────────────────────────

    # Get touched files from CONTEXT_GUARD's punch list
    history = self.db.get_task_history(task_id)
    context_guard = next((e for e in reversed(history) if e.action == "CONTEXT_GUARD"), None)
    touched = []
    if context_guard and context_guard.changed_files:
        touched = json.loads(context_guard.changed_files) if isinstance(context_guard.changed_files, str) else context_guard.changed_files

    script = Path(__file__).parent.parent / ".techne" / "scripts" / "refresh_generated_docs.py"
    cmd = ["python3", str(script), "--task", task_id, "--json"]
    for f in touched[:10]:
        cmd.extend(["--files", f])

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        if self._bump_retry(task_id, "REFRESH_CONTEXT"):
            outcome = LoopOutcome(
                action=LoopAction.FAILED, phase="REFRESH_CONTEXT", task_id=task_id,
                message=f"REFRESH_CONTEXT failed after {MAX_PHASE_RETRIES['REFRESH_CONTEXT']} attempts. Escalating.",
            )
        else:
            outcome = LoopOutcome(
                action=LoopAction.RETRY, phase="REFRESH_CONTEXT", task_id=task_id,
                message=(
                    f"REFRESH_CONTEXT failed: "
                    f"{(proc.stderr or proc.stdout or 'unknown error').strip()[:200]}"
                ),
            )
        self._print_phase_summary("REFRESH_CONTEXT", task_id, outcome)
        return outcome

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        if self._bump_retry(task_id, "REFRESH_CONTEXT"):
            outcome = LoopOutcome(
                action=LoopAction.FAILED, phase="REFRESH_CONTEXT", task_id=task_id,
                message=f"REFRESH_CONTEXT failed after {MAX_PHASE_RETRIES['REFRESH_CONTEXT']} attempts. Escalating.",
            )
        else:
            outcome = LoopOutcome(
                action=LoopAction.RETRY, phase="REFRESH_CONTEXT", task_id=task_id,
                message="REFRESH_CONTEXT failed: script output is not valid JSON",
            )
        self._print_phase_summary("REFRESH_CONTEXT", task_id, outcome)
        return outcome

    self._reset_phase_retry(task_id, "REFRESH_CONTEXT")
    self.enforcer.mark_complete(
        task_id, "REFRESH_CONTEXT", agent="refresh_context",
        summary=(
            f"Refreshed: {len(payload.get('generated_updated', []))} files, "
            f"{len(payload.get('stale_docs', []))} stale docs flagged"
        ),
        findings=json.dumps(payload),
    )
    self._record_reward(task_id)
    outcome = LoopOutcome(
        action=LoopAction.DONE, phase="DONE", task_id=task_id,
        message="Context refreshed — task complete",
    )
    self._print_phase_summary("REFRESH_CONTEXT", task_id, outcome)
    return outcome


# ── RETRO_LEARN_TRIGGER ───────────────────────────────────────────────────────

def _log_retro_learn_trigger(self, task_id: str, recurrence: dict,
                             ledger_counts: dict) -> None:
    """Write a retro-learn trigger line + rebuild wikilink index.

    Two outputs:
    1. memory/retro_learn_triggers.md — append-only log of "this task should be retro'd"
    2. memory/wikilinks.{md,json} — rebuilt index of all mistakes + ledger entries
       (refreshed every DONE so the wikilinks never go stale)

    The retro-learn skill (or host) reads trigger lines and acts on them.
    The wikilink index is bidirectional: each entry links to its skill,
    each skill links back to its entries. Tools consume the JSON, humans
    read the Markdown.
    """
    from datetime import datetime, timezone

    memory_dir = Path(__file__).parent.parent / ".techne" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    triggers = memory_dir / "retro_learn_triggers.md"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    recurring = ", ".join(f"{s}:{n}" for s, n in sorted(recurrence.items(), key=lambda x: -x[1]) if n >= 2)
    if not recurring and not ledger_counts:
        return  # nothing to retro-learn
    line = f"- [{now}] task {task_id} | recurrence: {recurring or '(none)'} | ledger: {ledger_counts or '(empty)'}\n"
    if not triggers.exists():
        triggers.write_text(
            "# Retro-Learn Triggers\n"
            "# Auto-written when a task completes with recurring mistakes or new ledger entries.\n"
            "# Read by retro-learn to decide what to propose (skill edit / new gate / nothing).\n\n",
            encoding="utf-8",
        )
    with triggers.open("a", encoding="utf-8") as f:
        f.write(line)

    # Rebuild wikilink index — cheap and keeps the registry current
    try:
        from wikilink import build_graph, format_markdown as wl_md
        import json as _json
        graph = build_graph()
        (memory_dir / "wikilinks.md").write_text(wl_md(graph), encoding="utf-8")
        (memory_dir / "wikilinks.json").write_text(
            _json.dumps(graph, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass  # wikilink build is best-effort — never block DONE
