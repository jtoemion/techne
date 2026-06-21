"""
test_prompt_proposals.py — the propose / validate / ratify staging gate.

prompt_evolution used to mutate a winning prompt and inject it straight into the
active variant pool (score-driven auto-edit). This drives the replacement:
proposals are staged, structurally validated (eval-suite gate), and only a human
ratification promotes them — recurrence-gated + structurally-gated +
human-approved, never score-driven auto-promotion.

Run from tests/:  python test_prompt_proposals.py
"""

import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

from reward_log import RewardLog
from prompt_evolution import PromptEvolution

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []


def check(label, cond):
    results.append(bool(cond))
    print(f"  {PASS if cond else FAIL} {label}")


def _fresh_evo(with_winner=True):
    """A PromptEvolution over a temp reward log + temp proposals/variants files."""
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db.close()
    proposals = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    proposals.close()
    variants = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    variants.close()
    log = RewardLog(db.name)
    if with_winner:
        # 3 clean runs on v1_strict → it becomes the best_variant for "auth"
        for i in range(3):
            log.record(
                task_id=f"t{i}", task_type="auth", prompt_variant="v1_strict",
                gate_pass=True, test_pass=True,
                review_findings=[], critique_predictions=[],
                scope_clean=True, attempt_count=1,
            )
    evo = PromptEvolution(log, proposals_path=proposals.name, variants_path=variants.name)
    return evo, log, Path(db.name), Path(proposals.name)


def test_propose_stages_without_activating():
    print("\n[propose — stages a candidate, does NOT activate it]")
    evo, log, db, pf = _fresh_evo()
    before = set(evo.variants.get("implementer", {}))
    p = evo.propose("auth", "implementer")
    check("propose returns a Proposal", p is not None)
    check("proposal starts pending", p.status == "pending")
    check("proposed variant is NOT in the active pool",
          p.variant_name not in evo.variants.get("implementer", {}))
    check("active pool is unchanged by propose",
          set(evo.variants.get("implementer", {})) == before)
    log.close(); db.unlink(); pf.unlink()


def test_propose_persists():
    print("\n[propose — proposal survives to a new instance via the log]")
    evo, log, db, pf = _fresh_evo()
    p = evo.propose("auth", "implementer")
    # Fresh instance pointed at the same proposals file
    evo2 = PromptEvolution(log, proposals_path=str(pf))
    again = evo2.get_proposal(p.id)
    check("proposal is retrievable by id from a new instance", again is not None)
    check("round-trips the variant name", again and again.variant_name == p.variant_name)
    check("listed under pending", any(x.id == p.id for x in evo2.list_proposals(status="pending")))
    log.close(); db.unlink(); pf.unlink()


def test_propose_needs_recurrence():
    print("\n[propose — recurrence gate: no winner, no proposal]")
    evo, log, db, pf = _fresh_evo(with_winner=False)
    p = evo.propose("auth", "implementer")
    check("propose returns None without enough data", p is None)
    check("nothing written to the proposals log", evo.list_proposals() == [])
    log.close(); db.unlink(); pf.unlink()


def test_propose_is_idempotent_while_open():
    print("\n[propose — does not stack duplicate open proposals]")
    evo, log, db, pf = _fresh_evo()
    p1 = evo.propose("auth", "implementer")
    p2 = evo.propose("auth", "implementer")
    check("second propose returns the same open proposal", p1.id == p2.id)
    check("only one proposal in the log",
          len([x for x in evo.list_proposals() if x.variant_name == p1.variant_name]) == 1)
    # Once it's resolved (rejected), a fresh propose may open a new one.
    evo.validate(p1, scorer=lambda cfg: 0.0)  # → rejected
    p3 = evo.propose("auth", "implementer")
    check("a new proposal opens after the prior one is resolved", p3.id != p1.id)
    log.close(); db.unlink(); pf.unlink()


def test_validate_is_structural_gate_only():
    print("\n[validate — marks validated/rejected, never promotes]")
    evo, log, db, pf = _fresh_evo()
    p = evo.propose("auth", "implementer")

    # candidate beats incumbent → validated
    passing = evo.validate(p, scorer=lambda cfg: 1.0)
    check("high score → validated", passing.status == "validated")
    check("validate does not activate the variant",
          p.variant_name not in evo.variants.get("implementer", {}))

    # a fresh proposal that regresses → rejected
    p2 = evo.propose("auth", "implementer")
    failing = evo.validate(p2, scorer=lambda cfg: 0.0)
    check("low score → rejected", failing.status == "rejected")
    check("rejected variant is not activated",
          p2.variant_name not in evo.variants.get("implementer", {}))
    log.close(); db.unlink(); pf.unlink()


