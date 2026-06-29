"""main.py — Techne CLI entry point."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ok(s):   return f"\033[92m✓\033[0m {s}"
def _warn(s): return f"\033[93m⚠\033[0m {s}"
def _fail(s): return f"\033[91m✗\033[0m {s}"
def _bold(s): return f"\033[1m{s}\033[0m"


def cmd_init(args):
    """Initialize a new task in RECALL phase."""
    from techne_cli.core import create_initial_state, state_path, artifact_path_for

    cwd = Path.cwd()
    sp = state_path(cwd)
    if sp.exists() and not args.force:
        print(f"Error: active pipeline already exists at {sp}")
        print("Use --force to overwrite, or run `techne status` to inspect.")
        sys.exit(1)

    techne_dir = cwd / ".techne"
    for sub in ["loop", "audit", "memory", "events", "context"]:
        (techne_dir / sub).mkdir(parents=True, exist_ok=True)

    state = create_initial_state(args.task_id, cwd=cwd)
    print(f"Task '{state.task_id}' initialized in RECALL phase")
    print()
    print("Next steps:")
    recall_artifact = artifact_path_for("RECALL", cwd)
    print(f"  1. Write your RECALL artifact:")
    print(f"       {recall_artifact}")
    print(f"     Must contain a 'WORKSHOP_CONTEXT:' header listing context files used.")
    print(f"  2. Run: techne next")


def cmd_next(args):
    """Advance the pipeline one phase."""
    repo = _repo_root()
    next_py = repo / "scripts" / "next.py"
    if not next_py.exists():
        print(f"Error: scripts/next.py not found at {next_py}")
        sys.exit(1)

    import importlib.util
    spec = importlib.util.spec_from_file_location("next_module", next_py)
    mod = importlib.util.module_from_spec(spec)
    sys.argv = ["next.py"]
    if getattr(args, "strict_nodes", False):
        sys.argv.append("--strict-nodes")
    if getattr(args, "strict_mutation", False):
        sys.argv.append("--strict-mutation")
    if getattr(args, "phase_mode", None):
        sys.argv += ["--phase-mode", args.phase_mode]
    spec.loader.exec_module(mod)
    sys.exit(mod.main())


def cmd_gates(args):
    """Show the Gate Registry — per-gate kind, provenance, status, catch-rate."""
    repo = _repo_root()
    gate_status_py = repo / "scripts" / "gate_status.py"
    for p in [str(repo / "scripts"), str(repo / "harness")]:
        if p not in sys.path:
            sys.path.insert(0, p)

    from gate_status import get_registry, format_registry, register_gate, record_outcome

    if args.record:
        name, outcome = args.record
        if outcome not in ("caught", "passed"):
            print(f"outcome must be 'caught' or 'passed', got: {outcome}")
            sys.exit(1)
        record_outcome(name, caught=(outcome == "caught"))
        print(f"  Recorded: {name} -> {outcome}")
        return

    if args.register:
        register_gate(args.register, args.kind, args.provenance,
                      args.phase, args.description)
        print(f"  Registered: {args.register} ({args.kind})")
        return

    registry = get_registry()
    if args.json:
        print(json.dumps(registry, indent=2, ensure_ascii=False))
    else:
        print(format_registry(registry))


def cmd_status(args):
    """Show current pipeline state."""
    from techne_cli.core import read_state

    cwd = Path.cwd()
    state = read_state(cwd)
    if state is None:
        print("No active pipeline.")
        print("Run: techne init <task-id>")
        sys.exit(0)

    print(_bold("Techne Pipeline Status"))
    print("─" * 40)
    print(f"  Task:    {state.task_id}")
    print(f"  Phase:   {state.phase}")
    print(f"  Updated: {state.updated_at}")

    if state.is_terminal():
        print(_ok("Pipeline DONE"))
    else:
        stale_min = (datetime.now(timezone.utc).timestamp() -
                     datetime.fromisoformat(state.updated_at).timestamp()) / 60
        if stale_min > state.phase_timeout_min:
            print(_warn(f"STALLED — {stale_min:.0f}m in {state.phase} (limit {state.phase_timeout_min}m)"))
        else:
            print(_ok(f"Active — {stale_min:.0f}m in current phase"))

    blocked_log = cwd / ".techne" / "audit" / "blocked.log"
    if blocked_log.exists():
        lines = [l for l in blocked_log.read_text().splitlines() if l.strip()]
        if lines:
            print(f"\n  Blocked writes (last 3):")
            for l in lines[-3:]:
                print(f"    {l}")

    rl_log = cwd / ".techne" / "events" / "rl.jsonl"
    if rl_log.exists():
        entries = [json.loads(l) for l in rl_log.read_text().splitlines() if l.strip()]
        if entries:
            print(f"\n  RL events: {len(entries)} total")
            last = entries[-1]
            print(f"  Last: reward={last.get('reward','?')} advantage={last.get('advantage','?')}")


def cmd_handoff(args):
    """Write a handoff document and print it for session continuity."""
    from techne_cli.core import read_state, read_entries, PHASE_SEQUENCE

    cwd = Path.cwd()
    state = read_state(cwd)

    if state is None:
        print("No active pipeline — nothing to hand off.")
        sys.exit(0)

    # Audit chain phases completed
    try:
        entries = read_entries()
        phases_done = [e.phase for e in entries if e.task_id == state.task_id]
    except Exception:
        phases_done = []

    # RL health
    rl_log = cwd / ".techne" / "events" / "rl.jsonl"
    rl_entries = []
    if rl_log.exists():
        for line in rl_log.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                try:
                    rl_entries.append(json.loads(line))
                except Exception:
                    pass

    # Artifact inventory
    loop_dir = cwd / ".techne" / "loop"
    artifact_names = ["recall.txt", "diff.txt", "test_output.txt", "conclude.txt"]
    artifacts = {}
    for name in artifact_names:
        p = loop_dir / name
        if p.exists() and p.stat().st_size > 0:
            artifacts[name] = p.stat().st_size

    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    _next_reqs = {
        "RECALL":    [
            "Write `.techne/loop/recall.txt` with `WORKSHOP_CONTEXT:` header",
            "Run: `techne next`",
        ],
        "IMPLEMENT": [
            "Make code changes",
            "Run: `git diff > .techne/loop/diff.txt`",
            "Run: `techne next`",
        ],
        "VERIFY":    [
            "Run: `pytest > .techne/loop/test_output.txt`",
            "Run: `techne next`",
        ],
        "CONCLUDE":  [
            "Write `.techne/loop/conclude.txt` with Honcho ID",
            "Run: `techne next`",
        ],
        "DONE":      ["Pipeline complete — nothing left to do."],
    }
    reqs = _next_reqs.get(state.phase, [f"Complete the {state.phase} phase, then `techne next`"])

    doc_lines = [
        f"# Techne Handoff — {state.task_id}",
        f"",
        f"Generated: {now_str}  |  Project: {cwd.name}",
        f"",
        f"## Current State",
        f"",
        f"| Field | Value |",
        f"|---|---|",
        f"| Task | `{state.task_id}` |",
        f"| Phase | **{state.phase}** |",
        f"| Updated | {state.updated_at} |",
        f"| Terminal | {'Yes — DONE' if state.is_terminal() else 'No'} |",
        f"",
    ]

    if phases_done:
        doc_lines += [
            "## Phases Completed (audit chain)",
            "",
            *[f"- {p}" for p in phases_done],
            "",
        ]

    if artifacts:
        doc_lines += [
            "## Artifacts On Disk",
            "",
            *[f"- `.techne/loop/{name}` — {size} bytes" for name, size in artifacts.items()],
            "",
        ]

    if rl_entries:
        last = rl_entries[-1]
        doc_lines += [
            "## RL Health",
            "",
            f"- Events logged: {len(rl_entries)}",
            f"- Last reward: {last.get('reward', '?')}",
            f"- Last advantage: {last.get('advantage', '?')}",
            "",
        ]

    doc_lines += [
        "## Next Action",
        "",
        *[f"- {r}" for r in reqs],
        "",
        "## Resume Commands",
        "",
        "```bash",
        f"cd {cwd}",
        "techne status   # confirm current state",
        f"# complete {state.phase} requirements above",
        "techne next",
        "```",
        "",
    ]

    doc = "\n".join(doc_lines)

    handoff_path = loop_dir / "handoff.md"
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text(doc, encoding="utf-8")

    print(_bold(f"Handoff written → {handoff_path}"))
    print()
    print(doc)


def cmd_gate(args):
    """Run a named gate check: hashline, forbidden, or audit."""
    # Ensure scripts/ and harness/ are on sys.path
    _gate_repo = _repo_root()
    for _p in [str(_gate_repo / "scripts"), str(_gate_repo / "harness")]:
        if _p not in sys.path:
            sys.path.insert(0, _p)
    from hash_gate import validate_diff_context
    from next import _check_no_forbidden_patterns, GateResult
    from audit_chain import append_entry, AuditEntry

    if args.name == "hashline":
        diff_text = Path(args.target).read_text(encoding="utf-8")
        passed, detail = validate_diff_context(diff_text)
        if passed:
            print(_ok(f"hashline: {detail}"))
            sys.exit(0)
        else:
            print(_fail(f"hashline: {detail}"))
            sys.exit(1)

    elif args.name == "forbidden":
        results = _check_no_forbidden_patterns(Path(args.target))
        failures = [r for r in results if not r.passed]
        if not failures:
            print(_ok("no forbidden patterns detected"))
            sys.exit(0)
        for r in failures:
            print(_fail(f"forbidden: {r.name} — {r.detail}"))
        sys.exit(1)

    elif args.name == "audit":
        event = json.loads(args.target)
        # Build AuditEntry with sensible defaults for required fields
        entry = AuditEntry(
            seq=event.get("seq", 0),
            timestamp=event.get("timestamp", datetime.now(timezone.utc).isoformat()),
            task_id=event.get("task_id", ""),
            phase=event.get("phase", ""),
            gates=event.get("gates", []),
            summary=event.get("summary", ""),
            prev_hash=event.get("prev_hash", ""),
        )
        entry_hash = append_entry(entry)
        print(f"entry_hash={entry_hash}")
        sys.exit(0)


def cmd_doctor(args):
    """Run a 6-category health check."""
    from techne_cli.core import read_state, verify_chain

    cwd = Path.cwd()
    print(f"\n{_bold('Techne Doctor')}\n" + "─" * 40)

    # 1. .techne/ exists
    techne_dir = cwd / ".techne"
    if techne_dir.is_dir():
        print(_ok(".techne/ directory found"))
    else:
        print(_fail(".techne/ not found — run: techne init <task-id>"))

    # 2. state.json + stall check
    state = read_state(cwd)
    if state is None:
        print(_warn("No active pipeline (no state.json)"))
    elif state.is_terminal():
        print(_ok(f"Pipeline DONE — task: {state.task_id}"))
    else:
        stale_min = (datetime.now(timezone.utc).timestamp() -
                     datetime.fromisoformat(state.updated_at).timestamp()) / 60
        if stale_min > state.phase_timeout_min:
            print(_warn(f"Pipeline STALLED in {state.phase} for {stale_min:.0f}m"))
        else:
            print(_ok(f"Pipeline active — phase={state.phase}, task={state.task_id}"))

    # 3. Audit chain
    try:
        ok_chain, msg = verify_chain()
        print(_ok("Audit chain intact") if ok_chain else _fail(f"Audit chain BROKEN: {msg}"))
    except Exception as e:
        print(_warn(f"Audit chain unreadable: {e}"))

    # 4. Pending GRPO proposals
    proposals_dir = cwd / ".techne" / "proposals"
    if proposals_dir.exists():
        count = len(list(proposals_dir.glob("*.md")))
        if count:
            print(_warn(f"{count} pending GRPO proposal(s) — review with apply_retro.py"))
        else:
            print(_ok("No pending GRPO proposals"))
    else:
        print(_ok("No proposals directory"))

    # 5. Context pack freshness
    digest = cwd / ".techne" / "context" / "project_digest.md"
    if digest.exists():
        age_h = (datetime.now().timestamp() - os.path.getmtime(digest)) / 3600
        if age_h > 24:
            print(_warn(f"Context pack is {age_h:.0f}h old — run: python3 harness/context_build.py"))
        else:
            print(_ok(f"Context pack fresh ({age_h:.1f}h old)"))
    else:
        print(_warn("No context pack — run: python3 harness/context_build.py"))

    # 6. PreToolUse hook
    hook_found = False
    for settings_path in [cwd / ".claude" / "settings.json",
                           Path.home() / ".claude" / "settings.json"]:
        if settings_path.exists():
            try:
                s = json.loads(settings_path.read_text())
                hooks = s.get("hooks", {}).get("PreToolUse", [])
                if any("phase_guard" in str(h) for h in hooks):
                    hook_found = True
                    print(_ok(f"PreToolUse hook installed ({settings_path})"))
                    break
            except Exception:
                pass
    if not hook_found:
        print(_warn("PreToolUse hook not wired — see HANDOFF-CC-V0.md §7"))

    # 7 — W1 Boundary self-test
    print(f"\n{_bold('W1 Boundary')}\n" + "─" * 40)
    boundary_script = _repo_root() / "scripts" / "boundary.py"
    if boundary_script.exists():
        try:
            r = subprocess.run(
                [sys.executable, str(boundary_script), "--self-test"],
                capture_output=True, text=True, encoding="utf-8", timeout=15,
            )
            if r.returncode == 0:
                print(_ok("Boundary self-test: ALL PASS"))
            else:
                failed_lines = [l for l in r.stdout.splitlines() if "[FAIL]" in l]
                print(_fail(f"Boundary self-test FAILED: {len(failed_lines)} check(s)"))
                for l in failed_lines[:3]:
                    print(f"    {l.strip()}")
        except Exception as e:
            print(_warn(f"Boundary self-test error: {e}"))
    else:
        print(_warn("boundary.py not found — W1 not deployed"))

    # Gate Registry summary
    genesis_contract = cwd / ".techne" / "genesis.json"
    if genesis_contract.exists():
        try:
            c = json.loads(genesis_contract.read_text(encoding="utf-8"))
            n = c.get("modules_scanned", "?")
            print(_ok(f"GENESIS bootstrap: {n} modules scanned, contract present"))
        except Exception:
            print(_warn("genesis.json unreadable"))
    else:
        print(_warn("No genesis.json — run: python scripts/genesis.py"))

    # W6 Runtime Ring status
    print(f"\n{_bold('W6 Runtime Ring')}\n" + "─" * 40)
    for _rp in [str(_repo_root() / "scripts")]:
        if _rp not in sys.path:
            sys.path.insert(0, _rp)
    try:
        from runtime_ring import load_last_snapshot, _INCIDENTS_FILE
        snap = load_last_snapshot()
        if snap is None:
            print(_warn("No baseline snapshot — run: techne ring snapshot"))
        else:
            print(_ok(f"Baseline: tag={snap.tag} pass_rate={snap.pass_rate:.1%} ({snap.pass_count}/{snap.test_count})"))
        if _INCIDENTS_FILE.exists():
            n_inc = len([l for l in _INCIDENTS_FILE.read_text(encoding="utf-8").splitlines() if l.strip()])
            if n_inc:
                print(_warn(f"{n_inc} incident(s) logged — check .techne/runtime_ring/incidents.jsonl"))
            else:
                print(_ok("No incidents logged"))
        else:
            print(_ok("No incidents logged"))
    except Exception as e:
        print(_warn(f"Runtime Ring unreadable: {e}"))

    # 8 — Hermes checks
    hermes_dir = Path.home() / ".hermes"
    print(f"\n{_bold('Hermes')}\n" + "─" * 40)

    config_exists = (hermes_dir / "config.yaml").exists()
    print(_ok("config.yaml exists") if config_exists else _fail("config.yaml missing — run: hermes setup"))

    plugin_registered = False
    config_path = hermes_dir / "config.yaml"
    if config_path.exists():
        try:
            import yaml
            config = yaml.safe_load(config_path.read_text())
            plugins = config.get("plugins", {}).get("enabled", [])
            plugin_registered = "techne-plugin" in plugins or "techne" in plugins
        except Exception:
            pass
    print(_ok("techne plugin registered") if plugin_registered else _warn("techne plugin not registered in config.yaml"))

    skill_exists = (hermes_dir / "skills" / "techne" / "SKILL.md").exists()
    print(_ok("techne SKILL.md found") if skill_exists else _warn("techne SKILL.md not found"))

    gate_works = False
    try:
        r = subprocess.run(
            ["python3", "-m", "techne_cli.main", "gate", "hashline", "/dev/null"],
            capture_output=True, text=True, timeout=10,
        )
        gate_works = r.returncode == 0
    except Exception:
        pass
    print(_ok("techne gate hashline callable") if gate_works else _warn("techne gate hashline failed"))

    chain_ok = False
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from audit_chain import verify_chain
        ok, msg = verify_chain()
        chain_ok = ok
    except Exception:
        pass
    print(_ok("audit chain intact") if chain_ok else _warn("audit chain not verified"))

    # 8 — Revolver checks
    revolver_dir = hermes_dir / "plugins" / "revolver"
    revolver_config = Path.home() / ".revolver.yaml"
    revolver_installed = revolver_dir.exists()
    print(_ok("Revolver plugin installed") if revolver_installed else _warn("Revolver plugin not found"))
    if revolver_config.exists():
        print(_ok("~/.revolver.yaml configured"))
    else:
        print(_warn("~/.revolver.yaml not found — see ref/HANDOFF-HERMES.md"))

    print()


def cmd_promotion(args):
    """Promotion Gate — W7 structural learning loop (evaluate/ingest/status)."""
    repo = _repo_root()
    for p in [str(repo / "scripts")]:
        if p not in sys.path:
            sys.path.insert(0, p)

    from promotion_gate import (
        evaluate_candidate, promote, ingest_from_incident_log,
        ingest_failure, show_status, load_corpus,
    )

    if args.promo_cmd == "evaluate":
        candidate_text = Path(args.candidate).read_text(encoding="utf-8")
        incumbent_text = Path(args.incumbent).read_text(encoding="utf-8")
        signal = evaluate_candidate(candidate_text, incumbent_text,
                                    k=args.k, divergence_bound=args.divergence_bound)
        print(f"  Verdict:    {signal.verdict}")
        print(f"  Reason:     {signal.reason}")
        print(f"  pass^k:     candidate={signal.pass_k_score:.2%} incumbent={signal.incumbent_score:.2%}")
        print(f"  Delta:      {signal.delta:+.2%}")
        print(f"  Divergence: {signal.divergence:.2f}")
        if signal.verdict == "PROMOTE" and args.promote_on_win:
            if promote(args.gate_name, args.candidate, signal, candidate_text):
                print(f"  Promoted:   {args.gate_name}")
        sys.exit(0 if signal.verdict == "PROMOTE" else 1)

    if args.promo_cmd == "ingest":
        inc_path = Path(args.incidents) if args.incidents else None
        new_cases = ingest_from_incident_log(inc_path)
        print(f"  Ingested {len(new_cases)} new eval case(s)")
        return

    if args.promo_cmd == "add-case":
        case = ingest_failure(
            source="human_label",
            description=args.description,
            skill_target=args.skill_target,
            required_patterns=args.require or [],
            forbidden_patterns=args.forbid or [],
        )
        print(f"  Added: {case.id}")
        return

    if args.promo_cmd == "status":
        show_status()
        return


def cmd_editions(args):
    """W9 — Show edition tiers (FULL/STANDARD/LITE) and current phase_mode."""
    repo = _repo_root()
    for p in [str(repo / "scripts")]:
        if p not in sys.path:
            sys.path.insert(0, p)
    from phase_mode import format_edition_table, get_phase_mode, skipped_gates, PhaseMode

    if args.current:
        mode = get_phase_mode()
        print(f"\n  Current phase mode: {mode.value}")
        skipped = skipped_gates(mode)
        if skipped:
            print(f"  Skipped gates: {', '.join(sorted(skipped))}")
        return

    print(format_edition_table())


def cmd_calibration(args):
    """W8 HITL-removal calibration — per-gate catch-rate + decommission."""
    repo = _repo_root()
    for p in [str(repo / "scripts")]:
        if p not in sys.path:
            sys.path.insert(0, p)
    from calibration import calibrate_from_corpus, decommission_gate, show_calibration_status

    if args.calib_cmd == "run":
        runs = calibrate_from_corpus(gate_name=getattr(args, "gate", None))
        if not runs:
            print("  No calibration data (no eval corpus or no gate runs).")
            return
        for r in runs:
            print(f"  {r.gate_name}: catch_rate={r.catch_rate:.1%} verdict={r.verdict}")
        cands = [r.gate_name for r in runs if r.verdict == "decommission_candidate"]
        if cands:
            print(f"\n  Decommission candidates: {', '.join(cands)}")
        return

    if args.calib_cmd == "decommission":
        if decommission_gate(args.gate_name):
            print(f"  Decommissioned: {args.gate_name}")
        else:
            print(f"  Cannot decommission {args.gate_name} — not a decommission_candidate yet")
            sys.exit(1)
        return

    if args.calib_cmd == "status":
        show_calibration_status()
        return


def cmd_dispose(args):
    """W8b Autonomous failure disposition — check and dispose stalled tasks."""
    repo = _repo_root()
    for p in [str(repo / "scripts")]:
        if p not in sys.path:
            sys.path.insert(0, p)
    from failure_disposition import check_stall, dispose, show_status

    cwd = Path.cwd()

    if args.dispose_cmd == "check":
        stall = check_stall(cwd, getattr(args, "stall_minutes", 60))
        if stall is None:
            print("  No active pipeline.")
        elif stall.is_stalled:
            print(f"  STALLED: {stall.task_id} in {stall.phase} — {stall.reason}")
            print(f"  Recommended: {stall.recommended_disposition}")
        else:
            print(f"  Active: {stall.task_id} in {stall.phase} ({stall.minutes_in_phase:.0f}m)")
        return

    if args.dispose_cmd == "run":
        stall = check_stall(cwd)
        if stall is None or not stall.is_stalled:
            print("  Not stalled — nothing to dispose.")
            return
        event = dispose(stall, cwd)
        print(f"  Disposed: action={event.action}")
        if event.okf_risk_note:
            print(f"  OKF risk note: {event.okf_risk_note}")
        return

    if args.dispose_cmd == "status":
        show_status(cwd)
        return


def cmd_ring(args):
    """Runtime Ring — snapshot, monitor, rollback, status."""
    repo = _repo_root()
    for p in [str(repo / "scripts")]:
        if p not in sys.path:
            sys.path.insert(0, p)

    from runtime_ring import take_snapshot, save_snapshot, monitor, rollback, show_status, log_incident, load_last_snapshot

    if args.ring_cmd == "snapshot":
        snap = take_snapshot(args.test_cmd, args.tag)
        save_snapshot(snap)
        return

    if args.ring_cmd == "monitor":
        result = monitor(args.test_cmd, args.threshold)
        print(f"  [ring] {result.reason}")
        if result.requires_rollback:
            baseline = load_last_snapshot()
            rollback_target = args.rollback_to or (baseline.tag if baseline else "HEAD~1")
            risk_note = log_incident(
                result.reason, result.current_pass_rate, result.baseline_pass_rate,
                baseline.tag if baseline else "unknown", rollback_target,
            )
            print(f"  [ring] Incident logged: {risk_note}")
            if not args.dry_run:
                ok, msg = rollback(rollback_target)
                print(f"  [ring] {'ROLLBACK' if ok else 'ROLLBACK FAILED'}: {msg}")
                sys.exit(0 if ok else 1)
        sys.exit(0 if result.passed else 1)

    if args.ring_cmd == "rollback":
        ok, msg = rollback(args.to_tag, args.dry_run)
        print(f"  [ring] {'OK' if ok else 'FAIL'}: {msg}")
        sys.exit(0 if ok else 1)

    if args.ring_cmd == "status":
        show_status()
        return


def cmd_proposals(args):
    """Review pending GRPO proposals."""
    cwd = Path.cwd()
    proposals_path = cwd / ".techne" / "memory" / "retro_proposals.md"
    if not proposals_path.exists():
        print("No pending GRPO proposals.")
        sys.exit(0)

    content = proposals_path.read_text()
    pending = content.count("PROPOSE ADD")
    if pending == 0:
        print("No pending proposals.")
        sys.exit(0)

    print(f"\n  ⚡  {pending} GRPO proposal(s) ready for review:")
    print(f"  File: {proposals_path}")
    print()
    print(content)
    print()
    print(f"Run: python3 harness/apply_retro.py to accept/reject proposals")


def cli():
    parser = argparse.ArgumentParser(
        prog="techne",
        description="Techne — disciplined engineering harness for AI coding agents",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialize a new task pipeline")
    p_init.add_argument("task_id", help="Unique task identifier (e.g. feat-auth-01)")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing state.json")
    p_init.set_defaults(func=cmd_init)

    p_next = sub.add_parser("next", help="Advance the pipeline to the next phase")
    p_next.add_argument("--strict-nodes", action="store_true",
                        help="Block VERIFY if node-discipline violations found")
    p_next.add_argument("--strict-mutation", action="store_true",
                        help="Block VERIFY if mutation gate finds surviving mutants")
    p_next.add_argument("--phase-mode", choices=["FULL", "STANDARD", "LITE"], default=None,
                        help="Edition tier (W9): FULL=all gates, STANDARD=no mutation, LITE=minimal")
    p_next.set_defaults(func=cmd_next)

    p_status = sub.add_parser("status", help="Show current pipeline state and RL health")
    p_status.set_defaults(func=cmd_status)

    p_doctor = sub.add_parser("doctor", help="Run a 6-category health check")
    p_doctor.set_defaults(func=cmd_doctor)

    p_handoff = sub.add_parser("handoff", help="Write a handoff doc for session continuity")
    p_handoff.set_defaults(func=cmd_handoff)

    p_gate = sub.add_parser("gate", help="Run a named gate check")
    p_gate.add_argument("name", choices=["hashline", "forbidden", "audit"])
    p_gate.add_argument("target", help="diff file path or JSON event string")
    p_gate.set_defaults(func=cmd_gate)

    p_proposals = sub.add_parser("proposals", help="Review pending GRPO proposals")
    p_proposals.add_argument("action", nargs="?", default="review",
                              choices=["review"], help="Action to perform (default: review)")
    p_proposals.set_defaults(func=cmd_proposals)

    p_editions = sub.add_parser("editions", help="W9 edition tiers — show gate rigor matrix")
    p_editions.add_argument("--current", action="store_true", help="Show current configured mode only")
    p_editions.set_defaults(func=cmd_editions)

    p_calib = sub.add_parser("calibration", help="W8 HITL-removal calibration — per-gate catch-rate")
    calib_sub = p_calib.add_subparsers(dest="calib_cmd", required=True)
    c_run = calib_sub.add_parser("run", help="Run calibration against eval corpus")
    c_run.add_argument("--gate", help="Calibrate a specific gate only")
    c_decom = calib_sub.add_parser("decommission", help="Mark a gate as human-decommissioned")
    c_decom.add_argument("gate_name", help="Gate name to decommission")
    calib_sub.add_parser("status", help="Show calibration status per gate")
    p_calib.set_defaults(func=cmd_calibration)

    p_dispose = sub.add_parser("dispose", help="W8b autonomous failure disposition")
    disp_sub = p_dispose.add_subparsers(dest="dispose_cmd", required=True)
    d_check = disp_sub.add_parser("check", help="Check if current task is stalled")
    d_check.add_argument("--stall-minutes", type=float, default=60)
    disp_sub.add_parser("run", help="Run disposition on a stalled task")
    disp_sub.add_parser("status", help="Show stall + disposition history")
    p_dispose.set_defaults(func=cmd_dispose)

    p_promo = sub.add_parser("promotion", help="Promotion Gate — W7 structural learning loop")
    promo_sub = p_promo.add_subparsers(dest="promo_cmd", required=True)

    pr_eval = promo_sub.add_parser("evaluate", help="Evaluate a candidate vs incumbent")
    pr_eval.add_argument("--candidate", required=True, help="Candidate skill file")
    pr_eval.add_argument("--incumbent", required=True, help="Incumbent skill file")
    pr_eval.add_argument("--gate-name", default="unnamed")
    pr_eval.add_argument("--k", type=int, default=5)
    pr_eval.add_argument("--divergence-bound", type=float, default=0.6)
    pr_eval.add_argument("--promote-on-win", action="store_true")

    pr_ing = promo_sub.add_parser("ingest", help="Ingest Runtime Ring incidents into eval corpus")
    pr_ing.add_argument("--incidents", help="Path to incidents.jsonl")

    pr_add = promo_sub.add_parser("add-case", help="Add a manual eval case")
    pr_add.add_argument("--description", required=True)
    pr_add.add_argument("--skill-target", default="skills/implementer.md")
    pr_add.add_argument("--require", action="append", default=[], metavar="PATTERN")
    pr_add.add_argument("--forbid", action="append", default=[], metavar="PATTERN")

    promo_sub.add_parser("status", help="Show promotion gate status")
    p_promo.set_defaults(func=cmd_promotion)

    p_ring = sub.add_parser("ring", help="Runtime Ring — post-merge behavioral monitor (W6)")
    ring_sub = p_ring.add_subparsers(dest="ring_cmd", required=True)

    r_snap = ring_sub.add_parser("snapshot", help="Capture a health baseline")
    r_snap.add_argument("--test-cmd", default="pytest -q", help="Test command to run")
    r_snap.add_argument("--tag", help="Tag for this snapshot (default: auto timestamp)")

    r_mon = ring_sub.add_parser("monitor", help="Compare current health to baseline")
    r_mon.add_argument("--test-cmd", default="pytest -q", help="Test command to run")
    r_mon.add_argument("--threshold", type=float, default=0.05,
                       help="Max allowed pass_rate drop (default: 0.05 = 5%%)")
    r_mon.add_argument("--rollback-to", help="Git ref to rollback to on regression")
    r_mon.add_argument("--dry-run", action="store_true")

    r_rb = ring_sub.add_parser("rollback", help="Rollback to a git tag or commit")
    r_rb.add_argument("--to-tag", required=True, help="Git tag or commit SHA")
    r_rb.add_argument("--dry-run", action="store_true")

    ring_sub.add_parser("status", help="Show current Runtime Ring status")
    p_ring.set_defaults(func=cmd_ring)

    p_gates = sub.add_parser("gates", help="Show Gate Registry (per-gate status + catch-rate)")
    p_gates.add_argument("--json", action="store_true", help="JSON output")
    p_gates.add_argument("--record", nargs=2, metavar=("NAME", "OUTCOME"),
                         help="Record a gate outcome: caught|passed")
    p_gates.add_argument("--register", metavar="NAME", help="Register a new gate")
    p_gates.add_argument("--kind", default="mechanical",
                         choices=["pbt", "mechanical", "llm_judge"])
    p_gates.add_argument("--provenance", default="custom")
    p_gates.add_argument("--phase", default="unknown")
    p_gates.add_argument("--description", default="")
    p_gates.set_defaults(func=cmd_gates)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    cli()
