"""
Tests for receptionist_enforcer.py — proves the gates actually hold,
mirroring the rigor pipeline_enforcer.py's own tests apply to Techne phases.

Each test is written to FAIL if the corresponding gate were removed —
that's the point. A passing test that can't be made to fail by deleting
the check it claims to verify isn't actually testing the gate.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "harness"))

import pytest
from task_db import TaskDB
from receptionist_enforcer import ReceptionistEnforcer, MODES, MAX_RETRIES


@pytest.fixture
def db(tmp_path):
    return TaskDB(str(tmp_path / "tasks.db"))


@pytest.fixture
def enforcer(db):
    return ReceptionistEnforcer(db)


def test_unknown_mode_rejected(db, enforcer):
    """BUILD and DEBUGGING no longer exist as separate modes (P5.1
    collapse). A ticket dispatched under either should be rejected with
    guidance toward IMPLEMENT + FIX_OF, not silently accepted."""
    ticket = db.create_task("Fix the login bug")
    check = enforcer.can_dispatch(ticket.id, "DEBUGGING")
    assert not check.allowed
    assert "IMPLEMENT" in check.reason
    assert "FIX_OF" in check.reason


def test_known_modes_accepted(db, enforcer):
    for mode in MODES:
        ticket = db.create_task(f"Test ticket for {mode}")
        check = enforcer.can_dispatch(ticket.id, mode)
        assert check.allowed, f"{mode} should be a valid mode post-collapse"


def test_mode_blend_rejected(db, enforcer):
    """'Don't blend EXPLORE+BUILD in a single dispatch. Modes don't mix.'
    Once a ticket has been dispatched under one mode, dispatching the SAME
    ticket under a different mode must be rejected — that's mode-blending,
    not a legitimate retry."""
    ticket = db.create_task("Investigate then implement")
    enforcer.mark_dispatched(ticket.id, "EXPLORE", objective="look around")

    check = enforcer.can_dispatch(ticket.id, "IMPLEMENT")
    assert not check.allowed
    assert "blend" in check.reason.lower()


def test_same_mode_redispatch_allowed_for_retry(db, enforcer):
    """A retry under the SAME mode is fine — only blending DIFFERENT modes
    on one ticket is the violation."""
    ticket = db.create_task("Implement the thing")
    enforcer.mark_dispatched(ticket.id, "IMPLEMENT", objective="build it")
    enforcer.mark_retry(ticket.id, reason="report was ambiguous")

    check = enforcer.can_dispatch(ticket.id, "IMPLEMENT")
    assert check.allowed


def test_one_retry_max_enforced(db, enforcer):
    """'If the second attempt also fails, stop and flag to the user —
    don't quietly fix it yourself.' A second mark_retry() call for the
    same ticket must raise, not silently succeed."""
    ticket = db.create_task("Flaky ticket")
    enforcer.mark_dispatched(ticket.id, "IMPLEMENT", objective="x")
    enforcer.mark_retry(ticket.id, reason="first failure")

    with pytest.raises(ValueError, match="already used its one retry"):
        enforcer.mark_retry(ticket.id, reason="second failure")


def test_cannot_dispatch_after_retry_exhausted(db, enforcer):
    """After one retry has been used AND the re-dispatch has happened,
    can_dispatch must refuse a third dispatch — this is what makes 'stop
    and flag to the user' enforceable rather than just advisory. The
    re-dispatch itself (attempt #2) is allowed; only attempt #3+ is
    blocked."""
    ticket = db.create_task("Flaky ticket")
    enforcer.mark_dispatched(ticket.id, "IMPLEMENT", objective="x")     # attempt 1
    enforcer.mark_retry(ticket.id, reason="first failure")
    enforcer.mark_dispatched(ticket.id, "IMPLEMENT", objective="x")     # attempt 2 (the retry)

    check = enforcer.can_dispatch(ticket.id, "IMPLEMENT")               # attempt 3 — blocked
    assert not check.allowed
    assert "retry max" in check.reason.lower()


def test_cannot_close_without_verification(db, enforcer):
    """'A delegation isn't done until you've read and accepted its report.
    No fire-and-forget.' Dispatching is not the same as closing — there
    must be no path from DISPATCHED straight to CLOSED."""
    ticket = db.create_task("Unverified ticket")
    enforcer.mark_dispatched(ticket.id, "IMPLEMENT", objective="x")

    check = enforcer.close_ticket(ticket.id)
    assert not check.allowed
    assert "no accepted VERIFIED event" in check.reason


def test_close_succeeds_after_verification(db, enforcer):
    ticket = db.create_task("Properly verified ticket")
    enforcer.mark_dispatched(ticket.id, "IMPLEMENT", objective="x")
    enforcer.mark_verified(ticket.id, accepted=True, summary="diff looks correct")

    check = enforcer.close_ticket(ticket.id)
    assert check.allowed


def test_fix_of_requires_root_cause_and_regression_risk(db, enforcer):
    """FIX_OF absorbed DEBUGGING's output contract (root cause statement +
    regression risk note) into IMPLEMENT's conditional requirements. A
    FIX_OF ticket accepted without both must be rejected — otherwise the
    P5.1 collapse silently dropped DEBUGGING's discipline instead of
    folding it in."""
    ticket = db.create_task("Fix the null pointer crash")
    enforcer.mark_dispatched(
        ticket.id, "IMPLEMENT", objective="fix crash",
        fix_of="NullPointerException in checkout.py line 42",
    )

    # Accepting without root_cause/regression_risk must fail
    check = enforcer.mark_verified(ticket.id, accepted=True, summary="fixed it")
    assert not check.allowed
    assert "root_cause and regression_risk are required" in check.reason

    # Accepting WITH both must succeed
    check = enforcer.mark_verified(
        ticket.id, accepted=True, summary="fixed it",
        root_cause="checkout.py assumed cart was never empty",
        regression_risk="low — guarded by existing empty-cart test",
    )
    assert check.allowed


def test_fix_of_not_required_for_net_new_work(db, enforcer):
    """A ticket with no FIX_OF (net-new work, the old BUILD case) must NOT
    require root_cause/regression_risk — that requirement is conditional,
    not universal."""
    ticket = db.create_task("Build a new export button")
    enforcer.mark_dispatched(ticket.id, "IMPLEMENT", objective="build it")

    check = enforcer.mark_verified(ticket.id, accepted=True, summary="built it")
    assert check.allowed


def test_cannot_verify_undispatched_ticket(db, enforcer):
    """Calling mark_verified on a ticket that was never dispatched should
    be rejected, not silently accepted as a no-op."""
    ticket = db.create_task("Never dispatched")
    check = enforcer.mark_verified(ticket.id, accepted=True, summary="...")
    assert not check.allowed
    assert "never dispatched" in check.reason.lower()


def test_terminal_state_blocks_redispatch(db, enforcer):
    """A CLOSED ticket should not accept further dispatches."""
    ticket = db.create_task("Done ticket")
    enforcer.mark_dispatched(ticket.id, "IMPLEMENT", objective="x")
    enforcer.mark_verified(ticket.id, accepted=True, summary="good")
    enforcer.close_ticket(ticket.id)

    check = enforcer.can_dispatch(ticket.id, "IMPLEMENT")
    assert not check.allowed
    assert "terminal" in check.reason.lower() or "CLOSED" in check.reason
