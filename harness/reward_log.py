"""
reward_log.py — Composite reward tracking for reinforcement learning.

Records per-task rewards that drive prompt evolution and gate emergence.
Each reward captures:
  - What prompt variant was used
  - How the implementation scored (gate, test, review, scope)
  - How well critique predicted reviewer findings (cross-agent score)
  - How well reviewer covered critique predictions (cross-agent score)

The reward log is the training signal. Prompt evolution reads it to pick
winners. Gate evolution reads it to find patterns worth gating.

Usage:
    from reward_log import RewardLog

    log = RewardLog()  # default: techne/memory/rewards.db

    # Record a task outcome
    log.record(
        task_id="abc123",
        task_type="auth",
        prompt_variant="implementer_v2",
        gate_pass=True,
        test_pass=True,
        review_findings=["missing null check at boundary"],
        critique_predictions=["null check missing at auth boundary"],
        scope_clean=True,
        attempt_count=1,
    )

    # Query for prompt evolution
    best = log.best_variant("auth")  # highest avg composite score

    # Query for gate evolution
    patterns = log.recurring_patterns(min_count=3)
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

HARNESS_DIR = Path(__file__).parent
MEMORY_DIR = HARNESS_DIR.parent / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

DEFAULT_DB = MEMORY_DIR / "rewards.db"

# Reward component weights (sum = 1.0)
WEIGHTS = {
    "gate_pass": 0.25,
    "test_pass": 0.25,
    "review_clean": 0.20,
    "critique_hit": 0.15,
    "scope_clean": 0.10,
    "attempt_efficiency": 0.05,
}


@dataclass
class Reward:
    """A single reward record for one task."""
    id: str
    task_id: str
    task_type: str                    # "auth", "api", "ui", "data", "infra"
    prompt_variant: str               # "implementer_v1", "implementer_v2", etc.
    timestamp: str = ""

    # Raw signals
    gate_pass: bool = True
    test_pass: bool = True
    review_findings: list[str] = field(default_factory=list)
    critique_predictions: list[str] = field(default_factory=list)
    scope_clean: bool = True
    attempt_count: int = 1

    # Computed scores
    composite_score: float = 0.0
    critique_accuracy: float = 0.0    # how well critique predicted review findings
    reviewer_coverage: float = 0.0    # how well reviewer covered critique predictions

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class RewardLog:
    """SQLite-backed reward log for reinforcement learning."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = str(db_path or DEFAULT_DB)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS rewards (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                prompt_variant TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                gate_pass INTEGER DEFAULT 1,
                test_pass INTEGER DEFAULT 1,
                review_findings TEXT DEFAULT '[]',
                critique_predictions TEXT DEFAULT '[]',
                scope_clean INTEGER DEFAULT 1,
                attempt_count INTEGER DEFAULT 1,
                composite_score REAL DEFAULT 0.0,
                critique_accuracy REAL DEFAULT 0.0,
                reviewer_coverage REAL DEFAULT 0.0
            );

            CREATE INDEX IF NOT EXISTS idx_rewards_type ON rewards(task_type);
            CREATE INDEX IF NOT EXISTS idx_rewards_variant ON rewards(prompt_variant);
            CREATE INDEX IF NOT EXISTS idx_rewards_score ON rewards(composite_score);
            CREATE INDEX IF NOT EXISTS idx_rewards_task ON rewards(task_id);
        """)
        self._conn.commit()

    def record(
        self,
        *,
        task_id: str,
        task_type: str,
        prompt_variant: str,
        gate_pass: bool,
        test_pass: bool,
        review_findings: list[str],
        critique_predictions: list[str],
        scope_clean: bool,
        attempt_count: int,
    ) -> Reward:
        """Record a reward. Computes composite score and cross-agent scores."""
        reward_id = _new_id()

        # Compute cross-agent scores
        critique_acc = _critique_accuracy(critique_predictions, review_findings)
        reviewer_cov = _reviewer_coverage(critique_predictions, review_findings)

        # Compute composite score
        composite = _composite_score(
            gate_pass=gate_pass,
            test_pass=test_pass,
            review_findings=review_findings,
            critique_accuracy=critique_acc,
            scope_clean=scope_clean,
            attempt_count=attempt_count,
        )

        reward = Reward(
            id=reward_id,
            task_id=task_id,
            task_type=task_type,
            prompt_variant=prompt_variant,
            gate_pass=gate_pass,
            test_pass=test_pass,
            review_findings=review_findings,
            critique_predictions=critique_predictions,
            scope_clean=scope_clean,
            attempt_count=attempt_count,
            composite_score=composite,
            critique_accuracy=critique_acc,
            reviewer_coverage=reviewer_cov,
        )

        self._conn.execute(
            """INSERT INTO rewards
               (id, task_id, task_type, prompt_variant, timestamp,
                gate_pass, test_pass, review_findings, critique_predictions,
                scope_clean, attempt_count, composite_score,
                critique_accuracy, reviewer_coverage)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (reward.id, reward.task_id, reward.task_type, reward.prompt_variant,
             reward.timestamp, int(reward.gate_pass), int(reward.test_pass),
             json.dumps(reward.review_findings),
             json.dumps(reward.critique_predictions),
             int(reward.scope_clean), reward.attempt_count,
             reward.composite_score, reward.critique_accuracy,
             reward.reviewer_coverage),
        )
        self._conn.commit()
        return reward

    # ── Queries for prompt evolution ─────────────────────────────────────

    def best_variant(self, task_type: str, min_runs: int = 3) -> str | None:
        """Return the prompt variant with highest avg composite score for a task type."""
        rows = self._conn.execute("""
            SELECT prompt_variant, AVG(composite_score) as avg_score, COUNT(*) as cnt
            FROM rewards WHERE task_type = ?
            GROUP BY prompt_variant
            HAVING cnt >= ?
            ORDER BY avg_score DESC
            LIMIT 1
        """, (task_type, min_runs)).fetchall()
        if not rows:
            return None
        return rows[0]["prompt_variant"]

    def variant_scores(self, task_type: str) -> list[dict]:
        """All variants and their scores for a task type."""
        rows = self._conn.execute("""
            SELECT prompt_variant,
                   AVG(composite_score) as avg_score,
                   AVG(critique_accuracy) as avg_critique,
                   AVG(reviewer_coverage) as avg_reviewer,
                   COUNT(*) as cnt,
                   SUM(CASE WHEN gate_pass = 1 THEN 1 ELSE 0 END) as gate_passes,
                   SUM(CASE WHEN test_pass = 1 THEN 1 ELSE 0 END) as test_passes
            FROM rewards WHERE task_type = ?
            GROUP BY prompt_variant
            ORDER BY avg_score DESC
        """, (task_type,)).fetchall()
        return [dict(r) for r in rows]

    def all_task_types(self) -> list[str]:
        """All task types seen so far."""
        rows = self._conn.execute(
            "SELECT DISTINCT task_type FROM rewards ORDER BY task_type"
        ).fetchall()
        return [r["task_type"] for r in rows]

    # ── Queries for gate evolution ───────────────────────────────────────

    def recurring_patterns(self, min_count: int = 3) -> list[dict]:
        """
        Find review findings that appear across multiple tasks.
        These are candidates for gate evolution.
        """
        rows = self._conn.execute("""
            SELECT review_findings FROM rewards
            WHERE review_findings != '[]'
        """).fetchall()

        # Flatten and count
        pattern_counts: dict[str, int] = {}
        pattern_tasks: dict[str, set] = {}
        for row in rows:
            findings = json.loads(row["review_findings"])
            for f in findings:
                key = _normalize_pattern(f)
                if key:
                    pattern_counts[key] = pattern_counts.get(key, 0) + 1
                    pattern_tasks.setdefault(key, set()).add(row["task_id"] if "task_id" in row else "")

        # Filter by min_count
        results = []
        for pattern, count in sorted(pattern_counts.items(), key=lambda x: -x[1]):
            if count >= min_count:
                results.append({
                    "pattern": pattern,
                    "count": count,
                    "sample_finding": pattern,  # the normalized text IS the sample
                })
        return results

    def critique_misses(self, min_count: int = 2) -> list[dict]:
        """
        Find patterns that critique consistently misses but reviewer catches.
        These indicate critique prompt weaknesses.
        """
        rows = self._conn.execute("""
            SELECT critique_predictions, review_findings FROM rewards
            WHERE critique_accuracy < 0.5 AND review_findings != '[]'
        """).fetchall()

        missed_counts: dict[str, int] = {}
        for row in rows:
            critique = set(json.loads(row["critique_predictions"]))
            review = set(json.loads(row["review_findings"]))
            missed = review - critique
            for m in missed:
                key = _normalize_pattern(m)
                if key:
                    missed_counts[key] = missed_counts.get(key, 0) + 1

        return [
            {"pattern": p, "miss_count": c}
            for p, c in sorted(missed_counts.items(), key=lambda x: -x[1])
            if c >= min_count
        ]

    # ── Dashboard ────────────────────────────────────────────────────────

    def dashboard(self) -> str:
        """Human-readable reward summary."""
        total = self._conn.execute("SELECT COUNT(*) FROM rewards").fetchone()[0]
        if total == 0:
            return "No rewards recorded yet."

        avg = self._conn.execute(
            "SELECT AVG(composite_score) FROM rewards"
        ).fetchone()[0]

        lines = [
            "=" * 55,
            "REWARD LOG",
            "=" * 55,
            f"Total rewards: {total}",
            f"Avg composite: {avg:.3f}",
            "",
            "BY TASK TYPE:",
        ]

        types = self._conn.execute("""
            SELECT task_type, COUNT(*) as cnt,
                   AVG(composite_score) as avg,
                   AVG(critique_accuracy) as crit,
                   AVG(reviewer_coverage) as rev
            FROM rewards GROUP BY task_type ORDER BY avg DESC
        """).fetchall()
        for t in types:
            lines.append(
                f"  {t['task_type']:12}  runs={t['cnt']:3d}  "
                f"score={t['avg']:.3f}  critique={t['crit']:.3f}  "
                f"reviewer={t['rev']:.3f}"
            )

        lines.append("\nBY VARIANT:")
        variants = self._conn.execute("""
            SELECT prompt_variant, COUNT(*) as cnt,
                   AVG(composite_score) as avg
            FROM rewards GROUP BY prompt_variant ORDER BY avg DESC
        """).fetchall()
        for v in variants:
            lines.append(
                f"  {v['prompt_variant']:20}  runs={v['cnt']:3d}  score={v['avg']:.3f}"
            )

        patterns = self.recurring_patterns(min_count=2)
        if patterns:
            lines.append(f"\nRECURRING PATTERNS ({len(patterns)}):")
            for p in patterns[:5]:
                lines.append(f"  [{p['count']}x] {p['pattern'][:60]}")

        misses = self.critique_misses(min_count=2)
        if misses:
            lines.append(f"\nCRITIQUE BLIND SPOTS ({len(misses)}):")
            for m in misses[:5]:
                lines.append(f"  [{m['miss_count']}x missed] {m['pattern'][:60]}")

        lines.append("=" * 55)
        return "\n".join(lines)

    def close(self):
        self._conn.close()


