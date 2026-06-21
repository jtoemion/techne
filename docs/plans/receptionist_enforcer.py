"""
receptionist_enforcer.py — State machine that enforces the Receptionist
dispatch protocol, the same way pipeline_enforcer.py enforces Techne's
phase order.

Context: the Receptionist's rules (one mode per dispatch, verify before
advancing, one retry max, no blending modes) exist only as prose in
receptionist/SKILL.md and references/receptionist-protocol.md. Nothing
checks they were actually followed — the same gap pipeline_enforcer.py
closes for Techne's own phases. This module closes it for the Receptionist
layer, one level above Techne.

Mode set reflects the P5.1 collapse: EXPLORE and SCOUT stay as genuine
pre-pipeline modes (no diff produced, no Techne phase to land in). BUILD
and DEBUGGING are gone — anything that produces a diff dispatches as
IMPLEMENT, with FIX_OF carrying DEBUGGING's old root-cause/regression-risk
requirement as a conditional field rather than a separate mode.

Usage:
    from receptionist_enforcer import ReceptionistEnforcer

    enforcer = ReceptionistEnforcer(db)

    # Before each dispatch:
    enforcer.can_dispatch(ticket_id, "IMPLEMENT")

    # After each dispatch, before treating it as resolved:
    enforcer.mark_dispatched(ticket_id, "IMPLEMENT", mode="IMPLEMENT", ...)

    # After reading and accepting the subagent's report:
    enforcer.mark_verified(ticket_id, accepted=True, summary="...")

    # If the report was rejected and a retry is needed:
    enforcer.mark_retry(ticket_id, reason="...")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from task_db import TaskDB, Task


# ── Mode definitions ─────────────────────────────────────────────────────
# Three modes post-collapse (see P5.1). EXPLORE/SCOUT never produce a diff
# and never enter Techne. IMPLEMENT always does, and is the only mode that
# triggers a Techne pipeline run.

MODES = ["EXPLORE", "SCOUT", "IMPLEMENT"]

# A ticket's lifecycle, independent of which mode it is:
#   OPEN        — ticket written, not yet dispatched
#   DISPATCHED  — delegate_task called, awaiting subagent report
#   VERIFIED    — report read, accepted, ticket can close
#   RETRY       — report rejected once, re-ticketed (one retry max)
#   FAILED      — second attempt also failed, flagged to user, terminal
#   CLOSED      — VERIFIED and folded into the session's running plan
TICKET_STATES = ["OPEN", "DISPATCHED", "VERIFIED", "RETRY", "FAILED", "CLOSED"]

MAX_RETRIES = 1   # "One retry max" — references/receptionist-protocol.md


@dataclass
class TicketTransition:
    allowed: bool
    current_state: Optional[str]
    target_state: str
    reason: str = ""
    ticket: Optional[Task] = None


class ReceptionistEnforcer:
    """
    Gates Receptionist ticket dispatch the way PipelineEnforcer gates
    Techne phases. Backed by the same TaskDB — Receptionist tickets are
    logged as TaskEvents with agent="receptionist", action=<mode or
    lifecycle step>, the same event trail Techne phases already use.

    This does NOT gate "never execute work yourself" — that's a property
    of what the Receptionist itself does outside any ticket, and no
    per-ticket check can observe it. See the module docstring and the
    build-guide patch entry this came from for that limitation stated
    plainly, rather than papered over.
    """

    def __init__(self, db: TaskDB):
        self.db = db

    # ── Mode-exclusivity gate ────────────────────────────────────────────
    # "Don't blend EXPLORE+BUILD in a single dispatch. Modes don't mix."

    def can_dispatch(self, ticket_id: str, mode: str) -> TicketTransition:
        """
        Check whether a ticket may be dispatched under the given mode.

        Rejects:
          - an unknown mode (not in MODES — catches BUILD/DEBUGGING typos
            left over from the pre-collapse protocol)
          - a ticket that already has a mode recorded and is being
            re-dispatched under a *different* mode (mode-blending)
          - a ticket already in a terminal state (FAILED, CLOSED)
          - more than MAX_RETRIES dispatches for the same ticket
        """
        ticket = self.db.get_task(ticket_id)
        if not ticket:
            return TicketTransition(
                allowed=False, current_state=None, target_state="DISPATCHED",
                reason=f"Ticket {ticket_id} not found",
            )

        if mode not in MODES:
            return TicketTransition(
                allowed=False, current_state=self._state(ticket_id),
                target_state="DISPATCHED",
                reason=(
                    f"Unknown mode '{mode}'. Valid modes post-collapse: "
                    f"{', '.join(MODES)}. BUILD and DEBUGGING no longer "
                    f"exist as separate modes — use IMPLEMENT, with FIX_OF "
                    f"set for fix-type tickets."
                ),
                ticket=ticket,
            )

        history = self.db.get_task_history(ticket_id)
        prior_modes = {e.action for e in history if e.action in MODES}
        if prior_modes and mode not in prior_modes:
            return TicketTransition(
                allowed=False, current_state=self._state(ticket_id),
                target_state="DISPATCHED",
                reason=(
                    f"Mode-blend violation: ticket {ticket_id} was already "
                    f"dispatched as {sorted(prior_modes)}. One subagent = "
                    f"one mode = one ticket. Open a new ticket instead of "
                    f"re-dispatching this one under {mode}."
                ),
                ticket=ticket,
            )

        state = self._state(ticket_id)
        if state in ("FAILED", "CLOSED"):
            return TicketTransition(
                allowed=False, current_state=state, target_state="DISPATCHED",
                reason=f"Ticket is {state} — terminal, cannot re-dispatch",
                ticket=ticket,
            )

        retry_count = sum(1 for e in history if e.action == "RETRY")
        dispatch_count = sum(1 for e in history if e.action in MODES)
        if retry_count >= MAX_RETRIES and dispatch_count > retry_count:
            # retry_count dispatches have already been retried-from, and a
            # further dispatch beyond that would be attempt #3+ — blocked.
            # One retry max means: original dispatch + ONE re-dispatch is
            # allowed; the re-dispatch itself is the "second attempt" the
            # protocol says must not fail silently a third time.
            return TicketTransition(
                allowed=False, current_state=state, target_state="DISPATCHED",
                reason=(
                    f"One retry max already used ({retry_count}), and the "
                    f"re-dispatch already happened ({dispatch_count} total "
                    f"dispatches). Per protocol: stop and flag to the "
                    f"user, do not re-dispatch a third time."
                ),
                ticket=ticket,
            )

        return TicketTransition(
            allowed=True, current_state=state, target_state="DISPATCHED",
            ticket=ticket,
        )

    def mark_dispatched(
        self, ticket_id: str, mode: str, *,
        objective: str = "", fix_of: str = "",
    ) -> TicketTransition:
        """
        Record that delegate_task was actually called for this ticket.
        Validates can_dispatch() first — raises if the gate rejects it,
        the same fail-loud contract pipeline_enforcer.mark_complete() uses.

        fix_of: pass the failure being fixed (error text / failing test
        name) for any IMPLEMENT ticket that fixes a reproducible failure
        rather than building something new. Recorded so mark_verified()
        can require the root-cause/regression-risk fields DEBUGGING used
        to mandate as a separate mode.
        """
        check = self.can_dispatch(ticket_id, mode)
        if not check.allowed:
            raise ValueError(f"Receptionist dispatch violation: {check.reason}")

        summary = objective[:200]
        if fix_of:
            summary = f"[FIX_OF: {fix_of[:80]}] {summary}"
        self.db._log_event(ticket_id, "receptionist", mode, summary)
        return check

    # ── Verification gate ────────────────────────────────────────────────
    # "A delegation isn't done until you've read and accepted its report.
    #  No fire-and-forget."

    def mark_verified(
        self, ticket_id: str, *, accepted: bool, summary: str = "",
        root_cause: str = "", regression_risk: str = "",
    ) -> TicketTransition:
        """
        Record that the Receptionist read and accepted (or rejected) a
        subagent's report. A ticket cannot be CLOSED without this being
        called at least once with accepted=True — see close_ticket().

        If the dispatched ticket had fix_of set, root_cause and
        regression_risk are REQUIRED here — this is FIX_OF's enforcement
        point, the conditional requirement that absorbed DEBUGGING's old
        output contract into IMPLEMENT's ticket schema.
        """
        ticket = self.db.get_task(ticket_id)
        if not ticket:
            return TicketTransition(
                allowed=False, current_state=None, target_state="VERIFIED",
                reason=f"Ticket {ticket_id} not found",
            )

        history = self.db.get_task_history(ticket_id)
        dispatch_events = [e for e in history if e.action in MODES]
        if not dispatch_events:
            return TicketTransition(
                allowed=False, current_state=self._state(ticket_id),
                target_state="VERIFIED",
                reason="Cannot verify a ticket that was never dispatched",
                ticket=ticket,
            )

        last_dispatch = dispatch_events[-1]
        had_fix_of = last_dispatch.summary.startswith("[FIX_OF:")
        if accepted and had_fix_of and not (root_cause and regression_risk):
            return TicketTransition(
                allowed=False, current_state=self._state(ticket_id),
                target_state="VERIFIED",
                reason=(
                    "This ticket has FIX_OF set — root_cause and "
                    "regression_risk are required to accept it. This is "
                    "the absorbed DEBUGGING output contract; it doesn't "
                    "disappear just because BUILD/DEBUGGING are no longer "
                    "separate modes."
                ),
                ticket=ticket,
            )

        action = "VERIFIED" if accepted else "RETRY"
        self.db._log_event(
            ticket_id, "receptionist", action, summary[:200],
            findings=f"root_cause={root_cause}; regression_risk={regression_risk}"
                      if had_fix_of else "",
            verdict="PASS" if accepted else "SOFT_FAIL",
        )
        return TicketTransition(
            allowed=True, current_state=self._state(ticket_id),
            target_state=action, ticket=ticket,
        )

    def mark_retry(self, ticket_id: str, reason: str) -> TicketTransition:
        """
        Explicit retry marker — separate from mark_verified(accepted=False)
        so a ticket's retry count is unambiguous in the event trail.
        Enforces MAX_RETRIES: the second call for the same ticket raises,
        matching "if the second attempt also fails, stop and flag to the
        user — don't quietly fix it yourself."
        """
        history = self.db.get_task_history(ticket_id)
        retry_count = sum(1 for e in history if e.action == "RETRY")
        if retry_count >= MAX_RETRIES:
            raise ValueError(
                f"Receptionist dispatch violation: ticket {ticket_id} has "
                f"already used its one retry. Stop and flag to the user — "
                f"do not re-ticket a third time."
            )
        self.db._log_event(
            ticket_id, "receptionist", "RETRY", reason[:200], verdict="SOFT_FAIL",
        )
        return TicketTransition(
            allowed=True, current_state=self._state(ticket_id),
            target_state="RETRY",
        )

    def close_ticket(self, ticket_id: str) -> TicketTransition:
        """
        Final step — requires a VERIFIED(accepted=True) event to exist in
        the history. This is what makes "no fire-and-forget" enforceable:
        a ticket cannot reach CLOSED by any path that skips mark_verified.
        """
        history = self.db.get_task_history(ticket_id)
        verified = [e for e in history if e.action == "VERIFIED" and e.verdict == "PASS"]
        if not verified:
            return TicketTransition(
                allowed=False, current_state=self._state(ticket_id),
                target_state="CLOSED",
                reason=(
                    "Cannot close — no accepted VERIFIED event in history. "
                    "Read and accept the subagent's report via "
                    "mark_verified(accepted=True) first."
                ),
            )
        self.db._log_event(ticket_id, "receptionist", "CLOSED", "Ticket closed")
        return TicketTransition(
            allowed=True, current_state="CLOSED", target_state="CLOSED",
        )

    # ── Internals ─────────────────────────────────────────────────────────

    def _state(self, ticket_id: str) -> Optional[str]:
        history = self.db.get_task_history(ticket_id)
        if not history:
            return None
        for e in reversed(history):
            if e.action in ("CLOSED", "FAILED", "VERIFIED", "RETRY"):
                return e.action
            if e.action in MODES:
                return "DISPATCHED"
        return None
