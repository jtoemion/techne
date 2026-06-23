"""
_loop_types.py — Shared type definitions and constants for the orchestrator loop.

This module exists to break the circular import between orchestrator_loop.py and
its sub-modules (_recall_implement.py, _review_approval.py, _retro_conclude.py,
_orchestrator_helpers.py, _orchestrator_context.py, _orchestrator_retry.py).

Both sides import from here instead of from each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

HARNESS_DIR = Path(__file__).parent
ROOT = HARNESS_DIR.parent
AGENTS_DIR = ROOT / "agents"

MAX_IMPLEMENT_RETRIES = 3
MAX_TOTAL_RETRIES = 5
DEFAULT_VARIANT_COUNT = 1  # number of implement variants to try per task

# Per-phase retry budgets. Phases not listed here use the global MAX_TOTAL_RETRIES
# or their own existing mechanisms (IMPLEMENT, VERIFY). REVIEW uses MAX_TOTAL_RETRIES
# via _retry_counts in _submit_review. CONCLUDE and REFRESH_CONTEXT are gated by
# _impl_retry_or_escalate but also get per-phase counters so IMPLEMENT retries
# don't consume CONCLUDE's budget.
MAX_PHASE_RETRIES = {
    "RECALL": 4,
    "CONTEXT_GUARD": 4,
    "CRITIQUE": 4,
    "REVIEW": 4,
    "RETRO": 4,
    "CONCLUDE": 4,
    "REFRESH_CONTEXT": 4,
}

# Per-phase timeout (seconds). A phase that takes longer than this is FAILED.
PHASE_TIMEOUT_SECONDS = 300


class LoopAction(Enum):
    """What the host should do next."""
    RUN_PHASE = "run_phase"        # execute the prompt for this phase
    RETRY = "retry"                # same phase, with feedback
    ESCALATE = "escalate"          # dispatch debugger agent
    BLOCK_HITL = "block_hitl"      # present question to human, wait
    DONE = "done"                   # task complete
    FAILED = "failed"               # task terminal failure (exhausted retries, unrecoverable)
    HALT = "halt"                   # fatal error — stop the task immediately, no more retries


@dataclass
class LoopOutcome:
    """Result of submitting a phase result to the loop."""
    action: LoopAction
    phase: str
    task_id: str
    message: str = ""
    prompt: Optional[dict] = None   # AgentPrompt for next action (if RUN_PHASE)
    question: str = ""              # HITL question (if BLOCK_HITL)
    options: list[str] | None = None
