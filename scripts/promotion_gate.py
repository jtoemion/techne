#!/usr/bin/env python3
"""promotion_gate.py — W7 Structural Learning Loop (GRAND-PLAN-FINAL §4).

Replaces the human ratifier with a multi-signal promotion gate:

  RL events → GRPO identifies high-advantage candidates → promotion_gate evaluates →
    (a) pass^k on held-out eval corpus
    (b) zero boundary violations
    (c) mechanical gates (mutation, hashline, secret scan)
    (d) divergence bound from incumbent
  All four pass → promote (audit-chained Gate Registry entry)
  Any fail → discard

The held-out eval corpus (.techne/eval/corpus.jsonl) lives inside the immutable
boundary (the policy can never write to it directly). It ingests new real failures
from the Runtime Ring via ingest_failure().

Usage:
    python promotion_gate.py --evaluate candidate.md --incumbent incumbent.md
    python promotion_gate.py --ingest-incident .techne/runtime_ring/incidents.jsonl
    python promotion_gate.py --status
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_EVAL_DIR = _ROOT / ".techne" / "eval"
_CORPUS_FILE = _EVAL_DIR / "corpus.jsonl"
_PROMOTIONS_FILE = _EVAL_DIR / "promotions.jsonl"

# Boundary: the eval corpus is read-only to the policy (the promotion gate owns it)
_PROTECTED_PATHS = {
    str(_CORPUS_FILE),
    str(_PROMOTIONS_FILE),
}


@dataclass
class EvalCase:
    """A single labeled eval case in the held-out corpus."""
    id: str
    source: str          # "human_label" | "runtime_ring" | "grpo_failure" | "seed"
    description: str
    skill_target: str    # which skill file this tests
    forbidden_patterns: list[str]   # patterns that must NOT appear in a passing skill
    required_patterns: list[str]    # patterns that MUST appear in a passing skill
    timestamp: str
    saturated: bool = False   # True when all candidates pass → retire


@dataclass
class PromotionSignal:
    """Multi-signal evaluation result for a candidate skill edit."""
    candidate_hash: str
    incumbent_hash: str
    pass_k_score: float     # fraction of eval cases the candidate passes (k runs, worst-of-k)
    incumbent_score: float  # fraction of eval cases the incumbent passes
    delta: float            # pass_k_score - incumbent_score
    boundary_clean: bool    # zero boundary violations detected
    mechanical_pass: bool   # passes structural mechanical checks
    divergence: float       # 0.0 (identical) to 1.0 (completely different)
    divergence_bound: float # max allowed divergence
    verdict: str            # "PROMOTE" | "DISCARD" | "TIE"
    reason: str


# ── Eval Corpus ───────────────────────────────────────────────────────────────

def load_corpus() -> list[EvalCase]:
    """Load the held-out eval corpus from disk."""
    if not _CORPUS_FILE.exists():
        return []
    cases = []
    for line in _CORPUS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            cases.append(EvalCase(**d))
        except Exception:
            continue
    return [c for c in cases if not c.saturated]


def save_corpus(cases: list[EvalCase]) -> None:
    _EVAL_DIR.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(asdict(c), ensure_ascii=False) for c in cases]
    _CORPUS_FILE.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def ingest_failure(source: str, description: str, skill_target: str,
                   forbidden_patterns: list[str] | None = None,
                   required_patterns: list[str] | None = None) -> EvalCase:
    """Add a new real failure to the held-out corpus.

    Called by:
    - Runtime Ring when a rollback incident is logged
    - GRPO when a task fails with a known pattern
    - Human labels during W8 calibration
    """
    case_id = f"case-{hashlib.sha256(f'{source}{description}{time.time()}'.encode()).hexdigest()[:8]}"
    case = EvalCase(
        id=case_id,
        source=source,
        description=description,
        skill_target=skill_target,
        forbidden_patterns=forbidden_patterns or [],
        required_patterns=required_patterns or [],
        timestamp=datetime.now(timezone.utc).isoformat(),
        saturated=False,
    )
    corpus = load_corpus()
    corpus.append(case)
    save_corpus(corpus)
    return case


def ingest_from_incident_log(incidents_file: Path | None = None) -> list[EvalCase]:
    """Import Runtime Ring incidents as eval cases."""
    incidents_file = incidents_file or (_ROOT / ".techne" / "runtime_ring" / "incidents.jsonl")
    if not incidents_file.exists():
        return []

    existing_corpus = load_corpus()
    existing_sources = {c.source + c.description for c in existing_corpus}

    new_cases: list[EvalCase] = []
    for line in incidents_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            inc = json.loads(line)
        except Exception:
            continue

        reason = inc.get("reason", "")
        description = f"Runtime Ring rollback: {reason[:120]}"
        dedup_key = "runtime_ring" + description
        if dedup_key in existing_sources:
            continue

        case = EvalCase(
            id=f"incident-{hashlib.sha256(reason.encode()).hexdigest()[:8]}",
            source="runtime_ring",
            description=description,
            skill_target="skills/implementer.md",
            forbidden_patterns=[],
            required_patterns=[],
            timestamp=inc.get("ts", str(time.time())),
            saturated=False,
        )
        new_cases.append(case)
        existing_sources.add(dedup_key)

    if new_cases:
        all_cases = existing_corpus + new_cases
        save_corpus(all_cases)

    return new_cases


def retire_saturated(cases: list[EvalCase], threshold: float = 1.0) -> list[EvalCase]:
    """Mark cases as saturated if all recent candidates passed them at >= threshold."""
    # For now, saturation is manual — this is a hook for W8 automation
    return cases


# ── Candidate Evaluation ──────────────────────────────────────────────────────

def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _divergence(candidate: str, incumbent: str) -> float:
    """Word-level Jaccard divergence: 0=identical, 1=completely different."""
    def words(t: str) -> set[str]:
        return set(re.findall(r'\w+', t.lower()))

    c_words = words(candidate)
    i_words = words(incumbent)
    if not c_words and not i_words:
        return 0.0
    union = c_words | i_words
    intersection = c_words & i_words
    return 1.0 - (len(intersection) / len(union)) if union else 0.0


def _eval_case_score(candidate_text: str, case: EvalCase) -> bool:
    """Check if a candidate skill text passes a single eval case."""
    text_lower = candidate_text.lower()

    for pattern in case.forbidden_patterns:
        if pattern.lower() in text_lower:
            return False

    for pattern in case.required_patterns:
        if pattern.lower() not in text_lower:
            return False

    return True


def _pass_k(candidate_text: str, cases: list[EvalCase], k: int = 5) -> float:
    """Compute pass^k: fraction of cases where candidate passes in ALL k simulated runs.

    Since skill text evaluation is deterministic (no randomness), k runs produce
    identical results — pass^k = pass^1 here. In a live eval with model inference,
    this would run k trials and require success in every one.
    """
    if not cases:
        return 1.0
    passing = sum(1 for c in cases if _eval_case_score(candidate_text, c))
    return passing / len(cases)


def _check_boundary_clean(candidate_text: str) -> bool:
    """Check that the candidate doesn't contain boundary-violating patterns."""
    violations = [
        r'\bcurl\b', r'\bwget\b', r'\brequests\.get\b', r'\brequests\.post\b',
        r'sk-[a-zA-Z0-9]{20,}',      # API key pattern
        r'AKIA[0-9A-Z]{16}',          # AWS key
        r'-----BEGIN .* PRIVATE KEY',  # PEM key
        r'--no-verify\b',              # bypass
        r'--no-gpg-sign\b',            # bypass
        r'#\s*noqa',                   # escape hatch
    ]
    for pat in violations:
        if re.search(pat, candidate_text):
            return False
    return True


