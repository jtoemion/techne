"""
evaluator.py — scores every pipeline run across 5 dimensions.

Called by conductor.py after every pipeline completion (pass or fail).
Reads checkpoint state, mistakes log, and run log to produce a graded
evaluation report with actionable recommendations.

Scores are persisted to memory/eval_history.json for trend analysis.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

HARNESS_DIR = Path(__file__).parent
ROOT = HARNESS_DIR.parent
MEMORY_DIR = ROOT / "memory"
EVAL_HISTORY = MEMORY_DIR / "eval_history.json"

GRADES = [
    (90, "EXCELLENT"),
    (75, "GOOD"),
    (60, "FAIR"),
    (40, "POOR"),
    (0, "CRITICAL"),
]


def _grade(score: int) -> str:
    for threshold, label in GRADES:
        if score >= threshold:
            return label
    return "CRITICAL"


def _trend(history: list[dict], current_score: int) -> str:
    """Compare current score against last 5 runs."""
    if len(history) < 2:
        return "insufficient data"
    recent = [h["total"] for h in history[-5:]]
    avg = sum(recent) / len(recent)
    if current_score > avg + 5:
        return "improving"
    elif current_score < avg - 5:
        return "degrading"
    return "stable"


class EvalReport:
    """Evaluation report for a single pipeline run."""

    def __init__(self, task: str, pipeline_number: int):
        self.task = task
        self.pipeline_number = pipeline_number
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.scores: dict[str, tuple[int, str]] = {}
        self.behavior_actual = ""
        self.behavior_ideal = ""
        self.behavior_gap = ""
        self.recommendations: list[str] = []

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

    @property
    def total(self) -> int:
        return sum(s for s, _ in self.scores.values())

    @property
    def grade(self) -> str:
        return _grade(self.total)

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
            "total": self.total,
            "grade": self.grade,
            "behavior": {
                "actual": self.behavior_actual,
                "ideal": self.behavior_ideal,
                "gap": self.behavior_gap,
            },
            "recommendations": self.recommendations,
        }

    def format_report(self) -> str:
        """Format the full evaluation report as a string."""
        history = load_eval_history()
        trend = _trend(history, self.total)

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

        for dim in [
            "Gate Compliance",
            "Verification Integrity",
            "Process Discipline",
            "Review Quality",
            "Retro Value",
        ]:
            if dim in self.scores:
                s, r = self.scores[dim]
                lines.append(f"  {dim:25}: {s:2}/20  {r}")

        lines.extend([
            "",
            f"TOTAL: {self.total}/100 — {self.grade}",
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

        lines.extend([
            "",
            f"TREND: {trend}",
            "=" * 64,
        ])

        return "\n".join(lines)


# ─── Persistence ──────────────────────────────────────────────────────────────

def load_eval_history() -> list[dict]:
    if not EVAL_HISTORY.exists():
        return []
    try:
        return json.loads(EVAL_HISTORY.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return []


def save_eval(report: EvalReport) -> None:
    """Append report to eval history and write the text report to memory/."""
    history = load_eval_history()
    history.append(report.to_dict())
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    EVAL_HISTORY.write_text(json.dumps(history, indent=2), encoding="utf-8")

    # Also write the latest report as readable text
    report_path = MEMORY_DIR / "latest_eval.txt"
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
) -> EvalReport:
    """
    Evaluate a pipeline run. Called by conductor.py after every completion.
    Returns the EvalReport with all scores and formatted output.
    """
    report = EvalReport(task, pipeline_number)

    report.score_gate_compliance(gate_violations, retries_used, max_retries, pipeline_halted)
    report.score_verification(sha_passed, hash_unique, output_existed, had_pass_indicators)
    report.score_process_discipline(skills_loaded, mistakes_consulted, diff_focused, scope_creep)
    report.score_review(review_result, shadow_gate_clean, drift_markers)
    report.score_retro(retro_ran, retro_proposals, retro_questions)

    # Generate behavior analysis based on scores
    total = report.total
    if total >= 90:
        report.set_behavior_analysis(
            "Agent followed all skill rules, produced focused diff, passed all gates on first try.",
            "Exactly this — maintain current discipline.",
            "No significant gap.",
        )
    elif total >= 75:
        weak = min(report.scores.items(), key=lambda x: x[1][0])
        report.set_behavior_analysis(
            f"Agent mostly followed process. Weakest area: {weak[0]} ({weak[1][0]}/20).",
            "All dimensions at 15+ would indicate consistent discipline.",
            f"Focus on {weak[0]}: {weak[1][1]}.",
        )
        report.add_recommendation(f"Investigate {weak[0]}: {weak[1][1]}")
    elif total >= 60:
        weak_dims = [(k, s, r) for k, (s, r) in report.scores.items() if s < 15]
        report.set_behavior_analysis(
            f"Agent had issues in {len(weak_dims)} area(s): {', '.join(k for k,_,_ in weak_dims)}.",
            "Each dimension should score 12+ for acceptable pipeline quality.",
            f"Multiple dimensions below threshold — tighten skill enforcement.",
        )
        for k, s, r in weak_dims:
            report.add_recommendation(f"Fix {k} ({s}/20): {r}")
    else:
        report.set_behavior_analysis(
            "Significant process failures — agent drifted from skill rules.",
            "Agent must read skills before acting and follow gate feedback on retry.",
            "Fundamental discipline gap — review agent prompts and gate coverage.",
        )
        report.add_recommendation("Review all agent .md files for clarity of constraints")
        report.add_recommendation("Add missing gates for any ungated skill rules")
        report.add_recommendation("Check if skills are being loaded into agent context")

    save_eval(report)
    return report
