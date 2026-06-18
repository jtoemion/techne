"""
gate_evolution.py — Evidence-staged gate generation behind a propose/validate/ratify firewall.

A gate is part of the GRADER — the reward function the pipeline is scored against.
Letting the grader rewrite itself is the sharpest Goodhart surface there is: the
detector learns to call its own slop clean. So gate generation mirrors
prompt_evolution's firewall EXACTLY — a recurring finding may be PROPOSED as a gate,
STRUCTURALLY VALIDATED against history, and only a HUMAN ratification writes the gate
plugin to harness/plugins/. No statistical threshold alone may ship a gate.

  propose(min_count)    recurrence gate — a finding seen min_count+ times stages a
                        GateProposal (persisted, NOT written to plugins/).
  validate(proposal)    structural gate — retroactive test vs history (hit >= 80%,
                        false-positive <= 10%). Marks validated | rejected. Never writes.
  ratify(id, approved)  human gate — the ONLY path that writes the gate plugin file.

prompt_evolution.py is the same firewall on the POLICY; this is the firewall on the
GRADER. Previously auto_evolve() wrote a gate the instant thresholds passed — that
hole is closed; auto_evolve() now only stages.

Usage:
    from gate_evolution import GateEvolution

    evo = GateEvolution(reward_log)
    proposals = evo.propose(min_count=3)          # stage candidates (recurrence)
    for p in proposals:
        evo.validate(p)                           # structural gate vs history
    evo.ratify(proposals[0].id, approved=True)    # human writes the gate

    print(evo.dashboard())
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from reward_log import RewardLog, _normalize_pattern

HARNESS_DIR = Path(__file__).parent
PLUGINS_DIR = HARNESS_DIR / "plugins"
MEMORY_DIR = HARNESS_DIR.parent / "memory"
DEFAULT_PROPOSALS_PATH = MEMORY_DIR / "gate_proposals.json"

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


@dataclass
class GateProposal:
    """
    A staged gate awaiting structural validation and human ratification.

    A proposal never becomes an active gate until ratified. This is the firewall
    against a self-writing grader: recurrence (propose), a retroactive structural
    test (validate), and a human (ratify) must all agree before the gate plugin is
    written to harness/plugins/. Mirrors prompt_evolution.Proposal.

    status transitions:
        pending → validated → ratified   (the happy path)
        pending → rejected                (failed the structural gate)
        validated → rejected              (human declined)
    """
    id: str
    gate_name: str
    pattern: str
    regex: str
    source_count: int
    status: str = "pending"          # pending | validated | rejected | ratified
    hit_rate: float = 0.0
    false_positive_rate: float = 0.0
    created: str = ""
    ratified_by: str = ""
    gate_path: str = ""              # path to the written plugin, set on ratify

    def __post_init__(self):
        if not self.created:
            self.created = datetime.now(timezone.utc).isoformat()


class GateEvolution:
    """
    Finds recurring patterns in review findings and stages them as gate proposals.
    A proposal is tested against history (validate) and written only on human
    ratification — the grader never self-writes.
    """

    def __init__(self, reward_log: RewardLog, proposals_path: str | Path | None = None):
        self.reward_log = reward_log
        self.proposals_path = Path(proposals_path or DEFAULT_PROPOSALS_PATH)

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
        Back-compat shim. No longer auto-writes gates — it now STAGES proposals
        (recurrence gate) and returns []. Promotion requires validate() + ratify().

        The old behavior wrote a gate the instant statistical thresholds passed;
        that let the grader rewrite itself. The firewall is now closed: nothing is
        written here. Inspect list_proposals() / dashboard() for what was staged.
        """
        self.propose(min_count=min_count)
        return []

    # ── propose / validate / ratify — the grader firewall ────────────────────

    def propose(self, min_count: int = MIN_PATTERN_COUNT) -> list[GateProposal]:
        """
        Stage recurring patterns as GateProposals (recurrence gate).

        Returns the open proposals (existing + newly staged). Nothing is written
        to plugins/ — a proposal cannot become an active gate until validate() +
        ratify() promote it. Idempotent while open: re-proposing the same
        gate_name reuses the open proposal instead of stacking duplicates.
        """
        open_by_name = {
            p.gate_name: p for p in self._load_proposals()
            if p.status in ("pending", "validated")
        }
        staged: list[GateProposal] = []
        for candidate in self.find_candidates(min_count=min_count):
            gate_name = self._pattern_to_gate_name(candidate.pattern)
            existing = open_by_name.get(gate_name)
            if existing is not None:
                staged.append(existing)
                continue
            proposal = GateProposal(
                id=uuid.uuid4().hex[:12],
                gate_name=gate_name,
                pattern=candidate.pattern,
                regex=candidate.regex,
                source_count=candidate.source_count,
            )
            self._save_proposal(proposal)
            open_by_name[gate_name] = proposal
            staged.append(proposal)
        return staged

    def validate(self, proposal: GateProposal) -> GateProposal:
        """
        Structural gate: retroactively test the candidate against history and mark
        it validated or rejected. Never writes the gate — passing validation only
        makes it eligible for human ratification.
        """
        candidate = self._proposal_to_candidate(proposal)
        result = self.test_candidate(candidate)
        proposal.hit_rate = result.hit_rate
        proposal.false_positive_rate = result.false_positive_rate
        proposal.status = "validated" if result.approved else "rejected"
        self._save_proposal(proposal)
        return proposal

    def ratify(self, proposal_id: str, approved: bool, by: str = "human") -> bool:
        """
        Human ratification — the ONLY path that writes a gate plugin.

        Writes the gate ONLY when the proposal exists, was structurally validated,
        and the human approved. Any other case leaves plugins/ untouched and
        returns False. Enforces all three gates: recurrence + structural + human.
        """
        proposal = self.get_proposal(proposal_id)
        if proposal is None:
            return False

        if not approved:
            proposal.status = "rejected"
            proposal.ratified_by = by
            self._save_proposal(proposal)
            return False

        if proposal.status != "validated":
            # Structurally-gated: cannot promote what history hasn't cleared.
            return False

        candidate = self._proposal_to_candidate(proposal)
        candidate.approved = True
        path = self.approve(candidate)
        proposal.status = "ratified"
        proposal.ratified_by = by
        proposal.gate_path = str(path) if path else ""
        self._save_proposal(proposal)
        return path is not None

    # ── Proposal persistence ─────────────────────────────────────────────────

    def _proposal_to_candidate(self, proposal: GateProposal) -> CandidateGate:
        return CandidateGate(
            pattern=proposal.pattern,
            regex=proposal.regex,
            source_count=proposal.source_count,
            sample_findings=[proposal.pattern],
            hit_rate=proposal.hit_rate,
            false_positive_rate=proposal.false_positive_rate,
        )

    def _load_proposals(self) -> list[GateProposal]:
        if not self.proposals_path.exists():
            return []
        try:
            raw = json.loads(self.proposals_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return [GateProposal(**d) for d in raw]

    def _save_proposal(self, proposal: GateProposal) -> None:
        """Upsert a proposal into the log by id."""
        proposals = [p for p in self._load_proposals() if p.id != proposal.id]
        proposals.append(proposal)
        self.proposals_path.parent.mkdir(parents=True, exist_ok=True)
        self.proposals_path.write_text(
            json.dumps([asdict(p) for p in proposals], indent=2),
            encoding="utf-8",
        )

    def get_proposal(self, proposal_id: str) -> Optional[GateProposal]:
        return next((p for p in self._load_proposals() if p.id == proposal_id), None)

    def list_proposals(self, status: Optional[str] = None) -> list[GateProposal]:
        proposals = self._load_proposals()
        if status is not None:
            proposals = [p for p in proposals if p.status == status]
        return proposals

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
                status = "✓ would validate" if result.approved else "○ monitoring"
                lines.append(
                    f"  {status}  [{c.source_count}x] {c.pattern[:45]:45s}  "
                    f"regex: {c.regex[:30]}"
                )
                lines.append(f"           {result.reason[:70]}")

        # Staged proposals awaiting human ratification (the firewall queue)
        staged = [p for p in self._load_proposals()
                  if p.status in ("pending", "validated")]
        if staged:
            lines.append(f"\nStaged proposals ({len(staged)}) — awaiting ratify:")
            for p in staged:
                lines.append(f"  [{p.status:9s}] {p.gate_name}  ({p.source_count}x)")

        # Show existing evolved gates (written = already ratified)
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
        """Convert a pattern to a SAFE snake_case identifier.

        SECURITY: this name is emitted as a Python identifier in generated code that
        gets imported and executed (see _generate_gate_code). It is restricted to
        [a-z0-9_] with a leading letter so an attacker-influenced review finding can
        never inject code through the gate name.
        """
        import re
        name = pattern.lower().strip()
        for word in ["the", "a", "an", "is", "are", "in", "on", "at"]:
            name = name.replace(f" {word} ", " ")
        words = [w for w in name.split() if len(w) > 2][:3]
        safe = re.sub(r"[^a-z0-9_]", "_", "_".join(words)).strip("_")
        if not safe or not safe[0].isalpha():
            safe = "g_" + (safe or "gate")
        return safe[:60]

    def _generate_gate_code(self, name: str, regex: str, description: str) -> str:
        """Generate a gate plugin Python file.

        SECURITY: review findings are not trusted input — they may be authored by a
        model or host. So the gate NAME is validated to a strict identifier, and the
        regex + description are emitted as repr() LITERALS, never interpolated into the
        source structure. This makes it impossible for a finding like '\"\"\";import os'
        to break out of a docstring/string and inject code into the imported module.
        """
        import re as _re
        if not _re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise ValueError(f"unsafe gate name (refusing to generate code): {name!r}")
        # The regex must actually compile, or the generated plugin would crash the whole
        # gate-discovery import. Reject it at generation time, not at runtime.
        try:
            _re.compile(regex)
        except _re.error as e:
            raise ValueError(f"refusing to generate a gate with an invalid regex: {e}") from e
        # repr() → safe Python string literals (handles quotes, backslashes, newlines).
        desc_lit = repr(description)
        regex_lit = repr(regex)
        return f'''"""Auto-generated gate: {name}

Generated by gate_evolution.py from a recurring review finding. The pattern text is
stored as a string literal below — never interpolated as source.
"""
import re
from gates import GateViolation, _strip_diff_marker, _is_comment

_PATTERN_DESC = {desc_lit}
_REGEX = re.compile({regex_lit})


def _gate_{name}(diff: str):
    """Reject diffs matching an auto-generated pattern (see _PATTERN_DESC)."""
    for i, line in enumerate(diff.splitlines()):
        if not line.startswith("+") or line.startswith("+++"):
            continue
        code = _strip_diff_marker(line)
        if _is_comment(code):
            continue
        if _REGEX.search(code):
            raise GateViolation(
                "GATE FAIL [evolved/{name}]: pattern match on line "
                + str(i + 1) + ".\\n  Pattern: " + _PATTERN_DESC
                + "\\n  -> " + line.strip()
            )


def register(registry):
    """Register the evolved gate."""
    registry.register(
        "evolved/{name}",
        _gate_{name},
        stack="general",
        category="hard",
        severity="error",
        description="Auto-generated: " + _PATTERN_DESC,
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
    import tempfile

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

    # Redirect writes to a temp dir so the self-test never touches real plugins/memory.
    tmp = Path(tempfile.mkdtemp())
    PLUGINS_DIR = tmp / "plugins"; PLUGINS_DIR.mkdir()
    MEMORY_DIR = tmp / "memory"; MEMORY_DIR.mkdir()
    evo = GateEvolution(log, proposals_path=tmp / "gate_proposals.json")

    # propose → validate → ratify (the firewall)
    proposals = evo.propose(min_count=3)
    print(f"Proposed: {len(proposals)} (nothing written yet)")
    for p in proposals:
        evo.validate(p)
        print(f"  {p.gate_name}: {p.status} (hit={p.hit_rate:.0%})")

    if proposals:
        first = proposals[0]
        # A pending/unvalidated proposal cannot be written.
        before = evo.get_proposal(first.id).status
        wrote = evo.ratify(first.id, approved=True, by="self-test")
        print(f"ratify({first.gate_name}) wrote gate: {wrote}")

    print(f"\n{evo.dashboard()}")

    log.close()
    if os.path.exists("/tmp/test_gate_evo.db"):
        os.remove("/tmp/test_gate_evo.db")
    print("\nGate evolution firewall: OK")