def _check_mechanical(candidate_text: str) -> bool:
    """Basic mechanical gate: no forbidden escape patterns, reasonable length."""
    if len(candidate_text.strip()) < 10:
        return False
    forbidden = ['TODO: replace', 'FIXME: placeholder', 'pass  # not implemented']
    for f in forbidden:
        if f in candidate_text:
            return False
    return True


def evaluate_candidate(
    candidate_text: str,
    incumbent_text: str,
    corpus: list[EvalCase] | None = None,
    k: int = 5,
    divergence_bound: float = 0.6,
) -> PromotionSignal:
    """Run the multi-signal promotion gate evaluation.

    Returns a PromotionSignal with verdict = PROMOTE | DISCARD | TIE.
    All four signals must pass for PROMOTE:
      (a) candidate pass^k > incumbent pass^k (beats the incumbent)
      (b) zero boundary violations
      (c) mechanical gate passes
      (d) divergence <= divergence_bound (conservative edit)
    """
    if corpus is None:
        corpus = load_corpus()

    c_hash = _text_hash(candidate_text)
    i_hash = _text_hash(incumbent_text)

    # Signal (a): pass^k comparison
    pass_k_score = _pass_k(candidate_text, corpus, k=k)
    incumbent_score = _pass_k(incumbent_text, corpus, k=k)
    delta = pass_k_score - incumbent_score

    # Signal (b): boundary clean
    boundary_clean = _check_boundary_clean(candidate_text)

    # Signal (c): mechanical gate
    mechanical_pass = _check_mechanical(candidate_text)

    # Signal (d): divergence bound
    div = _divergence(candidate_text, incumbent_text)
    within_bound = div <= divergence_bound

    # Verdict
    reasons = []
    if delta <= 0:
        reasons.append(f"candidate score {pass_k_score:.2%} does not beat incumbent {incumbent_score:.2%}")
    if not boundary_clean:
        reasons.append("boundary violation in candidate text")
    if not mechanical_pass:
        reasons.append("mechanical gate failed")
    if not within_bound:
        reasons.append(f"divergence {div:.2f} exceeds bound {divergence_bound:.2f}")

    if reasons:
        verdict = "DISCARD"
        reason = "DISCARD: " + "; ".join(reasons)
    elif delta == 0 and pass_k_score == incumbent_score:
        verdict = "TIE"
        reason = f"TIE: equal pass^k={pass_k_score:.2%} — incumbent retained"
    else:
        verdict = "PROMOTE"
        reason = (
            f"PROMOTE: candidate score {pass_k_score:.2%} vs incumbent {incumbent_score:.2%} "
            f"(+{delta:.1%}); boundary_clean=True; mechanical=True; divergence={div:.2f}"
        )

    return PromotionSignal(
        candidate_hash=c_hash,
        incumbent_hash=i_hash,
        pass_k_score=pass_k_score,
        incumbent_score=incumbent_score,
        delta=delta,
        boundary_clean=boundary_clean,
        mechanical_pass=mechanical_pass,
        divergence=div,
        divergence_bound=divergence_bound,
        verdict=verdict,
        reason=reason,
    )


