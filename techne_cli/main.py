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
    spec.loader.exec_module(mod)
    sys.exit(mod.main())


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

    # 7 — Hermes checks
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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    cli()
