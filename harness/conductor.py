"""
conductor.py — the state machine that runs the full pipeline.

The conductor is the only thing that calls agents AND enforces gates.
Agents cannot advance their own phase — only a passing gate does that.

Now integrates:
- Structured mistake logging (from jtoemion/harness-engineering-skills)
- Checkpoint enforcement (verification_logged flag)
- Skill routing (loads relevant skills per task)
- 7-question retro (from quick-retro format)

Usage:
    python harness/conductor.py "add WhatsApp button to product page"

Requires:
    pip install anthropic
    export ANTHROPIC_API_KEY=...
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from gates import GateViolation, run_all_gates
from sha_gate import gate_test_output
from mistakes import log_mistake, check_relevant, count_active
from evaluator import evaluate_pipeline_run
from checkpoint import (
    increment_pipeline_run,
    log_gate_pass,
    log_gate_fail,
    mark_verified,
    check_verification,
    get_summary,
)
from router import route, get_always_loaded
from session import new_session
from measure import run_measurements, full_intent_check
from intent_reasoner import verdict_to_gate
from apply_retro import has_pending_proposals

HARNESS_DIR = Path(__file__).parent        # techne/harness/
ROOT = HARNESS_DIR.parent                  # techne/
SKILLS_DIR = ROOT / "skills"
AGENTS_DIR = ROOT / "agents"
MEMORY_DIR = ROOT / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

MAX_RETRIES = 3
MODEL = "claude-sonnet-4-6"


# ─── Helpers ────────────────────────────────────────────────────────────────────

def _read_skill_files(task: str = "") -> str:
    """Read skill files — always-loaded + task-relevant via router."""
    loaded = set()
    parts = []

    # Always-loaded skills (nextjs.md, typescript.md)
    for rel_path in get_always_loaded():
        full = ROOT / rel_path
        if full.exists() and full.name not in loaded:
            parts.append(f"=== {full.name} [always-loaded] ===\n{full.read_text(encoding='utf-8')}")
            loaded.add(full.name)

    # Task-routed skill
    if task:
        matched = route(task)
        if matched:
            skill_path = ROOT / matched.get("skill_path", "")
            if skill_path.exists() and skill_path.name not in loaded:
                parts.append(f"=== {skill_path.name} [routed: {matched['id']}] ===\n{skill_path.read_text(encoding='utf-8')}")
                loaded.add(skill_path.name)

    # Fallback: load any remaining skill files not yet included
    for md in sorted(SKILLS_DIR.glob("*.md")):
        if md.name not in loaded:
            parts.append(f"=== {md.name} ===\n{md.read_text(encoding='utf-8')}")

    return "\n\n".join(parts)


def _surface_relevant_mistakes(task: str) -> str:
    """Check mistakes.md for lessons relevant to this task."""
    relevant = check_relevant(task)
    if not relevant:
        return ""

    lines = [f"[CONDUCTOR] {len(relevant)} relevant mistake(s) found:"]
    for entry in relevant[:3]:
        lines.append(f"  - {entry['error'][:80]}")
        lines.append(f"    Lesson: {entry['lesson'][:80]}")

    return "\n".join(lines)


def _call_agent(system_prompt: str, user_message: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def _read_agent_prompt(agent_name: str) -> str:
    path = AGENTS_DIR / f"{agent_name}.md"
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        _, _, body = text.partition("---\n")
        _, _, body = body.partition("---\n")
        return body.strip()
    return text.strip()


# ─── Phase runners ───────────────────────────────────────────────────────────────

def phase_implement(task: str, retries: int = 0) -> str:
    print(f"\n[CONDUCTOR] === IMPLEMENT (attempt {retries+1}/{MAX_RETRIES}) ===")

    if retries >= MAX_RETRIES:
        raise RuntimeError(f"IMPLEMENT failed after {MAX_RETRIES} attempts")

    skills = _read_skill_files(task)

    # Surface relevant past mistakes
    mistakes_context = _surface_relevant_mistakes(task)
    if mistakes_context:
        print(mistakes_context)

    system = _read_agent_prompt("implementer")
    user_msg = textwrap.dedent(f"""
        Task: {task}

        Skill rules in effect:
        {skills}

        {f"Past mistakes relevant to this task:{chr(10)}{mistakes_context}" if mistakes_context else ""}

        Return the unified diff only.
    """).strip()

    diff = _call_agent(system, user_msg)
    (MEMORY_DIR / "implementer_output.txt").write_text(diff, encoding="utf-8")

    try:
        run_all_gates(diff)
        log_gate_pass("all_gates")
        print("[CONDUCTOR] IMPLEMENT passed all gates")
        return diff
    except GateViolation as e:
        gate_name = str(e).split("[")[1].split("]")[0] if "[" in str(e) else "unknown"
        print(f"[CONDUCTOR] IMPLEMENT gate failed: {e}")
        log_gate_fail(gate_name, str(e))
        log_mistake(
            phase="IMPLEMENT",
            error=str(e)[:200],
            cause="agent violated skill rule",
            lesson="pending retro",
            gate=gate_name,
        )

        feedback_msg = textwrap.dedent(f"""
            Your previous diff was rejected by the gate:

            {e}

            Fix only the specific violation above. Return the corrected unified diff.
        """).strip()
        corrected = _call_agent(system, feedback_msg)
        (HARNESS_DIR / "implementer_output.txt").write_text(corrected, encoding="utf-8")

        try:
            run_all_gates(corrected)
            log_gate_pass("all_gates_retry")
            print("[CONDUCTOR] IMPLEMENT passed gates after retry")
            return corrected
        except GateViolation as e2:
            log_gate_fail(gate_name, str(e2))
            log_mistake(
                phase="IMPLEMENT",
                error=str(e2)[:200],
                cause="agent failed same rule on retry",
                lesson="pending retro",
                gate=gate_name,
            )
            return phase_implement(task, retries + 1)


def phase_verify(diff: str) -> str:
    print(f"\n[CONDUCTOR] === VERIFY ===")

    system = _read_agent_prompt("verifier")
    user_msg = textwrap.dedent(f"""
        The following diff was produced by the implementer and passed code gates.
        Run the test suite now. Write full stdout to test_output.txt.

        Diff (for context only — do not re-apply it):
        {diff[:2000]}
    """).strip()

    _call_agent(system, user_msg)

    sha = gate_test_output(
        test_output_path=str(MEMORY_DIR / "test_output.txt"),
        run_log_path=str(MEMORY_DIR / "run_log.json"),
    )
    log_gate_pass("sha_gate")
    mark_verified(sha)
    print(f"[CONDUCTOR] VERIFY passed — SHA: {sha[:16]}...")
    return sha


def phase_review(diff: str, sha: str) -> str:
    print(f"\n[CONDUCTOR] === REVIEW ===")

    system = _read_agent_prompt("reviewer")
    user_msg = textwrap.dedent(f"""
        Review the following diff. Tests passed (SHA: {sha[:16]}...).

        Diff:
        {diff}
    """).strip()

    findings = _call_agent(system, user_msg)
    print(f"[CONDUCTOR] Review result:\n{findings[:400]}")

    if "HARD_FAIL" in findings:
        log_gate_fail("review", "HARD_FAIL in review findings")
        raise GateViolation(f"REVIEW hard fail:\n{findings}")

    log_gate_pass("review")
    return findings


def phase_retro():
    print(f"\n[CONDUCTOR] === RETRO ===")

    system = _read_agent_prompt("retro")
    mistakes = (MEMORY_DIR / "mistakes.md").read_text(encoding="utf-8") if (MEMORY_DIR / "mistakes.md").exists() else "(none)"

    user_msg = f"Run the 7-question retro and skill file analysis.\n\nmistakes.md content:\n{mistakes}"
    _call_agent(system, user_msg)
    print("[CONDUCTOR] RETRO complete — see harness/memory/retro_proposals.md")


# ─── Main pipeline ───────────────────────────────────────────────────────────────

def run_pipeline(task: str):
    run_number = increment_pipeline_run()
    active_mistakes = count_active()

    print(f"\n[CONDUCTOR] Starting pipeline #{run_number}: {task}")
    print(f"[CONDUCTOR] Active mistakes: {active_mistakes}")

    # Route the task
    matched_skill = route(task)
    if matched_skill:
        print(f"[CONDUCTOR] Skill routed: {matched_skill['id']} ({matched_skill.get('skill_path', '')})")
    else:
        print(f"[CONDUCTOR] No specific skill matched — loading all rules")

    print("=" * 60)

    results: dict[str, str] = {}

    # Warn if unapplied retro proposals exist — the loop doesn't close otherwise
    pending_proposals = has_pending_proposals()
    if pending_proposals:
        print(f"[CONDUCTOR] ⚠ {pending_proposals} unapplied retro proposal(s) in memory/retro_proposals.md")
        print(f"[CONDUCTOR]   Run: python harness/apply_retro.py")

    # Eval metrics — start with known defaults, update with real measurements after diff
    eval_metrics = {
        "gate_violations": 0,
        "retries_used": 0,
        "pipeline_halted": False,
        "sha_passed": False,
        "hash_unique": True,
        "output_existed": False,
        "had_pass_indicators": False,
        "skills_loaded": True,  # always-loaded files guarantee this
        "mistakes_consulted": active_mistakes > 0,
        "diff_focused": True,    # measured below after diff is produced
        "scope_creep": False,    # measured below after diff is produced
        "review_result": "SKIPPED",
        "shadow_gate_clean": True,
        "drift_markers": 0,
        "retro_ran": False,
        "retro_proposals": False,
        "retro_questions": 0,
    }

    try:
        diff = phase_implement(task)
        results["implement"] = "PASS"

        # ── Fix 1+2: real measurements, L2/L3 intent gate ────────────────
        measurements = run_measurements(task, diff)
        eval_metrics["diff_focused"] = measurements["diff_focused"]
        eval_metrics["scope_creep"] = measurements["scope_creep"]

        intent = measurements["_intent"]
        # Fix 1: use l1_score, not "score" (was crashing with KeyError)
        l1_score = intent.get("l1_score", 0.0)
        print(f"[CONDUCTOR] Intent check: {intent['warning']}"
              + (" ⚠" if l1_score < 0.5 else ""))

        # Fix 2: wire the L2/L3 reasoner — verdict_to_gate acts on the
        # structured verdict, not just keyword overlap
        try:
            verdict_to_gate(intent, task)  # MISMATCH ≥70% → GateViolation
        except GateViolation as eg:
            print(f"[CONDUCTOR] ⚠ Intent gate: {eg}")
            eval_metrics["diff_focused"] = False
            log_mistake(
                phase="IMPLEMENT",
                error=f"Intent gate: {intent.get('verdict', 'MISMATCH')}",
                cause=intent.get("reason", ""),
                lesson="diff did not implement the stated task",
                gate="intent",
            )
            raise  # halt — this is a real mismatch, not advisory

        sha = phase_verify(diff)
        results["verify"] = f"PASS (sha: {sha[:16]}...)"
        eval_metrics["sha_passed"] = True
        eval_metrics["output_existed"] = True
        eval_metrics["had_pass_indicators"] = True

        findings = phase_review(diff, sha)
        review_outcome = "PASS" if "HARD_FAIL" not in findings else "SOFT_FAIL"
        results["review"] = review_outcome
        eval_metrics["review_result"] = review_outcome
        eval_metrics["shadow_gate_clean"] = (
            "SHADOW GATE CHECK: clean" in findings
            or "shadow" not in findings.lower()
        )
        # Fix 4: count drift markers in the DIFF, not the reviewer's report
        # (reviewer.md template itself contains these words — wrong artifact)
        diff_lower = diff.lower()
        eval_metrics["drift_markers"] = (
            diff_lower.count("+  todo")
            + diff_lower.count("+ // todo")
            + diff_lower.count("+  fixme")
            + diff_lower.count("+ // fixme")
            + diff_lower.count("+ console.log")
            + diff_lower.count("+console.log")
        )

    # Fix 5: catch unexpected errors — degrade gracefully, don't crash
    except (GateViolation, RuntimeError) as e:
        results.setdefault("implement", "FAIL")
        results.setdefault("verify", "FAIL")
        results.setdefault("review", "FAIL")
        eval_metrics["pipeline_halted"] = True
        print(f"\n[CONDUCTOR] Pipeline halted (expected): {e}")

    except Exception as e:
        results.setdefault("implement", "ERROR")
        results.setdefault("verify", "ERROR")
        results.setdefault("review", "ERROR")
        eval_metrics["pipeline_halted"] = True
        print(f"\n[CONDUCTOR] Pipeline crashed (unexpected {type(e).__name__}): {e}")
        log_mistake(
            phase="CONDUCTOR",
            error=f"{type(e).__name__}: {e}",
            cause="unexpected exception — check the seam between phases",
            lesson=f"add a test that exercises this code path without API key",
            gate="none",
        )

    finally:
        # Retro runs regardless — but must not propagate its own failures
        try:
            phase_retro()
            eval_metrics["retro_ran"] = True
            eval_metrics["retro_questions"] = 7
        except Exception as retro_err:
            print(f"[CONDUCTOR] Retro failed ({type(retro_err).__name__}): {retro_err}")
            eval_metrics["retro_ran"] = False

    # Checkpoint enforcement
    verified = check_verification()

    print("\n" + "=" * 60)
    print(f"PIPELINE #{run_number}: {task}")
    for phase, status in results.items():
        print(f"  {phase.upper():10}: {status}")
    print(f"  {'VERIFIED':10}: {'YES' if verified else 'NO — do not claim completion'}")
    print("=" * 60)
    print(f"\n{get_summary()}")

    # ─── EVALUATION REPORT ────────────────────────────────────────────
    eval_report = evaluate_pipeline_run(
        task=task,
        pipeline_number=run_number,
        **eval_metrics,
    )
    print(eval_report.format_report())

    # ─── SESSION LOG ──────────────────────────────────────────────────
    session = new_session(agent_tool="claude-code")
    session.set_task(task)
    session.set_pipeline_result(
        pipeline_number=run_number,
        implement=results.get("implement", "PENDING"),
        verify=results.get("verify", "PENDING"),
        review=results.get("review", "PENDING"),
        sha=eval_metrics.get("sha_passed") and
            (MEMORY_DIR / "run_log.json").exists() and
            str(json.loads((MEMORY_DIR / "run_log.json").read_text())[-1].get("test_output_hash", "")[:16] + "...")
            or "none",
    )
    intent_summary = measurements.get("_intent", {}).get("warning", "") if "measurements" in dir() else ""
    session.set_eval(
        score=eval_report.total,
        grade=eval_report.grade,
        summary=f"{eval_report.behavior_actual} {intent_summary}".strip(),
    )

    # Surface active mistakes as handoff notes
    relevant = check_relevant(task)
    for m in relevant[:3]:
        session.add_mistake(m.get("gate", "unknown"), m.get("lesson", ""))

    # Recommendations become open questions if score < 75
    if eval_report.total < 75:
        for rec in eval_report.recommendations:
            session.add_question(rec)

    # Handoff note
    if verified:
        session.add_handoff(f"Pipeline #{run_number} complete and verified. Ready for next task.")
    else:
        session.add_handoff(f"Pipeline #{run_number} did not complete verification. Do not claim done.")

    session_path = session.save()
    print(f"\n[CONDUCTOR] Session log saved → {session_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the agent pipeline")
    parser.add_argument("task", help="Task description for the implementer agent")
    args = parser.parse_args()

    if "ANTHROPIC_API_KEY" not in os.environ:
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)

    run_pipeline(args.task)