# ── Scoring functions ────────────────────────────────────────────────────

def _composite_score(
    gate_pass: bool,
    test_pass: bool,
    review_findings: list[str],
    critique_accuracy: float,
    scope_clean: bool,
    attempt_count: int,
) -> float:
    """Weighted composite score (0-1)."""
    gate = 1.0 if gate_pass else 0.0
    test = 1.0 if test_pass else 0.0
    review = 1.0 if not review_findings else max(0.0, 1.0 - len(review_findings) * 0.2)
    scope = 1.0 if scope_clean else 0.0
    attempts = max(0.0, 1.0 - (attempt_count - 1) * 0.25)  # 1 attempt=1.0, 2=0.75, 3=0.5, 4=0.25

    return (
        WEIGHTS["gate_pass"] * gate +
        WEIGHTS["test_pass"] * test +
        WEIGHTS["review_clean"] * review +
        WEIGHTS["critique_hit"] * critique_accuracy +
        WEIGHTS["scope_clean"] * scope +
        WEIGHTS["attempt_efficiency"] * attempts
    )


def _critique_accuracy(predictions: list[str], findings: list[str]) -> float:
    """
    How well did critique predict what reviewer found?
    1.0 = all findings were predicted, 0.0 = none were.
    Uses fuzzy matching — prediction doesn't need to be exact.
    """
    if not findings:
        return 1.0  # nothing to predict
    if not predictions:
        return 0.0  # critique predicted nothing

    pred_normalized = {_normalize_pattern(p) for p in predictions if _normalize_pattern(p)}
    find_normalized = {_normalize_pattern(f) for f in findings if _normalize_pattern(f)}

    if not find_normalized:
        return 1.0

    # How many findings were at least partially predicted?
    matched = 0
    for f in find_normalized:
        for p in pred_normalized:
            if _patterns_overlap(f, p):
                matched += 1
                break

    return matched / len(find_normalized)


