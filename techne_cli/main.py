"""main.py — Techne CLI entry point."""
from __future__ import annotations

import argparse
import json
import os
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

    print()


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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    cli()