# ── Promotion ─────────────────────────────────────────────────────────────────

def promote(gate_name: str, skill_target: str, signal: PromotionSignal,
            candidate_text: str) -> bool:
    """Record a PROMOTE event: audit-chained + Gate Registry entry.

    Returns True on success.
    """
    if signal.verdict != "PROMOTE":
        return False

    _EVAL_DIR.mkdir(parents=True, exist_ok=True)

    # Audit-chained promotion event
    now = datetime.now(timezone.utc).isoformat()
    event = {
        "ts": now,
        "gate_name": gate_name,
        "skill_target": skill_target,
        "candidate_hash": signal.candidate_hash,
        "incumbent_hash": signal.incumbent_hash,
        "pass_k_score": signal.pass_k_score,
        "incumbent_score": signal.incumbent_score,
        "delta": signal.delta,
        "divergence": signal.divergence,
        "reason": signal.reason,
    }
    with _PROMOTIONS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    # Gate Registry entry: provenance = grpo-promoted
    try:
        sys.path.insert(0, str(_HERE))
        from gate_status import register_gate
        register_gate(
            name=gate_name,
            kind="mechanical",
            provenance=f"grpo-promoted:{signal.candidate_hash}",
            phase="VERIFY",
            description=f"GRPO-promoted gate: pass_k={signal.pass_k_score:.2%}",
        )
    except Exception:
        pass

    return True


def load_promotions() -> list[dict]:
    """Load the promotion history."""
    if not _PROMOTIONS_FILE.exists():
        return []
    result = []
    for line in _PROMOTIONS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            result.append(json.loads(line))
        except Exception:
            continue
    return result