def _reviewer_coverage(predictions: list[str], findings: list[str]) -> float:
    """
    How well did reviewer cover critique's predictions?
    1.0 = reviewer caught everything critique predicted, 0.0 = caught nothing.
    """
    if not predictions:
        return 1.0  # nothing to cover
    if not findings:
        return 0.0  # reviewer found nothing

    pred_normalized = {_normalize_pattern(p) for p in predictions if _normalize_pattern(p)}
    find_normalized = {_normalize_pattern(f) for f in findings if _normalize_pattern(f)}

    if not pred_normalized:
        return 1.0

    matched = 0
    for p in pred_normalized:
        for f in find_normalized:
            if _patterns_overlap(p, f):
                matched += 1
                break

    return matched / len(pred_normalized)


def _normalize_pattern(text: str) -> str:
    """Normalize a finding/pattern for comparison."""
    import re
    text = text.lower().strip()
    # Remove file:line references
    text = re.sub(r'\[?\w+\.\w+:\d+\]?', '', text)
    # Remove common prefixes
    for prefix in ["critical:", "warning:", "high:", "medium:", "low:", "- "]:
        if text.startswith(prefix):
            text = text[len(prefix):]
    text = text.strip()
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text)
    return text[:100]  # cap length for comparison


def _patterns_overlap(a: str, b: str) -> bool:
    """Check if two normalized patterns overlap significantly."""
    # Simple: check if they share 3+ significant words
    stopwords = {"the", "a", "an", "is", "are", "was", "in", "on", "at", "to", "for", "of", "and", "or", "not", "no"}
    words_a = {w for w in a.split() if len(w) > 2 and w not in stopwords}
    words_b = {w for w in b.split() if len(w) > 2 and w not in stopwords}
    if not words_a or not words_b:
        return False
    overlap = words_a & words_b
    # Require 40% overlap of the shorter set
    min_len = min(len(words_a), len(words_b))
    return len(overlap) >= max(2, int(min_len * 0.4))


