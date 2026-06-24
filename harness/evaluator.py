"""
evaluator.py — scores every pipeline run across 8 dimensions.

Called by orchestrator_loop after every pipeline completion (pass or fail).
Reads checkpoint state, mistakes log, and run log to produce a graded
evaluation report with actionable recommendations.

Scores are persisted to .techne/memory/eval_history.json for trend analysis.

8 dimensions (120pt raw, weighted to 100pt scale for grades):
  - Gate Compliance (20 raw, weight 1.2)
  - Verification Integrity (20 raw, weight 1.2)
  - Process Discipline (20 raw, weight 1.0)
  - Review Quality (20 raw, weight 1.0)
  - Retro Value (20 raw, weight 0.8)
  - RL/GRPO Contribution (15 raw, weight 0.8)
  - Enforcement Compliance (15 raw, weight 1.0)
  - Execution Efficiency (10 raw, weight 0.6)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from store import read_json, write_json

HARNESS_DIR = Path(__file__).parent
ROOT = HARNESS_DIR.parent
MEMORY_DIR = ROOT / ".techne" / "memory"
REPORTS_DIR = ROOT / ".techne" / "reports"
EVAL_DIR = REPORTS_DIR / "eval"
EVAL_HISTORY = EVAL_DIR / "eval_history.json"

# Raw max points per dimension
RAW_MAX = {
    "Gate Compliance": 20,
    "Verification Integrity": 20,
    "Process Discipline": 20,
    "Review Quality": 20,
    "Retro Value": 20,
    "RL/GRPO Contribution": 15,
    "Enforcement Compliance": 15,
    "Execution Efficiency": 10,
}
RAW_TOTAL_MAX = sum(RAW_MAX.values())  # 120

# Default weights (can be overridden per-run)
DEFAULT_WEIGHTS: dict[str, float] = {
    "Gate Compliance": 1.2,
    "Verification Integrity": 1.2,
    "Process Discipline": 1.0,
    "Review Quality": 1.0,
    "Retro Value": 0.8,
    "RL/GRPO Contribution": 0.8,
    "Enforcement Compliance": 1.0,
    "Execution Efficiency": 0.6,
}

GRADES = [
    (90, "EXCELLENT"),
    (75, "GOOD"),
    (60, "FAIR"),
    (40, "POOR"),
    (0, "CRITICAL"),
]


def _grade(score: float) -> str:
    for threshold, label in GRADES:
        if score >= threshold:
            return label
    return "CRITICAL"


def _trend(history: list[dict], current_score: int) -> str:
    """Compare current score against last 5 runs (backward-compatible string API)."""
    if len(history) < 2:
        return "insufficient data"
    recent = [h["total"] for h in history[-5:]]
    avg = sum(recent) / len(recent)
    if current_score > avg + 5:
        return "improving"
    elif current_score < avg - 5:
        return "degrading"
    return "stable"


def _detect_regression(history: list[dict], current_score: float) -> dict:
    """
    Compare last N eval scores against N previous runs.
    Returns dict with severity ('none'|'warning'|'critical') and detail string.
    """
    if len(history) < 4:
        return {"severity": "none", "detail": "insufficient history for regression analysis"}

    n = min(5, len(history) // 2)
    if n < 2:
        return {"severity": "none", "detail": "insufficient history for regression analysis"}

    # Current window: last n runs (most recent first in history)
    current_window = [h["total"] for h in history[-n:]]
    # Previous window: n runs before that
    previous_window = [h["total"] for h in history[-n * 2 : -n]]

    current_avg = sum(current_window) / len(current_window)
    previous_avg = sum(previous_window) / len(previous_window)

    if previous_avg == 0:
        return {"severity": "none", "detail": "previous average is zero — cannot compute regression"}

    pct_change = ((current_avg - previous_avg) / previous_avg) * 100

    if pct_change < -25:
        return {
            "severity": "critical",
            "detail": f"score dropped {abs(pct_change):.1f}% below rolling average ({current_avg:.1f} vs {previous_avg:.1f})",
        }
    elif pct_change < -10:
        return {
            "severity": "warning",
            "detail": f"score dropped {abs(pct_change):.1f}% below rolling average ({current_avg:.1f} vs {previous_avg:.1f})",
        }
    elif pct_change > 10:
        return {
            "severity": "none",
            "detail": f"score improving — {pct_change:.1f}% above rolling average ({current_avg:.1f} vs {previous_avg:.1f})",
        }
    else:
        return {
            "severity": "none",
            "detail": f"stable — within 10% of rolling average ({current_avg:.1f} vs {previous_avg:.1f})",
        }


@dataclass
class RegressionInfo:
    severity: Literal["none", "warning", "critical"] = "none"
    detail: str = ""


class EvalReport:
    """Evaluation report for a single pipeline run."""

    def __init__(self, task: str, pipeline_number: int, weights: dict[str, float] | None = None):
        self.task = task
        self.pipeline_number = pipeline_number
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.scores: dict[str, tuple[int, str]] = {}
        self.behavior_actual = ""
        self.behavior_ideal = ""
        self.behavior_gap = ""
        self.recommendations: list[str] = []
        self.weights = weights if weights is not None else DEFAULT_WEIGHTS.copy()
        self.skill_scores: dict[str, float] | None = None
        self.regression: RegressionInfo = RegressionInfo()

    def score_gate_compliance(
        self,
        violations: int,
        retries_used: int,
        max_retries: int,
        pipeline_halted: bool,
    ) -> int:
        if pipeline_halted:
            s, r = 0, "pipeline halted — violations not correctable"
        elif violations == 0:
            s, r = 20, "zero gate violations"
        elif violations == 1 and retries_used <= 1:
            s, r = 15, f"1 violation, corrected on retry {retries_used}"
        elif violations <= 3 and retries_used < max_retries:
            s, r = 10, f"{violations} violations, {retries_used} retries used"
        elif retries_used >= max_retries:
            s, r = 5, f"required max retries ({max_retries})"
        else:
            s, r = 10, f"{violations} violations corrected"
        self.scores["Gate Compliance"] = (s, r)
        return s

    def score_verification(
        self,
        sha_passed: bool,
        hash_unique: bool,
        output_existed: bool,
        had_pass_indicators: bool,
    ) -> int:
        if not output_existed:
            s, r = 0, "test output missing or faked"
        elif not sha_passed:
            s, r = 5, "SHA gate failed"
        elif sha_passed and hash_unique and had_pass_indicators:
            s, r = 20, "SHA passed, unique hash, pass indicators present"
        elif sha_passed and not hash_unique:
            s, r = 15, "SHA passed but identical hash — possible cached output"
        else:
            s, r = 10, "SHA passed with caveats"
        self.scores["Verification Integrity"] = (s, r)
        return s

    def score_process_discipline(
        self,
        skills_loaded: bool,
        mistakes_consulted: bool,
        diff_focused: bool,
        scope_creep: bool,
    ) -> int:
        s = 20
        reasons = []
        if not skills_loaded:
            s -= 10
            reasons.append("skills not loaded")
        if not mistakes_consulted:
            s -= 5
            reasons.append("mistakes.md not consulted")
        if not diff_focused:
            s -= 5
            reasons.append("diff not minimal")
        if scope_creep:
            s -= 5
            reasons.append("scope creep detected")
        r = "; ".join(reasons) if reasons else "full discipline followed"
        s = max(0, s)
        self.scores["Process Discipline"] = (s, r)
        return s

    def score_review(
        self,
        review_result: str,
        shadow_gate_clean: bool,
        drift_markers: int,
    ) -> int:
        if review_result == "PASS" and shadow_gate_clean and drift_markers == 0:
            s, r = 20, "review PASS, shadow gate clean, no drift markers"
        elif review_result == "PASS" and drift_markers > 0:
            s, r = 15, f"review PASS but {drift_markers} drift marker(s)"
        elif review_result == "SOFT_FAIL":
            s, r = 15, "review SOFT_FAIL — warnings only"
        elif not shadow_gate_clean:
            s, r = 10, "shadow gate found issue gate missed"
        elif review_result == "HARD_FAIL":
            s, r = 5, "review HARD_FAIL — rework required"
        elif review_result == "SKIPPED":
            s, r = 0, "review skipped"
        else:
            s, r = 10, f"review: {review_result}"
        self.scores["Review Quality"] = (s, r)
        return s

    def score_retro(
        self,
        retro_ran: bool,
        produced_proposals: bool,
        questions_answered: int,
    ) -> int:
        if not retro_ran:
            s, r = 0, "retro skipped"
        elif questions_answered >= 7 and produced_proposals:
            s, r = 20, "retro complete with actionable proposals"
        elif questions_answered >= 7:
            s, r = 20, "retro complete, clean run — no proposals needed"
        elif retro_ran and questions_answered < 7:
            s, r = 10, f"retro ran, only {questions_answered}/7 questions answered"
        elif retro_ran:
            s, r = 10, "retro ran, stable run"
        else:
            s, r = 5, "retro incomplete"
        self.scores["Retro Value"] = (s, r)
        return s

    # ─── New dimensions ───────────────────────────────────────────────────────

    def score_rl_grpo(
        self,
        rewards_total: int = 0,
        proposals_count: int = 0,
        advantages_computed: int = 0,
        framework_edited: bool = False,
    ) -> int:
        """
        RL/GRPO Contribution (15pts max).
        Reward signal quality, proposal rate, framework edits.
        """
        s = 0
        reasons = []

        # Reward signals (up to 7pts)
        if rewards_total > 0:
            if rewards_total >= 200:
                s += 7
                reasons.append(f"strong reward signal ({rewards_total})")
            elif rewards_total >= 100:
                s += 5
                reasons.append(f"reward signal active ({rewards_total})")
            elif rewards_total >= 50:
                s += 3
                reasons.append(f"reward signal present ({rewards_total})")
            else:
                s += 1
                reasons.append(f"weak reward signal ({rewards_total})")

        # Proposals generated (up to 5pts)
        if proposals_count > 0:
            if proposals_count >= 10:
                s += 5
                reasons.append(f"{proposals_count} RL proposals (high volume)")
            elif proposals_count >= 5:
                s += 4
                reasons.append(f"{proposals_count} RL proposals")
            elif proposals_count >= 2:
                s += 3
                reasons.append(f"{proposals_count} RL proposals")
            else:
                s += 1
                reasons.append(f"{proposals_count} RL proposal(s)")

        # Advantages computed (up to 2pts)
        if advantages_computed > 0:
            s += 2
            reasons.append(f"{advantages_computed} advantage computations")

        # Framework edits (1pt)
        if framework_edited:
            s += 1
            reasons.append("framework edited based on RL feedback")

        # Clamp to max
        s = min(15, s)

        # Neutral default when no data
        if not reasons:
            s, r = 8, "no RL/GRPO data provided — neutral score"
        else:
            r = "; ".join(reasons)

        self.scores["RL/GRPO Contribution"] = (s, r)
        return s

    def score_enforcement(
        self,
        blocks_encountered: int = 0,
        audit_chain_intact: bool = True,
        watchdog_healthy: bool = True,
    ) -> int:
        """
        Enforcement Compliance (15pts max).
        Phase guard blocks avoided, audit chain integrity, watchdog health.
        """
        if blocks_encountered == 0 and audit_chain_intact and watchdog_healthy:
            s, r = 15, "zero blocks, audit chain intact, watchdog healthy"
        elif blocks_encountered == 0 and (not audit_chain_intact or not watchdog_healthy):
            s, r = 10, "no blocks but audit or watchdog issue"
        elif blocks_encountered <= 2 and audit_chain_intact and watchdog_healthy:
            s, r = 12, f"{blocks_encountered} block(s) encountered, audit/watchdog OK"
        elif blocks_encountered <= 2:
            s, r = 8, f"{blocks_encountered} block(s), audit or watchdog issue"
        elif blocks_encountered <= 5:
            s, r = 5, f"{blocks_encountered} blocks — enforcement pressure detected"
        else:
            s, r = 2, f"{blocks_encountered} blocks — severe enforcement failure"
        self.scores["Enforcement Compliance"] = (s, r)
        return s

    def score_execution(
        self,
        tool_count: int = 50,
        retries: int = 0,
        elapsed_seconds: float = 60.0,
    ) -> int:
        """
        Execution Efficiency (10pts max).
        Tool count vs retries, phase time, resource usage.
        """
        # Ideal: tool_count ~50, retries ~0, elapsed ~60s
        s = 10
        reasons = []

        # Tool efficiency
        if tool_count > 100:
            s -= 4
            reasons.append(f"high tool count ({tool_count})")
        elif tool_count > 75:
            s -= 2
            reasons.append(f"elevated tool count ({tool_count})")
        elif tool_count < 20:
            s -= 1
            reasons.append(f"low tool count ({tool_count})")

        # Retry penalty
        if retries > 5:
            s -= 3
            reasons.append(f"{retries} retries")
        elif retries > 2:
            s -= 1
            reasons.append(f"{retries} retries")

        # Time efficiency (relative to 60s baseline)
        if elapsed_seconds > 300:  # 5 min
            s -= 2
            reasons.append(f"slow execution ({elapsed_seconds:.0f}s)")
        elif elapsed_seconds > 180:
            s -= 1
            reasons.append(f"elevated time ({elapsed_seconds:.0f}s)")

        s = max(0, s)
        r = "; ".join(reasons) if reasons else "efficient execution"
        self.scores["Execution Efficiency"] = (s, r)
        return s

    # ─── Scoring aggregation ─────────────────────────────────────────────────

    @property
    def raw_total(self) -> int:
        """Unweighted sum of all scored dimensions (all 8 possible)."""
        total = 0
        for dim in RAW_MAX:
            if dim in self.scores:
                total += self.scores[dim][0]
        return total

    @property
    def total(self) -> int:
        """
        Unweighted total — raw sum of scores.
        This is the backward-compatible field used by existing callers.
        With 5 original dimensions: max = 100.
        With all 8 dimensions scored: max = 120.
        """
        return self.raw_total

    @property
    def weighted_total(self) -> int:
        """
        Weighted total normalized to 100pt scale.
        Each dimension contributes (score/max) * weight to the average.
        Only dimensions that have been explicitly scored are included.
        """
        scored = [(dim, self.scores[dim]) for dim in self.scores]
        if not scored:
            return 0
        weighted = 0.0
        weight_sum = 0.0
        for dim, (score, _) in scored:
            w = self.weights.get(dim, 1.0)
            max_raw = RAW_MAX.get(dim, score)
            # Weight-adjusted contribution (proportional to max)
            weighted += (score / max_raw) * w
            weight_sum += w
        if weight_sum == 0:
            return 0
        return int(round((weighted / weight_sum) * 100))

    @property
    def weighted_score(self) -> int:
        """Alias for weighted_total."""
        return self.weighted_total

    @property
    def grade(self) -> str:
        return _grade(self.total)

    def score_for_gate(self) -> Literal["PASS", "WARN", "BLOCK"]:
        """
        Threshold gating decision based on weighted total.
        - PASS: total >= 85
        - WARN: total >= 60
        - BLOCK: total < 60
        """
        t = self.total
        if t >= 85:
            return "PASS"
        elif t >= 60:
            return "WARN"
        return "BLOCK"

    def set_behavior_analysis(self, actual: str, ideal: str, gap: str):
        self.behavior_actual = actual
        self.behavior_ideal = ideal
        self.behavior_gap = gap

    def add_recommendation(self, rec: str):
        self.recommendations.append(rec)

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "pipeline_number": self.pipeline_number,
            "timestamp": self.timestamp,
            "scores": {k: {"score": s, "reason": r} for k, (s, r) in self.scores.items()},
            "raw_total": self.raw_total,
            "total": self.total,
            "weighted_total": self.weighted_total,
            "grade": self.grade,
            "behavior": {
                "actual": self.behavior_actual,
                "ideal": self.behavior_ideal,
                "gap": self.behavior_gap,
            },
            "recommendations": self.recommendations,
            "skill_scores": self.skill_scores,
            "regression": {"severity": self.regression.severity, "detail": self.regression.detail},
        }

    def format_report(self) -> str:
        """Format the full evaluation report as a string."""
        history = load_eval_history()
        regression_info = _detect_regression(history, self.total)

        # Determine gate emoji
        gate = self.score_for_gate()
        gate_icon = {"PASS": "✅", "WARN": "⚠️", "BLOCK": "🔴"}.get(gate, "?")

        lines = [
            "",
            "=" * 64,
            f"EVALUATION REPORT — Pipeline #{self.pipeline_number}",
            "=" * 64,
            f"Task: {self.task}",
            f"Date: {self.timestamp}",
            "",
            "SCORES:",
        ]

        # Original 5 dimensions with /20
        for dim in [
            "Gate Compliance",
            "Verification Integrity",
            "Process Discipline",
            "Review Quality",
            "Retro Value",
        ]:
            if dim in self.scores:
                s, r = self.scores[dim]
                w_marker = " *" if self.weights.get(dim, 1.0) != 1.0 else ""
                lines.append(f"  {dim:25}: {s:2}/20  {r}{w_marker}")

        # New 3 dimensions with their own max
        new_dims = {
            "RL/GRPO Contribution": 15,
            "Enforcement Compliance": 15,
            "Execution Efficiency": 10,
        }
        for dim, max_pts in new_dims.items():
            if dim in self.scores:
                s, r = self.scores[dim]
                w_marker = " *" if self.weights.get(dim, 1.0) != 1.0 else ""
                lines.append(f"  {dim:25}: {s:2}/{max_pts}  {r}{w_marker}")

        # Determine which totals to show
        has_new_dims = any(d in self.scores for d in ("RL/GRPO Contribution", "Enforcement Compliance", "Execution Efficiency"))
        if has_new_dims:
            lines.extend([
                "",
                f"RAW TOTAL: {self.raw_total}/{RAW_TOTAL_MAX}",
                f"WEIGHTED TOTAL: {self.weighted_total}/100 — {self.grade}  {gate_icon} {gate}",
            ])
        else:
            # Backward-compatible: show simple total/grade
            lines.extend([
                "",
                f"TOTAL: {self.total}/100 — {self.grade}",
            ])
        # Behavior analysis (shared by both paths)
        lines.extend([
            "",
            "AGENT BEHAVIOR ANALYSIS:",
            f"  What happened:  {self.behavior_actual}",
            f"  What should be: {self.behavior_ideal}",
            f"  Gap:            {self.behavior_gap}",
            "",
            "RECOMMENDATIONS:",
        ])

        for i, rec in enumerate(self.recommendations, 1):
            lines.append(f"  {i}. {rec}")

        if not self.recommendations:
            lines.append("  (none — clean run)")

        # Regression status
        sev = regression_info["severity"]
        sev_icon = {"none": "➡️", "warning": "⚠️", "critical": "🔴"}.get(sev, "?")
        # Backward-compatible trend string
        trend_str = _trend(history, self.total)
        lines.extend([
            "",
            f"REGRESSION: {sev_icon} {sev.upper()} — {regression_info['detail']}",
            f"GATE DECISION: {gate_icon} {gate}",
            f"TREND: {trend_str}",
            "=" * 64,
        ])

        # Per-skill breakdown
        if self.skill_scores:
            lines.append("")
            lines.append("PER-SKILL BREAKDOWN:")
            for skill, score in self.skill_scores.items():
                pct = score * 100
                lines.append(f"  {skill:30}: {pct:5.1f}%")
            lines.append("=" * 64)

        return "\n".join(lines)


# ─── Persistence ──────────────────────────────────────────────────────────────

def load_eval_history() -> list[dict]:
    return read_json(EVAL_HISTORY, default=[])


def save_eval(report: EvalReport) -> None:
    """Append report to eval history and write the text report to memory/."""
    history = load_eval_history()
    history.append(report.to_dict())
    write_json(EVAL_HISTORY, history)

    # Also write the latest report as readable text (domain artifact, not JSON)
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    report_path = EVAL_DIR / "latest_eval.txt"
    report_path.write_text(report.format_report(), encoding="utf-8")


def evaluate_pipeline_run(
    task: str,
    pipeline_number: int,
    gate_violations: int = 0,
    retries_used: int = 0,
    max_retries: int = 3,
    pipeline_halted: bool = False,
    sha_passed: bool = False,
    hash_unique: bool = True,
    output_existed: bool = True,
    had_pass_indicators: bool = True,
    skills_loaded: bool = True,
    mistakes_consulted: bool = True,
    diff_focused: bool = True,
    scope_creep: bool = False,
    review_result: str = "PASS",
    shadow_gate_clean: bool = True,
    drift_markers: int = 0,
    retro_ran: bool = True,
    retro_proposals: bool = False,
    retro_questions: int = 7,
    # ─── New parameters (backward-compatible: all have defaults) ─────────────
    rl_rewards_total: int = 0,
    rl_proposals: int = 0,
    rl_advantages_computed: int = 0,
    rl_framework_edited: bool = False,
    enforcement_blocks: int | None = None,
    audit_chain_intact: bool | None = None,
    watchdog_ok: bool | None = None,
    execution_tool_count: int = 50,
    execution_retries: int = 0,
    execution_time_seconds: float = 60.0,
    skill_scores: dict[str, float] | None = None,
) -> EvalReport:
    """
    Evaluate a pipeline run. Called by orchestrator_loop after every completion.
    Returns the EvalReport with all scores and formatted output.

    New parameters (all optional for backward compat):
      rl_rewards_total: Total reward signal accumulated (RL loop indicator)
      rl_proposals: Number of RL/GRPO proposals generated
      enforcement_blocks: Number of phase_guard blocks encountered
      audit_chain_intact: Whether the audit chain is unbroken
      execution_tool_count: Number of tools executed in the run
      execution_retries: Number of retries used during execution
      execution_time_seconds: Total wall-clock time for the run
      skill_scores: Optional dict of skill_name -> score (0.0-1.0)
    """
    report = EvalReport(task, pipeline_number)

    # Original 5 dimensions
    report.score_gate_compliance(gate_violations, retries_used, max_retries, pipeline_halted)
    report.score_verification(sha_passed, hash_unique, output_existed, had_pass_indicators)
    report.score_process_discipline(skills_loaded, mistakes_consulted, diff_focused, scope_creep)
    report.score_review(review_result, shadow_gate_clean, drift_markers)
    report.score_retro(retro_ran, retro_proposals, retro_questions)

    # New 3 dimensions — only score when meaningful RL/enforcement/execution data provided
    has_rl_data = rl_rewards_total > 0 or rl_proposals > 0 or rl_advantages_computed > 0 or rl_framework_edited
    has_enforcement_data = (
        enforcement_blocks is not None
        or audit_chain_intact is not None
        or watchdog_ok is not None
    )
    has_execution_data = (
        execution_tool_count != 50
        or execution_retries > 0
        or execution_time_seconds != 60.0
    )
    if has_rl_data:
        report.score_rl_grpo(
            rewards_total=rl_rewards_total,
            proposals_count=rl_proposals,
            advantages_computed=rl_advantages_computed,
            framework_edited=rl_framework_edited,
        )
    if has_enforcement_data:
        report.score_enforcement(
            blocks_encountered=enforcement_blocks if enforcement_blocks is not None else 0,
            audit_chain_intact=audit_chain_intact if audit_chain_intact is not None else True,
            watchdog_healthy=watchdog_ok if watchdog_ok is not None else True,
        )
    if has_execution_data:
        report.score_execution(
            tool_count=execution_tool_count,
            retries=execution_retries,
            elapsed_seconds=execution_time_seconds,
        )

    # Per-skill scores
    if skill_scores is not None:
        report.skill_scores = skill_scores

    # Generate behavior analysis based on scores
    total = report.total
    if total >= 90:
        report.set_behavior_analysis(
            "Agent followed all skill rules, produced focused diff, passed all gates on first try.",
            "Exactly this — maintain current discipline.",
            "No significant gap.",
        )
    elif total >= 75:
        weak = min(report.scores.items(), key=lambda x: x[1][0] / RAW_MAX.get(x[0], 20))
        report.set_behavior_analysis(
            f"Agent mostly followed process. Weakest area: {weak[0]} ({weak[1][0]}/{RAW_MAX.get(weak[0], 20)}).",
            "All dimensions at 15+ would indicate consistent discipline.",
            f"Focus on {weak[0]}: {weak[1][1]}.",
        )
        report.add_recommendation(f"Investigate {weak[0]}: {weak[1][1]}")
    elif total >= 60:
        weak_dims = [(k, s, r) for k, (s, r) in report.scores.items() if s < RAW_MAX.get(k, 20) * 0.6]
        report.set_behavior_analysis(
            f"Agent had issues in {len(weak_dims)} area(s): {', '.join(k for k, _, _ in weak_dims)}.",
            "Each dimension should score 60%+ for acceptable pipeline quality.",
            f"Multiple dimensions below threshold — tighten skill enforcement.",
        )
        for k, s, r in weak_dims:
            max_s = RAW_MAX.get(k, 20)
            report.add_recommendation(f"Fix {k} ({s}/{max_s}): {r}")
    else:
        report.set_behavior_analysis(
            "Significant process failures — agent drifted from skill rules.",
            "Agent must read skills before acting and follow gate feedback on retry.",
            "Fundamental discipline gap — review agent prompts and gate coverage.",
        )
        report.add_recommendation("Review all agent .md files for clarity of constraints")
        report.add_recommendation("Add missing gates for any ungated skill rules")
        report.add_recommendation("Check if skills are being loaded into agent context")

    # Compute regression
    history = load_eval_history()
    reg_info = _detect_regression(history, total)
    report.regression = RegressionInfo(severity=reg_info["severity"], detail=reg_info["detail"])

    save_eval(report)
    return report
