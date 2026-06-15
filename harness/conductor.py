"""
conductor.py — the host-driven pipeline state machine.

Techne is harness-native: a host agent (Claude Code, Hermes, OpenCode) IS the
model. This module never calls a model. It assembles the prompt for each phase,
the host runs its own turn and submits the artifact it produced, and Techne runs
every deterministic check (gates, SHA, intent L1/L2, checkpoint, eval, session).

Drive it turn by turn:

    from conductor import Pipeline

    p = Pipeline.start("add WhatsApp button to product page")

    # IMPLEMENT — host runs p.implement_prompt(), produces a diff
    res = p.submit_implementation(host_diff)
    while res.status == "RETRY":               # gate violation — host fixes and resubmits
        res = p.submit_implementation(host_fixed_diff)
    # res.status is PASS or HALT

    # VERIFY — host runs the tests, captures stdout
    p.submit_verification(host_test_output)

    # REVIEW — host reviews the diff
    p.submit_review(host_findings)

    # RETRO — host answers the 7-question retro
    p.submit_retro(host_retro_output)

    report = p.finalize()                       # eval report + SESSION.md
    print(report.format_report())

No ANTHROPIC_API_KEY. No network. The host supplies every model turn.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from gates import GateViolation
from gate_registry import GateRegistry
from sha_gate import gate_test_output
from mistakes import log_mistake, check_relevant, count_active
from evaluator import evaluate_pipeline_run, EvalReport, load_eval_history as _load_eval_history, _trend
from task_db import TaskDB
from pipeline_enforcer import PipelineEnforcer, get_phase_prompt
from checkpoint import (
    increment_pipeline_run,
    log_gate_pass,
    log_gate_fail,
    mark_verified,
    check_verification,
    get_summary,
)
from router import route, get_always_loaded, get_common_loaded
from session import new_session
from measure import run_measurements
from intent_reasoner import verdict_to_gate
from apply_retro import has_pending_proposals, auto_apply_pending

HARNESS_DIR = Path(__file__).parent        # techne/harness/
ROOT = HARNESS_DIR.parent                  # techne/
SKILLS_DIR = ROOT / "skills"
AGENTS_DIR = ROOT / "agents"
MEMORY_DIR = ROOT / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

MAX_RETRIES = 3


# ─── Host interface dataclasses ──────────────────────────────────────────────

@dataclass
class AgentPrompt:
    """A prompt for the host to execute as its own model turn."""
    system: str   # agent .md body (implementer / verifier / reviewer / retro)
    user: str     # assembled context (task + skills + mistakes + diff, etc.)


@dataclass
class PhaseResult:
    """Outcome of a host submission, evaluated by Techne's deterministic gates."""
    status: str                       # PASS | RETRY | HALT | DONE
    feedback: str = ""                # gate-violation text when status == RETRY
    detail: dict = field(default_factory=dict)


# ─── Prompt-assembly helpers (no model calls) ────────────────────────────────

def _read_skill_files(task: str = "") -> str:
    """Read skill files — always-loaded + task-relevant via router."""
    loaded = set()
    parts = []

    # Always-loaded skills (nextjs.md, typescript.md)
    for rel_path in get_always_loaded():
        full = ROOT / rel_path
        if full.exists() and full.name not in loaded:
            parts.append(f"=== {full.name} [always-loaded] ===\n{full.read_text(encoding='utf-8')}")
            loaded.add(full.name)

    # Task-routed skill
    if task:
        matched = route(task)
        if matched:
            skill_path = ROOT / matched.get("skill_path", "")
            if skill_path.exists() and skill_path.name not in loaded:
                parts.append(f"=== {skill_path.name} [routed: {matched['id']}] ===\n{skill_path.read_text(encoding='utf-8')}")
                loaded.add(skill_path.name)

    # Fallback: load any remaining skill files not yet included
    for md in sorted(SKILLS_DIR.glob("*.md")):
        if md.name not in loaded:
            parts.append(f"=== {md.name} ===\n{md.read_text(encoding='utf-8')}")

    return "\n\n".join(parts)