def test_ratify_promotes_only_validated():
    print("\n[ratify — human step promotes a validated proposal]")
    evo, log, db, pf = _fresh_evo()
    p = evo.propose("auth", "implementer")
    evo.validate(p, scorer=lambda cfg: 1.0)
    ok = evo.ratify(p.id, approved=True)
    check("ratify returns True", ok is True)
    check("ratified variant enters the active pool",
          p.variant_name in evo.variants.get("implementer", {}))
    check("status recorded as ratified",
          evo.get_proposal(p.id).status == "ratified")
    log.close(); db.unlink(); pf.unlink()


def test_ratify_refuses_unvalidated():
    print("\n[ratify — structural gate: cannot promote a pending proposal]")
    evo, log, db, pf = _fresh_evo()
    p = evo.propose("auth", "implementer")  # never validated
    ok = evo.ratify(p.id, approved=True)
    check("ratify refuses (returns False) without validation", ok is False)
    check("pending proposal is not activated",
          p.variant_name not in evo.variants.get("implementer", {}))
    log.close(); db.unlink(); pf.unlink()


def test_ratify_reject_path():
    print("\n[ratify — human rejection marks rejected, never promotes]")
    evo, log, db, pf = _fresh_evo()
    p = evo.propose("auth", "implementer")
    evo.validate(p, scorer=lambda cfg: 1.0)
    ok = evo.ratify(p.id, approved=False)
    check("ratify(approved=False) returns False", ok is False)
    check("rejected by human → not activated",
          p.variant_name not in evo.variants.get("implementer", {}))
    check("status recorded as rejected",
          evo.get_proposal(p.id).status == "rejected")
    log.close(); db.unlink(); pf.unlink()


def test_ratify_writes_to_isolated_variants_path():
    """Two instances with different variants_path stay isolated — P2 fix."""
    print("\n[ratify — variants_path isolation: ratifying one doesn't touch the other]")
    # Setup: two evo instances, each with its own temp proposals + variants file.
    evo1, log1, db1, pf1 = _fresh_evo()
    evo2, log2, db2, pf2 = _fresh_evo()

    # Ratify a proposal in evo1.
    p1 = evo1.propose("auth", "implementer")
    evo1.validate(p1, scorer=lambda cfg: 1.0)
    ok = evo1.ratify(p1.id, approved=True)
    check("ratify succeeded for evo1", ok is True)
    check("evo1's ratified variant is in evo1 pool",
          p1.variant_name in evo1.variants.get("implementer", {}))

    # evo2 should NOT see evo1's ratified variant.
    check("evo2's pool is unchanged (no cross-contamination)",
          p1.variant_name not in evo2.variants.get("implementer", {}))

    log1.close(); db1.unlink(); pf1.unlink()
    log2.close(); db2.unlink(); pf2.unlink()


def test_evolve_no_longer_auto_activates():
    print("\n[evolve — back-compat shim now stages instead of auto-activating]")
    evo, log, db, pf = _fresh_evo()
    name = evo.evolve("auth", "implementer")
    check("evolve still returns a variant name", isinstance(name, str) and name)
    check("evolve no longer injects into the active pool",
          name not in evo.variants.get("implementer", {}))
    check("evolve left a pending proposal instead",
          any(x.status == "pending" for x in evo.list_proposals()))
    log.close(); db.unlink(); pf.unlink()


if __name__ == "__main__":
    print("=" * 60)
    print("PROMPT PROPOSALS (propose / validate / ratify) — TEST")
    print("=" * 60)
    test_propose_stages_without_activating()
    test_propose_persists()
    test_propose_needs_recurrence()
    test_propose_is_idempotent_while_open()
    test_validate_is_structural_gate_only()
    test_ratify_promotes_only_validated()
    test_ratify_refuses_unvalidated()
    test_ratify_reject_path()
    test_evolve_no_longer_auto_activates()
    test_ratify_writes_to_isolated_variants_path()
    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed" + ("  -- all clear" if passed == total else f"  ({total-passed} FAILED)"))
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