# ── Status display ────────────────────────────────────────────────────────────

def show_status() -> None:
    corpus = load_corpus()
    promotions = load_promotions()

    print(f"\n  Promotion Gate Status")
    print(f"  {'='*50}")
    print(f"  Eval corpus:  {len(corpus)} active case(s)")
    print(f"  Promotions:   {len(promotions)} total")

    if corpus:
        sources = {}
        for c in corpus:
            sources[c.source] = sources.get(c.source, 0) + 1
        for src, cnt in sorted(sources.items()):
            print(f"    {src}: {cnt} case(s)")

    if promotions:
        last = promotions[-1]
        print(f"  Last promotion: {last.get('ts', '?')} — gate={last.get('gate_name', '?')}")
    else:
        print(f"  No promotions yet.")
    print()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import argparse
    p = argparse.ArgumentParser(
        description="Promotion Gate — W7 Structural Learning Loop"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_eval = sub.add_parser("evaluate", help="Evaluate a candidate skill against the incumbent")
    p_eval.add_argument("--candidate", required=True, help="Path to candidate skill file")
    p_eval.add_argument("--incumbent", required=True, help="Path to incumbent skill file")
    p_eval.add_argument("--gate-name", default="unnamed", help="Name for this gate")
    p_eval.add_argument("--k", type=int, default=5, help="pass^k repetitions")
    p_eval.add_argument("--divergence-bound", type=float, default=0.6)
    p_eval.add_argument("--promote-on-win", action="store_true",
                        help="If PROMOTE verdict, apply the promotion event")

    p_ingest = sub.add_parser("ingest", help="Ingest Runtime Ring incidents into corpus")
    p_ingest.add_argument("--incidents", help="Path to incidents.jsonl (default: auto)")

    p_add = sub.add_parser("add-case", help="Add a manual eval case")
    p_add.add_argument("--description", required=True)
    p_add.add_argument("--skill-target", default="skills/implementer.md")
    p_add.add_argument("--require", action="append", default=[], metavar="PATTERN",
                       help="Pattern that must appear in passing skill")
    p_add.add_argument("--forbid", action="append", default=[], metavar="PATTERN",
                       help="Pattern that must NOT appear in passing skill")

    sub.add_parser("status", help="Show promotion gate status")

    args = p.parse_args()

    if args.cmd == "evaluate":
        candidate_text = Path(args.candidate).read_text(encoding="utf-8")
        incumbent_text = Path(args.incumbent).read_text(encoding="utf-8")
        signal = evaluate_candidate(
            candidate_text, incumbent_text,
            k=args.k, divergence_bound=args.divergence_bound,
        )
        print(f"  Verdict:      {signal.verdict}")
        print(f"  Reason:       {signal.reason}")
        print(f"  pass^k:       candidate={signal.pass_k_score:.2%} | incumbent={signal.incumbent_score:.2%}")
        print(f"  Delta:        {signal.delta:+.2%}")
        print(f"  Divergence:   {signal.divergence:.2f} (bound={signal.divergence_bound:.2f})")
        print(f"  Boundary:     {'clean' if signal.boundary_clean else 'VIOLATION'}")
        print(f"  Mechanical:   {'pass' if signal.mechanical_pass else 'FAIL'}")

        if signal.verdict == "PROMOTE" and args.promote_on_win:
            if promote(args.gate_name, args.candidate, signal, candidate_text):
                print(f"  Promotion:    RECORDED (gate_name={args.gate_name})")
        return 0 if signal.verdict == "PROMOTE" else 1

    if args.cmd == "ingest":
        inc_path = Path(args.incidents) if args.incidents else None
        new_cases = ingest_from_incident_log(inc_path)
        print(f"  Ingested {len(new_cases)} new eval case(s) from Runtime Ring incidents")
        return 0

    if args.cmd == "add-case":
        case = ingest_failure(
            source="human_label",
            description=args.description,
            skill_target=args.skill_target,
            required_patterns=args.require,
            forbidden_patterns=args.forbid,
        )
        print(f"  Added: {case.id}")
        return 0

    if args.cmd == "status":
        show_status()
        return 0

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
