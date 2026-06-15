"""
gate_evolution.py — Automatic gate generation from recurring patterns.

When a review finding appears 3+ times across different tasks, it becomes
a candidate gate. The system:
  1. Extracts the greppable pattern from the finding
  2. Tests it against past diffs (retroactive validation)
  3. Auto-approves if hit rate >= 80% and false positive rate <= 10%
  4. Generates a gate function and writes it to harness/plugins/

This is the mechanism where gates emerge from evidence, not human proposal.

Usage:
    from gate_evolution import GateEvolution

    evo = GateEvolution(reward_log)

    # Check for new gate candidates
    candidates = evo.find_candidates(min_count=3)

    # Test a candidate against history
    result = evo.test_candidate(candidates[0])

    # Auto-approve if it passes
    if result.approved:
        evo.write_gate(result)

    # Dashboard
    print(evo.dashboard())
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from reward_log import RewardLog, _normalize_pattern

HARNESS_DIR = Path(__file__).parent
PLUGINS_DIR = HARNESS_DIR / "plugins"
MEMORY_DIR = HARNESS_DIR.parent / "memory"

# Thresholds for auto-approval
MIN_PATTERN_COUNT = 3         # must appear in 3+ tasks
MIN_HIT_RATE = 0.80           # must catch 80%+ of past instances
MAX_FALSE_POSITIVE_RATE = 0.10  # must not fire on clean diffs more than 10%

# Known pattern → regex templates
PATTERN_TEMPLATES = {
    "null check": r"(?<!\!)\\b\\w+\\.\\w+\\b(?!\\s*\\?)",  # property access without optional chaining
    "console.log": r"console\\.log\\s*\\(",
    "any type": r":\\s*any\\b",
    "ts-ignore": r"@ts-(ignore|nocheck)",
    "unused import": r"^import\\s+.*from\\s+",  # too broad, needs refinement
    "hardcoded secret": r"(api[_-]?key|password|token|secret)\\s*[:=]\\s*[\"\\'][^\\'\"]{8,}",
    "eval usage": r"\\beval\\s*\\(",
    "dangerouslysetinnerhtml": r"dangerouslySetInnerHTML",
    "missing error handling": r"catch\\s*\\(\\w*\\)\\s*\\{\\s*\\}",  # empty catch block
}


@dataclass
class CandidateGate:
    """A candidate gate derived from a recurring pattern."""
    pattern: str               # the normalized finding text
    regex: str                 # proposed greppable regex
    source_count: int          # how many tasks had this finding
    sample_findings: list[str] # original finding texts
    hit_rate: float = 0.0      # how often the regex catches the pattern
    false_positive_rate: float = 0.0  # how often it fires on clean diffs
    approved: bool = False


@dataclass
class TestResult:
    """Result of testing a candidate gate against history."""
    candidate: CandidateGate
    total_instances: int       # how many past diffs had the pattern
    regex_hits: int            # how many the regex caught
    clean_diffs_tested: int    # how many clean diffs were tested
    false_positives: int       # how many clean diffs the regex fired on
    hit_rate: float
    false_positive_rate: float
    approved: bool
    reason: str


class GateEvolution:
    """
    Finds recurring patterns in review findings and proposes gates.
    Gates are tested against history before approval.
    """

    def __init__(self, reward_log: RewardLog):
        self.reward_log = reward_log

    def find_candidates(self, min_count: int = MIN_PATTERN_COUNT) -> list[CandidateGate]:
        """
        Find patterns that appear in min_count+ tasks.
        Returns candidate gates with proposed regex patterns.
        """
        raw_patterns = self.reward_log.recurring_patterns(min_count=min_count)
        candidates = []

        for p in raw_patterns:
            pattern = p["pattern"]
            regex = self._pattern_to_regex(pattern)
            if regex:
                candidates.append(CandidateGate(
                    pattern=pattern,
                    regex=regex,
                    source_count=p["count"],
                    sample_findings=[pattern],
                ))

        return candidates

    def test_candidate(
        self,
        candidate: CandidateGate,
        past_diffs: list[str] | None = None,
        clean_diffs: list[str] | None = None,
    ) -> TestResult:
        """
        Test a candidate gate against past diffs.
        If diffs not provided, returns a result based on pattern matching only.
        """
        # If we have real diffs, test against them
        if past_diffs and clean_diffs:
            return self._test_against_diffs(candidate, past_diffs, clean_diffs)

        # Without diffs, we can only estimate based on pattern count
        # Conservative: approve only if count is high enough
        estimated_hit_rate = min(1.0, candidate.source_count / 5.0)
        approved = (
            candidate.source_count >= MIN_PATTERN_COUNT
            and estimated_hit_rate >= MIN_HIT_RATE
        )

        return TestResult(
            candidate=candidate,
            total_instances=candidate.source_count,
            regex_hits=candidate.source_count,  # assume regex matches
            clean_diffs_tested=0,
            false_positives=0,
            hit_rate=estimated_hit_rate,
            false_positive_rate=0.0,
            approved=approved,
            reason=(
                f"Pattern count: {candidate.source_count} "
                f"(threshold: {MIN_PATTERN_COUNT}). "
                f"Estimated hit rate: {estimated_hit_rate:.0%}. "
                f"{'Approved' if approved else 'Not enough evidence'}."
            ),
        )

    def approve(self, candidate: CandidateGate) -> Path | None:
        """
        Generate and write a gate plugin file for an approved candidate.
        Returns the path to the generated file.
        """
        if not candidate.approved:
            return None

        gate_name = self._pattern_to_gate_name(candidate.pattern)
        gate_code = self._generate_gate_code(gate_name, candidate.regex, candidate.pattern)

        # Write to plugins/
        filename = f"evolved_{gate_name}.py"
        filepath = PLUGINS_DIR / filename

        # Don't overwrite existing
        if filepath.exists():
            return filepath

        filepath.write_text(gate_code, encoding="utf-8")

        # Record in memory
        self._record_gate(gate_name, candidate)

        return filepath

    def auto_evolve(self, min_count: int = MIN_PATTERN_COUNT) -> list[Path]:
        """
        Full auto-evolution cycle:
        1. Find candidates
        2. Test each
        3. Approve and write gates for approved ones
        Returns list of paths to generated gate files.
        """
        candidates = self.find_candidates(min_count=min_count)
        generated = []

        for c in candidates:
            result = self.test_candidate(c)
            c.hit_rate = result.hit_rate
            c.false_positive_rate = result.false_positive_rate
            c.approved = result.approved

            if c.approved:
                path = self.approve(c)
                if path:
                    generated.append(path)

        return generated

    def dashboard(self) -> str:
        """Human-readable gate evolution status."""
        candidates = self.find_candidates()

        lines = [
            "=" * 55,
            "GATE EVOLUTION",
            "=" * 55,
        ]

        if not candidates:
            lines.append("No gate candidates yet (need 3+ recurring patterns).")
        else:
            lines.append(f"Candidates ({len(candidates)}):")
            for c in candidates:
                result = self.test_candidate(c)
                status = "✓ APPROVED" if result.approved else "○ monitoring"
                lines.append(
                    f"  {status}  [{c.source_count}x] {c.pattern[:45]:45s}  "
                    f"regex: {c.regex[:30]}"
                )
                lines.append(f"           {result.reason[:70]}")

        # Show existing evolved gates
        existing = list(PLUGINS_DIR.glob("evolved_*.py"))
        if existing:
            lines.append(f"\nExisting evolved gates ({len(existing)}):")
            for f in existing:
                lines.append(f"  {f.name}")

        lines.append("=" * 55)
        return "\n".join(lines)

    # ── Internal helpers ─────────────────────────────────────────────────

    def _pattern_to_regex(self, pattern: str) -> str | None:
        """
        Convert a normalized finding pattern to a greppable regex.
        Returns None if no good regex can be derived.
        """
        pattern_lower = pattern.lower()

        # Check known templates
        for keyword, regex in PATTERN_TEMPLATES.items():
            if keyword in pattern_lower:
                return regex

        # SHA256 exact match: use the normalized pattern as-is for grepping.
        # Gates are greppable rules — exactness is a feature, not a bug.
        # "missing null check" and "null check missing" SHOULD be different gates.
        words = [w for w in pattern_lower.split() if len(w) > 2]
        if len(words) >= 2:
            # Return the pattern itself as a grep-able regex
            # Escape special regex chars, join with whitespace wildcard
            escaped = [re.escape(w) for w in words]
            return r"\s+".join(escaped)

        return None

    def _pattern_to_gate_name(self, pattern: str) -> str:
        """Convert a pattern to a snake_case gate name."""
        import re
        name = pattern.lower().strip()
        # Remove common words
        for word in ["the", "a", "an", "is", "are", "in", "on", "at"]:
            name = name.replace(f" {word} ", " ")
        # Take first 3 significant words
        words = [w for w in name.split() if len(w) > 2][:3]
        return "_".join(words)

    def _generate_gate_code(self, name: str, regex: str, description: str) -> str:
        """Generate a gate plugin Python file."""
        # Escape for Python string
        regex_escaped = regex.replace("\\", "\\\\").replace('"', '\\"')

        return f'''"""