def _surface_relevant_mistakes(task: str) -> str:
    """Check mistakes.md for lessons relevant to this task."""
    relevant = check_relevant(task)
    if not relevant:
        return ""

    lines = [f"[CONDUCTOR] {len(relevant)} relevant mistake(s) found:"]
    for entry in relevant[:3]:
        lines.append(f"  - {entry['error'][:80]}")
        lines.append(f"    Lesson: {entry['lesson'][:80]}")

    return "\n".join(lines)


def _read_agent_prompt(agent_name: str) -> str:
    """Return the body of an agents/<name>.md file (frontmatter stripped)."""
    path = AGENTS_DIR / f"{agent_name}.md"
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        _, _, body = text.partition("---\n")
        _, _, body = body.partition("---\n")
        return body.strip()
    return text.strip()


# ─── The host-driven pipeline ────────────────────────────────────────────────

class Pipeline:
    """
    A pipeline run the host steps through turn by turn.

    Each phase exposes a *_prompt() the host executes, and a submit_*() that
    feeds the host's artifact back through Techne's deterministic gates.
    """

    def __init__(self, task: str, run_number: int, task_id: str | None = None):
        self.task = task
        self.run_number = run_number
        self.matched_skill = route(task)
        self.relevant_mistakes = _surface_relevant_mistakes(task)
        self.task_id = task_id
        self.db: TaskDB | None = None
        self.enforcer: PipelineEnforcer | None = None

        # Task DB integration (optional — for multi-agent pipeline)
        if task_id:
            self.db = TaskDB()
            self.enforcer = PipelineEnforcer(self.db)

        # Artifacts collected from the host as phases complete
        self.diff: str = ""
        self.sha: str = ""
        self.findings: str = ""

        self.retries_used = 0
        self._last_feedback = ""
        self.results: dict[str, str] = {}

        active_mistakes = count_active()
        # Eval metrics — known defaults, updated as real artifacts arrive
        self.eval_metrics: dict = {
            "gate_violations": 0,
            "retries_used": 0,
            "pipeline_halted": False,
            "sha_passed": False,
            "hash_unique": True,
            "output_existed": False,
            "had_pass_indicators": False,
            "skills_loaded": True,            # always-loaded files guarantee this
            "mistakes_consulted": active_mistakes > 0,
            "diff_focused": True,             # measured after diff is submitted
            "scope_creep": False,             # measured after diff is submitted
            "review_result": "SKIPPED",
            "shadow_gate_clean": True,
            "drift_markers": 0,
            "retro_ran": False,
            "retro_proposals": False,
            "retro_questions": 0,
        }

        # Gate registry — discovers plugins, loads config
        self.registry = GateRegistry()
        self.registry.discover_plugins()
        self.registry.load_config()

    # ── lifecycle ────────────────────────────────────────────────────────────

    @classmethod
    def start(cls, task: str, *, task_id: str | None = None) -> "Pipeline":
        """Begin a pipeline run: increment counter, route, surface mistakes."""
        run_number = increment_pipeline_run()
        p = cls(task, run_number, task_id=task_id)
        print(f"\n[CONDUCTOR] Starting pipeline #{run_number}: {task}")
        if p.matched_skill:
            print(f"[CONDUCTOR] Skill routed: {p.matched_skill['id']} "
                  f"({p.matched_skill.get('skill_path', '')})")
        else:
            print("[CONDUCTOR] No specific skill matched — loading all rules")
        if p.relevant_mistakes:
            print(p.relevant_mistakes)

        pending = has_pending_proposals()
        if pending:
            print(f"[CONDUCTOR] (!) {pending} unapplied retro proposal(s) in memory/retro_proposals.md")
            print("[CONDUCTOR]     Run: python harness/apply_retro.py")
        print("=" * 60)
        return p

    # ── IMPLEMENT ────────────────────────────────────────────────────────────

    def implement_prompt(self) -> AgentPrompt:
        """Prompt for the host to produce a diff. Includes prior gate feedback on retry."""
        # If task_db is active, inject phase context
        phase_context = ""
        if self.enforcer and self.task_id:
            phase = self.enforcer.get_phase(self.task_id)
            if phase and phase not in (None, "PENDING"):
                phase_context = f"\nCurrent pipeline phase: {phase}\n"

        if self._last_feedback:
            user = textwrap.dedent(f"""
                Your previous diff was rejected by the gate:

                {self._last_feedback}

                Fix only the specific violation above. Return the corrected unified diff.
            """).strip()
        else:
            skills = _read_skill_files(self.task)
            mistakes_block = (
                f"Past mistakes relevant to this task:\n{self.relevant_mistakes}\n"
                if self.relevant_mistakes else ""
            )
            user = textwrap.dedent(f"""
                Task: {self.task}

                Skill rules in effect:
                {skills}

                {mistakes_block}
                Return the unified diff only.
            """).strip()
        return AgentPrompt(system=_read_agent_prompt("implementer"), user=user)

    def submit_implementation(self, diff: str, semantic_verdict=None) -> PhaseResult:
        """
        Run gates on the host's diff. On violation: RETRY (host fixes, resubmits)
        until MAX_RETRIES, then HALT. On pass: measure focus/scope + intent L1/L2
        (optional host semantic_verdict), enforce the intent gate.
        """
        # Pipeline enforcer: check phase transition
        if self.enforcer and self.task_id:
            check = self.enforcer.can_enter(self.task_id, "IMPLEMENT")
            if not check.allowed and check.current_phase not in (None, "PENDING", "BLOCKED"):
                print(f"[CONDUCTOR] (!) Pipeline: {check.reason}")

        (MEMORY_DIR / "implementer_output.txt").write_text(diff, encoding="utf-8")
        try:
            self.registry.run_all(diff)
            log_gate_pass("all_gates" if self.retries_used == 0 else "all_gates_retry")
            print("[CONDUCTOR] IMPLEMENT passed all gates")
        except GateViolation as e:
            gate_name = str(e).split("[")[1].split("]")[0] if "[" in str(e) else "unknown"
            log_gate_fail(gate_name, str(e))
            log_mistake(
                phase="IMPLEMENT", error=str(e)[:200],
                cause="agent violated skill rule", lesson="pending retro", gate=gate_name,
            )
            self.retries_used += 1
            self.eval_metrics["gate_violations"] += 1
            self.eval_metrics["retries_used"] = self.retries_used
            self._last_feedback = str(e)
            if self.retries_used >= MAX_RETRIES:
                self.eval_metrics["pipeline_halted"] = True
                self.results["implement"] = "FAIL"
                print(f"[CONDUCTOR] IMPLEMENT halted after {MAX_RETRIES} attempts")
                return PhaseResult("HALT", feedback=str(e))
            print(f"[CONDUCTOR] IMPLEMENT gate failed (attempt {self.retries_used}): {e}")
            return PhaseResult("RETRY", feedback=str(e))

        # Gates passed — record diff and run measurements
        self._last_feedback = ""
        self.diff = diff
        self.results["implement"] = "PASS"

        measurements = run_measurements(self.task, diff, semantic_verdict=semantic_verdict)
        self.eval_metrics["diff_focused"] = measurements["diff_focused"]
        self.eval_metrics["scope_creep"] = measurements["scope_creep"]

        intent = measurements["_intent"]
        l1_score = intent.get("l1_score", 0.0)
        print(f"[CONDUCTOR] Intent check: {intent['warning']}"
              + (" (!)" if l1_score < 0.5 else ""))

        try:
            verdict_to_gate(intent, self.task)   # MISMATCH >= 70% -> GateViolation
        except GateViolation as eg:
            print(f"[CONDUCTOR] (!) Intent gate: {eg}")
            self.eval_metrics["diff_focused"] = False
            self.eval_metrics["pipeline_halted"] = True
            self.results["implement"] = "FAIL"
            log_mistake(
                phase="IMPLEMENT", error=f"Intent gate: {intent.get('verdict', 'MISMATCH')}",
                cause=intent.get("reason", ""), lesson="diff did not implement the stated task",
                gate="intent",
            )
            return PhaseResult("HALT", feedback=str(eg), detail={"intent": intent})

        return PhaseResult("PASS", detail={"intent": intent})

    # ── VERIFY ───────────────────────────────────────────────────────────────

    def verify_prompt(self) -> AgentPrompt:
        """Prompt for the host to run the test suite and capture stdout."""
        user = textwrap.dedent(f"""
            The following diff was produced by the implementer and passed code gates.
            Run the test suite now. Return full stdout (it will be hashed by the SHA gate).

            Diff (for context only — do not re-apply it):
            {self.diff[:2000]}
        """).strip()
        return AgentPrompt(system=_read_agent_prompt("verifier"), user=user)

    def submit_verification(self, test_output: str) -> PhaseResult:
        """Persist host test output, run the SHA gate, mark verified."""
        (MEMORY_DIR / "test_output.txt").write_text(test_output, encoding="utf-8")
        try:
            sha = gate_test_output(
                test_output_path=str(MEMORY_DIR / "test_output.txt"),
                run_log_path=str(MEMORY_DIR / "run_log.json"),
            )
        except Exception as e:
            self.results["verify"] = "FAIL"
            self.eval_metrics["pipeline_halted"] = True
            print(f"[CONDUCTOR] VERIFY SHA gate failed: {e}")
            return PhaseResult("HALT", feedback=str(e))

        log_gate_pass("sha_gate")
        mark_verified(sha)
        self.sha = sha
        self.results["verify"] = f"PASS (sha: {sha[:16]}...)"
        self.eval_metrics["sha_passed"] = True
        self.eval_metrics["output_existed"] = True
        self.eval_metrics["had_pass_indicators"] = True
        print(f"[CONDUCTOR] VERIFY passed — SHA: {sha[:16]}...")
        return PhaseResult("PASS", detail={"sha": sha})

    # ── REVIEW ───────────────────────────────────────────────────────────────

    def review_prompt(self) -> AgentPrompt:
        """Prompt for the host to review the diff."""
        user = textwrap.dedent(f"""
            Review the following diff. Tests passed (SHA: {self.sha[:16]}...).

            Diff:
            {self.diff}
        """).strip()
        return AgentPrompt(system=_read_agent_prompt("reviewer"), user=user)

    # ── CONTEXT-GUARD ──────────────────────────────────────────────────────

    def context_guard_prompt(self) -> AgentPrompt:
        """Prompt for the host to run the context-guard audit."""
        user = textwrap.dedent(f"""
            Task: {self.task}
            Scan all changes and record an audit trail.
            Diff (for context):
            {self.diff[:3000]}
        """).strip()
        return AgentPrompt(system=_read_agent_prompt("context-guard"), user=user)

    def submit_context_guard(self, audit_report: str) -> PhaseResult:
        """Record context-guard audit. No gate check — purely informational."""
        if self.enforcer and self.task_id:
            self.enforcer.mark_complete(
                self.task_id, "CONTEXT_GUARD",
                agent="context-guard",
                summary=audit_report[:200],
                findings=audit_report,
            )
        self.results["context_guard"] = "PASS"
        print("[CONDUCTOR] CONTEXT-GUARD complete")
        return PhaseResult("PASS")

    # ── CRITIQUE ───────────────────────────────────────────────────────────

    def critique_prompt(self) -> AgentPrompt:
        """Prompt for the host to run predictive fault analysis."""
        user = textwrap.dedent(f"""
            Task: {self.task}
            Predict emergent bugs from this implementation.
            Diff:
            {self.diff[:3000]}
        """).strip()
        return AgentPrompt(system=_read_agent_prompt("critique"), user=user)

    def submit_critique(self, critique_report: str) -> PhaseResult:
        """Record critique findings. Triggers debugger if CRITICAL."""
        if self.enforcer and self.task_id:
            verdict = "PASS"
            if "CRITICAL" in critique_report:
                verdict = "HARD_FAIL"
            self.enforcer.mark_complete(
                self.task_id, "CRITIQUE",
                agent="critique",
                summary=critique_report[:200],
                verdict=verdict,
                findings=critique_report,
            )
            if verdict == "HARD_FAIL":
                self.results["critique"] = "HARD_FAIL"
                self.eval_metrics["pipeline_halted"] = True
                print("[CONDUCTOR] CRITIQUE found CRITICAL issues — debugger recommended")
                return PhaseResult("HALT", feedback="CRITICAL: " + critique_report[:200])
        self.results["critique"] = "PASS"
        print("[CONDUCTOR] CRITIQUE complete")
        return PhaseResult("PASS")

    # ── DEBUG ──────────────────────────────────────────────────────────────

    def debug_prompt(self) -> AgentPrompt:
        """Prompt for the debugger agent — called when implementer fails repeatedly."""
        history_text = ""
        if self.enforcer and self.task_id:
            history = self.db.get_task_history(self.task_id)
            history_text = "\n".join(
                f"  {e.action}: {e.summary[:80]}" for e in history
            )
        user = textwrap.dedent(f"""
            Task: {self.task}
            This task has failed multiple times. Diagnose the root cause.

            Event history:
            {history_text or '(no history)'}

            Last gate feedback: {self._last_feedback or '(none)'}
        """).strip()
        return AgentPrompt(system=_read_agent_prompt("debugger"), user=user)

    def submit_review(self, findings: str) -> PhaseResult:
        """Evaluate the host's review findings."""
        self.findings = findings
        if "HARD_FAIL" in findings:
            log_gate_fail("review", "HARD_FAIL in review findings")
            self.results["review"] = "SOFT_FAIL"
            self.eval_metrics["review_result"] = "SOFT_FAIL"
        else:
            log_gate_pass("review")
            self.results["review"] = "PASS"
            self.eval_metrics["review_result"] = "PASS"

        self.eval_metrics["shadow_gate_clean"] = (
            "SHADOW GATE CHECK: clean" in findings or "shadow" not in findings.lower()
        )
        # Count drift markers in the DIFF, not the reviewer's report
        diff_lower = self.diff.lower()
        self.eval_metrics["drift_markers"] = (
            diff_lower.count("+  todo") + diff_lower.count("+ // todo")
            + diff_lower.count("+  fixme") + diff_lower.count("+ // fixme")
            + diff_lower.count("+ console.log") + diff_lower.count("+console.log")
        )
        print(f"[CONDUCTOR] Review result: {self.eval_metrics['review_result']}")
        return PhaseResult("PASS", detail={"review": self.eval_metrics["review_result"]})

    # ── RETRO ────────────────────────────────────────────────────────────────

    def retro_prompt(self) -> AgentPrompt:
        """Prompt for the host to run the 7-question retro."""
        mistakes_path = MEMORY_DIR / "mistakes.md"
        mistakes = mistakes_path.read_text(encoding="utf-8") if mistakes_path.exists() else "(none)"
        user = f"Run the 7-question retro and skill file analysis.\n\nmistakes.md content:\n{mistakes}"
        return AgentPrompt(system=_read_agent_prompt("retro"), user=user)

    def submit_retro(self, output: str = "", questions_answered: int = 7,
                     produced_proposals: bool = False) -> PhaseResult:
        """Record retro completion."""
        self.eval_metrics["retro_ran"] = True
        self.eval_metrics["retro_questions"] = questions_answered
        self.eval_metrics["retro_proposals"] = produced_proposals
        print("[CONDUCTOR] RETRO complete")
        return PhaseResult("DONE")

    # ── RETRO LOOP (close the learning loop) ────────────────────────────────

    def apply_retro_prompt(self) -> AgentPrompt:
        """
        Prompt for the host to review retro proposals before auto-apply.
        The host can approve (submit_retro_approve) or skip.
        """
        pending = has_pending_proposals()
        user = textwrap.dedent(f"""
            {pending} retro proposal(s) pending in memory/retro_proposals.md.

            Review the proposals. If they look correct, respond with APPROVE.
            If any should be skipped, respond with SKIP: <reason>.

            The proposals will be applied automatically after your approval.
        """).strip()
        return AgentPrompt(system=_read_agent_prompt("retro"), user=user)

    def submit_retro_approve(self, approval: str = "APPROVE") -> PhaseResult:
        """Apply retro proposals if host approved."""
        if "APPROVE" in approval.upper():
            result = auto_apply_pending()
            self.eval_metrics["retro_proposals_applied"] = result.get("applied", 0)
            print(f"[CONDUCTOR] Retro proposals applied: {result}")
            return PhaseResult("PASS", detail={"retro_apply": result})
        else:
            print("[CONDUCTOR] Retro proposals skipped by host")
            return PhaseResult("PASS", detail={"retro_apply": "skipped"})

    # ── HOST GATE INJECTION ───────────────────────────────────────────────────

    def register_host_gate(self, name, fn, **kwargs):
        """
        Let the host inject a custom gate at pipeline start.
        Example: p.register_host_gate('custom/no-any', my_no_any_gate, stack='typescript')
        """
        self.registry.register(name, fn, source='host', **kwargs)

    def add_host_hook(self, hook_type, hook_fn):
        """
        Let the host add pre/post hooks around gate execution.
        hook_type: 'pre' or 'post'
        hook_fn: pre(diff, meta) or post(diff, meta, exception_or_None)
        """
        if hook_type == 'pre':
            self.registry.add_pre_hook(hook_fn)
        elif hook_type == 'post':
            self.registry.add_post_hook(hook_fn)

    # ── STATUS (show after every phase) ─────────────────────────────────────────

    def get_status(self) -> str:
        """
        Returns a structured status report after every phase.
        Shows: phase results, checkpoint summary, live eval preview.
        Call this after submit_implementation / submit_verification /
        submit_review / submit_retro — display the output to the user.
        """
        verified = check_verification()
        history = _load_eval_history()
        trend = _trend(history, self._preview_score())

        lines = [
            "",
            "=" * 60,
            f"PIPELINE #{self.run_number} STATUS",
            "=" * 60,
            f"Task: {self.task}",
            "",
            "PHASE RESULTS:",
        ]
        for phase, status in self.results.items():
            lines.append(f"  {phase.upper():10}: {status}")
        lines.append(f"  {'VERIFIED':10}: {'YES' if verified else 'NO'}")
        lines.extend(["", "CHECKPOINT:", f"  {get_summary()}"])
        lines.extend(["", "EVAL PREVIEW (based on current metrics):"])
        for dim, (score, reason) in self._preview_scores().items():
            lines.append(f"  {dim:25}: {score}/20  {reason}")
        total = self._preview_score()
        lines.extend([
            f"  {'─'*36}",
            f"  {'TOTAL (preview)':25}: {total}/100  (trend: {trend})",
            "=" * 60,
        ])
        return "\n".join(lines)

    def _preview_scores(self) -> dict:
        """Current eval_metrics scored as they would appear in final eval."""
        m = self.eval_metrics
        scores = {}

        # Gate Compliance
        v = m["gate_violations"]
        r = m["retries_used"]
        h = m["pipeline_halted"]
        if h:
            scores["Gate Compliance"] = (0, "pipeline halted")
        elif v == 0:
            scores["Gate Compliance"] = (20, "zero gate violations")
        elif v == 1 and r <= 1:
            scores["Gate Compliance"] = (15, f"1 violation, corrected on retry {r}")
        elif v <= 3 and r < MAX_RETRIES:
            scores["Gate Compliance"] = (10, f"{v} violations, {r} retries used")
        else:
            scores["Gate Compliance"] = (5, f"required max retries ({MAX_RETRIES})")

        # Verification Integrity
        if not m["output_existed"]:
            scores["Verification Integrity"] = (0, "test output missing or faked")
        elif not m["sha_passed"]:
            scores["Verification Integrity"] = (5, "SHA gate not yet run")
        elif m["sha_passed"] and m["hash_unique"] and m["had_pass_indicators"]:
            scores["Verification Integrity"] = (20, "SHA passed, unique hash, pass indicators present")
        elif m["sha_passed"] and not m["hash_unique"]:
            scores["Verification Integrity"] = (15, "SHA passed but identical hash")
        else:
            scores["Verification Integrity"] = (10, "SHA passed with caveats")

        # Process Discipline
        s, reasons = 20, []
        if not m["skills_loaded"]: s -= 10; reasons.append("skills not loaded")
        if not m["mistakes_consulted"]: s -= 5; reasons.append("mistakes not consulted")
        if not m["diff_focused"]: s -= 5; reasons.append("diff not focused")
        if m["scope_creep"]: s -= 5; reasons.append("scope creep detected")
        scores["Process Discipline"] = (max(0, s), "; ".join(reasons) if reasons else "full discipline")

        # Review Quality
        rr = m["review_result"]
        sg = m["shadow_gate_clean"]
        dm = m["drift_markers"]
        if rr == "PASS" and sg and dm == 0:
            scores["Review Quality"] = (20, "review PASS, shadow gate clean, no drift")
        elif rr == "PASS" and dm > 0:
            scores["Review Quality"] = (15, f"review PASS but {dm} drift marker(s)")
        elif rr == "SOFT_FAIL":
            scores["Review Quality"] = (15, "review SOFT_FAIL")
        elif not sg:
            scores["Review Quality"] = (10, "shadow gate found issue gate missed")
        elif rr == "HARD_FAIL":
            scores["Review Quality"] = (5, "review HARD_FAIL")
        elif rr == "SKIPPED":
            scores["Review Quality"] = (0, "review not yet run")
        else:
            scores["Review Quality"] = (10, f"review: {rr}")

        # Retro Value
        ran = m["retro_ran"]
        pq = m["retro_questions"]
        pp = m["retro_proposals"]
        if not ran:
            scores["Retro Value"] = (0, "retro not yet run")
        elif pq >= 7 and pp:
            scores["Retro Value"] = (20, "retro complete with proposals")
        elif pq >= 7:
            scores["Retro Value"] = (20, "retro complete, clean run")
        elif ran and pq < 7:
            scores["Retro Value"] = (10, f"retro ran, only {pq}/7 questions")
        else:
            scores["Retro Value"] = (10, "retro ran")

        return scores

    def _preview_score(self) -> int:
        return sum(s for s, _ in self._preview_scores().values())

    # ── FINALIZE ─────────────────────────────────────────────────────────────

    def finalize(self) -> EvalReport:
        """Produce the eval report and write the session log."""
        verified = check_verification()

        print("\n" + "=" * 60)
        print(f"PIPELINE #{self.run_number}: {self.task}")
        for phase, status in self.results.items():
            print(f"  {phase.upper():10}: {status}")
        print(f"  {'VERIFIED':10}: {'YES' if verified else 'NO — do not claim completion'}")
        print("=" * 60)
        print(f"\n{get_summary()}")

        report = evaluate_pipeline_run(
            task=self.task, pipeline_number=self.run_number, **self.eval_metrics,
        )
        print(report.format_report())

        self._write_session(report, verified)
        return report

    def _write_session(self, report: EvalReport, verified: bool) -> Path:
        session = new_session(agent_tool="host-driven")
        session.set_task(self.task)
        session.set_pipeline_result(
            pipeline_number=self.run_number,
            implement=self.results.get("implement", "PENDING"),
            verify=self.results.get("verify", "PENDING"),
            review=self.results.get("review", "PENDING"),
            sha=(self.sha[:16] + "...") if self.sha else "none",
        )
        session.set_eval(
            score=report.total, grade=report.grade, summary=report.behavior_actual,
        )
        for m in check_relevant(self.task)[:3]:
            session.add_mistake(m.get("gate", "unknown"), m.get("lesson", ""))
        if report.total < 75:
            for rec in report.recommendations:
                session.add_question(rec)
        if verified:
            session.add_handoff(f"Pipeline #{self.run_number} complete and verified. Ready for next task.")
        else:
            session.add_handoff(f"Pipeline #{self.run_number} did not complete verification. Do not claim done.")
        path = session.save()
        print(f"\n[CONDUCTOR] Session log saved -> {path}")
        return path


if __name__ == "__main__":
    print(textwrap.dedent("""
        Techne is host-driven — it does not call a model.

        Drive the pipeline from your host agent (Claude Code / Hermes / OpenCode):

            from conductor import Pipeline
            p = Pipeline.start("your task")
            p.submit_implementation(host_diff)      # retry while status == RETRY
            p.submit_verification(host_test_output)
            p.submit_review(host_findings)
            p.submit_retro(host_retro_output)
            report = p.finalize()

        See README.md for the full host-driven walkthrough.
    """).strip())