def _new_id() -> str:
    import uuid
    return uuid.uuid4().hex[:12]


if __name__ == "__main__":
    import os
    log = RewardLog("/tmp/test_rewards.db")

    # Simulate rewards
    log.record(
        task_id="t1", task_type="auth", prompt_variant="implementer_v1",
        gate_pass=True, test_pass=True,
        review_findings=["missing null check at auth boundary"],
        critique_predictions=["null check missing at auth middleware boundary"],
        scope_clean=True, attempt_count=1,
    )
    log.record(
        task_id="t2", task_type="auth", prompt_variant="implementer_v2",
        gate_pass=True, test_pass=True,
        review_findings=["stale closure in useEffect"],
        critique_predictions=["race condition in async flow"],
        scope_clean=True, attempt_count=2,
    )
    log.record(
        task_id="t3", task_type="api", prompt_variant="implementer_v1",
        gate_pass=True, test_pass=True,
        review_findings=[],
        critique_predictions=[],
        scope_clean=True, attempt_count=1,
    )

    print(log.dashboard())
    print(f"\nBest variant for auth: {log.best_variant('auth')}")
    print(f"Best variant for api: {log.best_variant('api')}")

    patterns = log.recurring_patterns(min_count=1)
    print(f"\nRecurring patterns: {patterns}")

    log.close()
    os.remove("/tmp/test_rewards.db")
    print("\nReward log: OK")