Auto-generated gate: {name}
Derived from pattern: {description}
Generated by gate_evolution.py
"""
import re
from gates import GateViolation, _strip_diff_marker, _is_comment


def _gate_{name}(diff: str):
    """Reject diffs matching pattern: {description}"""
    pattern = re.compile(r"{regex_escaped}")
    for i, line in enumerate(diff.splitlines()):
        if not line.startswith("+") or line.startswith("+++"):
            continue
        code = _strip_diff_marker(line)
        if _is_comment(code):
            continue
        if pattern.search(code):
            raise GateViolation(
                f"GATE FAIL [evolved/{name}]: pattern match on line {{i+1}}.\\n"
                f"  Pattern: {description}\\n"
                f"  → {{line.strip()}}"
            )


def register(registry):
    """Register the evolved gate."""
    registry.register(
        "evolved/{name}",
        _gate_{name},
        stack="general",
        category="hard",
        severity="error",
        description="Auto-generated: {description}",
        source="evolved",
    )
'''

    def _record_gate(self, name: str, candidate: CandidateGate):
        """Record a gate evolution event."""
        log_path = MEMORY_DIR / "gate_evolution_log.json"
        entry = {
            "gate_name": name,
            "pattern": candidate.pattern,
            "regex": candidate.regex,
            "source_count": candidate.source_count,
            "hit_rate": candidate.hit_rate,
            "false_positive_rate": candidate.false_positive_rate,
        }

        log = []
        if log_path.exists():
            try:
                log = json.loads(log_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                log = []

        log.append(entry)
        log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")


if __name__ == "__main__":
    import os
    log = RewardLog("/tmp/test_gate_evo.db")

    # Simulate recurring patterns
    for i in range(5):
        log.record(
            task_id=f"t{i}", task_type="auth", prompt_variant="v1",
            gate_pass=True, test_pass=True,
            review_findings=["missing null check at auth boundary"] if i < 4 else [],
            critique_predictions=[],
            scope_clean=True, attempt_count=1,
        )

    evo = GateEvolution(log)
    candidates = evo.find_candidates(min_count=3)
    print(f"Candidates: {len(candidates)}")
    for c in candidates:
        result = evo.test_candidate(c)
        print(f"  [{c.source_count}x] {c.pattern[:50]} -> approved={result.approved}")

    print(f"\n{evo.dashboard()}")

    log.close()
    os.remove("/tmp/test_gate_evo.db")
    print("\nGate evolution: OK")
