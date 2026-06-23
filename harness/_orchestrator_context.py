"""
_orchestrator_context.py — Context-building and RL integration helpers.

Contains methods that build user context, expected phases, RL integration,
and the post-run evolve dashboard — used by the facade class but kept
separate for clarity.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from _loop_types import ROOT, AGENTS_DIR
from pipeline_enforcer import PHASE_DESCRIPTIONS


# ── User context builder ─────────────────────────────────────────────────────

def _build_user_context(self, task_id: str, phase: str) -> str:
    """Build the user prompt context for a phase."""
    task = self.db.get_task(task_id)
    history = self.db.get_task_history(task_id)
    prior = [e for e in history if e.action in PHASE_DESCRIPTIONS]

    lines = [
        f"TASK: {task.title}",
        f"DESCRIPTION: {task.description}",
        f"DISCIPLINE: {task.discipline}",
        f"ATTEMPT: #{task.attempt}",
        f"PHASE: {phase}",
        "",
        f"INSTRUCTIONS: {PHASE_DESCRIPTIONS.get(phase, phase)}",
    ]

    # RECALL: host needs task title + tags to search Honcho
    if phase == "RECALL" and task:
        tags = ", ".join(task.tags) if task.tags else "none"
        lines.extend([
            "",
            f"TAGS: {tags}",
            "",
            "Run both recall sources before IMPLEMENT:",
            "- Honcho: recall durable user/workflow context relevant to the task.",
            "- Workshop: use the project workshop retrieval packet below.",
            "",
            "Required output format:",
            "HONCHO_CONTEXT: <durable context you recalled>",
            "WORKSHOP_CONTEXT: <comma-separated .techne/context docs used, or none>",
            "WORKSHOP_FILES: <comma-separated files surfaced by retrieval, or none>",
            "LESSONS: <relevant lessons/mistakes/decisions, or none>",
            "FOCUS: <2-4 lines on what IMPLEMENT should touch/avoid>",
        ])
        lines.extend(_build_workshop_recall_lines(task))

    # RETRO: inject mistakes.md, per-skill recurrence, routed skill content
    if phase == "RETRO" and task:
        lines.extend(_build_retro_context(task))

    # CONCLUDE: host must close context-guard's punch list with proof
    if phase == "CONCLUDE":
        context_guard = next((e for e in reversed(history) if e.action == "CONTEXT_GUARD"), None)
        lines.extend([
            "",
            "CONCLUDE PROOF REQUIRED:",
            "  HONCHO: honcho://conclusion/<id> or conclusion id from honcho_conclude",
            "  DOCS: docs/<file>.md updated OR NOT_NEEDED: <specific reason>",
            "  CONTEXT: .techne/context/<path> refreshed OR NOT_NEEDED: <specific reason>",
            "",
            "When CONTEXT is updated: commit .techne/context first, then include",
            "  sha:<full-commit-sha> in the CONTEXT line (the gate rejects without it).",
            "",
            "Close the Context-Guard punch list. Do not return a generic summary.",
        ])
        if context_guard:
            lines.extend([
                "",
                "LATEST CONTEXT_GUARD REPORT:",
                context_guard.findings or context_guard.summary,
            ])

    if prior:
        lines.append("")
        lines.append("COMPLETED PHASES:")
        for e in prior:
            lines.append(f"  {e.action}: {e.summary[:100]}")

    return "\n".join(lines)


def _build_workshop_recall_lines(task) -> list[str]:
    """Best-effort workshop retrieval packet for RECALL."""
    lines = ["", "WORKSHOP RETRIEVAL PACKET:"]
    try:
        from workshop import find_workshop_paths

        paths = find_workshop_paths(Path.cwd())
        if paths is None:
            lines.append("WORKSHOP_STATUS: no .techne/config.yaml found from current cwd upward")
            lines.append("WORKSHOP_QUERY: unavailable")
            return lines

        query_parts = [task.title or "", task.description or ""]
        if task.tags:
            query_parts.append(" ".join(task.tags))
        query = " ".join(part.strip() for part in query_parts if part and part.strip())
        script = paths.scripts_dir / "context_search.py"
        if not script.exists():
            lines.append(f"WORKSHOP_STATUS: missing script {script}")
            lines.append(f"WORKSHOP_QUERY: {query or task.title}")
            return lines

        proc = subprocess.run(
            ["python3", str(script), query or task.title, "--json"],
            cwd=str(paths.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or proc.stdout or "context_search failed").strip()
            lines.append(f"WORKSHOP_STATUS: retrieval failed: {stderr[:240]}")
            lines.append(f"WORKSHOP_QUERY: {query or task.title}")
            return lines

        payload = json.loads(proc.stdout)
        docs = [row.get("path", "") for row in payload.get("context_docs", [])[:5] if row.get("path")]
        files = [row.get("path", "") for row in payload.get("files", [])[:8] if row.get("path")]
        subsystems = [row.get("name", "") for row in payload.get("subsystems", [])[:5] if row.get("name")]
        memories = []
        for bucket in ("lessons", "mistakes", "decisions"):
            for row in payload.get(bucket, [])[:2]:
                what = row.get("what")
                if what:
                    memories.append(what)

        lines.extend([
            "WORKSHOP_STATUS: ok",
            f"WORKSHOP_QUERY: {payload.get('query', query or task.title)}",
            f"LIKELY_SUBSYSTEMS: {', '.join(subsystems) if subsystems else 'none'}",
            f"CONTEXT_DOC_CANDIDATES: {', '.join(docs) if docs else 'none'}",
            f"FILE_CANDIDATES: {', '.join(files) if files else 'none'}",
            f"MEMORY_CANDIDATES: {' | '.join(memories) if memories else 'none'}",
        ])
        return lines
    except Exception as exc:
        lines.append(f"WORKSHOP_STATUS: retrieval exception: {str(exc)[:240]}")
        return lines


def _build_retro_context(task) -> list[str]:
    """Build the rich context RETRO needs: mistakes.md, recurrence, routed skill."""
    from mistakes import count_by_skill, MISTAKES_FILE
    from router import route

    lines = []

    # 1. Per-skill recurrence counts
    by_skill = count_by_skill()
    if by_skill:
        lines.extend(["", "ACTIVE MISTAKES BY SKILL (recurrence → retro proposals):"])
        for s, n in sorted(by_skill.items(), key=lambda x: -x[1]):
            rec = "   <- RECURRING (>=2): propose an edit to this skill" if n >= 2 else ""
            lines.append(f"  {s}: {n} active{rec}")
    else:
        lines.extend(["", "ACTIVE MISTAKES BY SKILL: (none)"])

    # 2. Routed skill's current content
    matched = route(task.title)
    if matched:
        skill_path = ROOT / matched.get("skill_path", "")
        if skill_path.exists():
            lines.extend([
                "",
                f"--- {matched.get('skill_path', '')} (current content) ---",
                skill_path.read_text(encoding="utf-8"),
            ])

    # 3. Full mistakes.md
    if MISTAKES_FILE.exists():
        mistakes = MISTAKES_FILE.read_text(encoding="utf-8")
        lines.extend(["", f"mistakes.md content:", mistakes])

    return lines


# ── Phase-mode-aware expected phases ─────────────────────────────────────────

def _expected_phases(self, task_id: str) -> list[str]:
    """Return the ordered list of phases this task is expected to complete."""
    from pipeline_enforcer import PHASES

    task = self.db.get_task(task_id)
    mode = task.phase_mode if task else "full"

    if mode == "fast":
        # Skip RECALL, CONCLUDE, REFRESH_CONTEXT
        skip = {"RECALL", "CONCLUDE", "REFRESH_CONTEXT"}
    elif mode == "micro":
        # Only: IMPLEMENT → CONTEXT_GUARD → VERIFY → EVAL → DONE
        return ["IMPLEMENT", "CONTEXT_GUARD", "VERIFY", "EVAL", "DONE"]
    else:
        skip = set()

    return [p for p in PHASES if p not in skip]


# ── RL integration ─────────────────────────────────────────────────────────────

def set_task_type(self, task_id: str, task_type: str) -> None:
    """Set the task type for reward classification."""
    self._task_type[task_id] = task_type


def set_variant(self, task_id: str, variant: str) -> None:
    """Set which prompt variant was used for this task."""
    self._variant_used[task_id] = variant


def get_best_variant(self, task_type: str, agent: str = "implementer") -> str | None:
    """Get the best-performing variant name for a task type."""
    return self.reward_log.best_variant(task_type)


# ── Post-run evolve ───────────────────────────────────────────────────────────

def post_run_evolve(self) -> dict:
    """
    Run after all tasks complete. Stages prompt AND gate proposals.
    Returns summary of what was proposed.

    Both are staged only (propose → validate → ratify); neither a prompt
    rewrite nor a new gate is promoted until a human ratifies it. A gate is
    part of the grader, so the loop must never auto-write one — same firewall
    as prompts, applied to the grader.
    """
    from grpo import propose_grpo_edits, propose_skill_edits, propose_framework_edits
    from stack_detect import detect_stack

    result = {
        "prompts_proposed": [],
        "gates_proposed": [],
        "grpo_proposed": [],
        "framework_proposed": [],
        "dashboard": "",
    }

    # Stage a prompt proposal for each task type seen (pending ratification).
    for task_type in self.reward_log.all_task_types():
        proposal = self.evolution.propose(task_type, "implementer")
        if proposal is not None:
            result["prompts_proposed"].append({
                "task_type": task_type,
                "variant_name": proposal.variant_name,
                "proposal_id": proposal.id,
                "status": proposal.status,
            })

    # Stage gate proposals (recurrence gate). A gate is part of the grader,
    # so it is NOT written until validate() + ratify() — never auto-written.
    gate_proposals = self.gate_evolution.propose(min_count=3)
    result["gates_proposed"] = [
        {"gate_name": gp.gate_name, "proposal_id": gp.id,
         "source_count": gp.source_count, "status": gp.status}
        for gp in gate_proposals
    ]

    # B3: GRPO advantage-based proposals — write high-advantage variants
    # as PROPOSE ADD entries in retro_proposals.md for human confirmation.
    # This is the connector that turns RL advantage scores into real
    # skill file edits through the apply_retro.py write path.
    if self.reward_log is not None:
        try:
            self.reward_log.compute_batch_advantages()
            grpo_proposals = propose_grpo_edits(self.reward_log)
            result["grpo_proposed"] = grpo_proposals
            skill_proposals = propose_skill_edits(self.reward_log)
            if skill_proposals:
                result["grpo_proposed"].extend(
                    {"type": "skill", **p} for p in skill_proposals
                )

            # Framework-specific proposals go directly to skill files
            stack_tags = detect_stack(ROOT)
            if stack_tags:
                fw_proposals = propose_framework_edits(self.reward_log, stack_tags)
                if fw_proposals:
                    result["framework_proposed"] = fw_proposals
        except Exception:
            # GRPO proposals are best-effort — don't let failures block
            # the rest of post_run_evolve.
            result["grpo_proposed"] = []
    else:
        result["grpo_proposed"] = []

    # ── RL event log ───────────────────────────────────────────────────────
    # Audit trail: write a summary line to .techne/events/rl.jsonl every time
    # post_run_evolve() runs, so external dashboards and replay tools can
    # track what the RL loop proposed without parsing the full result dict.
    _events_dir = Path(".techne/events")
    _events_dir.mkdir(parents=True, exist_ok=True)
    _event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": "grpo_proposals",
        "task_count": len(self.reward_log.all_task_types()),
        "prompts_proposed": len(result.get("prompts_proposed", [])),
        "skills_proposed": len(
            [p for p in result.get("grpo_proposed", []) if p.get("type") == "skill"]
        ),
        "framework_proposed": len(result.get("framework_proposed", [])),
        "advantages_computed": True,
    }
    try:
        with open(_events_dir / "rl.jsonl", "a") as _f:
            _f.write(json.dumps(_event) + "\n")
    except Exception:
        # Event logging must never block post_run_evolve.
        pass

    # ── Rebuild wikilink knowledge graph ─────────────────────────────────
    # The wikilink index (wikilinks.json + wikilinks.md) is rebuilt every
    # DONE so the knowledge graph stays current with mistakes, ledger,
    # tasks.db, and workshop context. This is the same refresh that the
    # old orchestrator's REFRESH_CONTEXT phase ran.
    try:
        from wikilink import build_graph, format_markdown as wl_md
        memory_dir = Path(__file__).parent.parent / ".techne" / "memory"
        graph = build_graph()
        (memory_dir / "wikilinks.md").write_text(wl_md(graph), encoding="utf-8")
        (memory_dir / "wikilinks.json").write_text(
            json.dumps(graph, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        # Wikilink rebuild is best-effort — must never block post_run_evolve.
        pass

    # ── Conclude context amortization ────────────────────────────────────
    # The deterministic context pack (project_digest.md, commands.md,
    # file_roles.md) is refreshed so the next session's RECALL sees
    # current project state. Same conclude that the old orchestrator's
    # REFRESH_CONTEXT phase ran — regenerates derived files without
    # clobbering human-owned ones (risk_boundaries.md, docs/).
    try:
        from context_build import conclude_context
        techne_root = Path(__file__).parent.parent
        conclude_context(techne_root)
    except Exception:
        # Context conclude is best-effort — must never block post_run_evolve.
        pass

    # Dashboard
    result["dashboard"] = self.rl_dashboard()

    return result


def rl_dashboard(self) -> str:
    """Full RL dashboard: rewards + evolution + gates."""
    parts = [
        self.reward_log.dashboard(),
        "",
        self.evolution.dashboard(),
        "",
        self.gate_evolution.dashboard(),
    ]
    return "\n".join(parts)
