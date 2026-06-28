#!/usr/bin/env python3
"""
Techne Workshop Bootstrap Script

Creates the full .techne/ directory skeleton, config.yaml, memory files,
context templates, and initial state.json in a single command.

Usage:
    python3 init_project.py [dir] [--project-name NAME] [--techne-path PATH] [--force]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def create_directory_structure(base_path: Path) -> dict:
    """Create all directories in the .techne/ skeleton."""
    dirs = {
        "loop": base_path / ".techne" / "loop",
        "audit": base_path / ".techne" / "audit",
        "events": base_path / ".techne" / "events",
        "memory": base_path / ".techne" / "memory",
        "context": base_path / ".techne" / "context",
        "context_packs": base_path / ".techne" / "context" / "context_packs",
        "scripts_dir": base_path / ".techne" / "scripts",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def create_config(base_path: Path, project_name: str, techne_path: str) -> Path:
    """Create config.yaml with project settings."""
    config_content = f"""project_name: {project_name}
techne_path: {techne_path}
"""
    config_path = base_path / ".techne" / "config.yaml"
    config_path.write_text(config_content)
    return config_path


def create_state_json(loop_dir: Path) -> Path:
    """Create initial state.json for RECALL phase."""
    now = datetime.now(timezone.utc).isoformat()
    state = {
        "task_id": "init",
        "phase": "RECALL",
        "created_at": now,
        "updated_at": now,
        "summary": "",
        "phase_timeout_min": 30
    }
    state_path = loop_dir / "state.json"
    state_path.write_text(json.dumps(state, indent=2))
    return state_path


def create_empty_jsonl(file_path: Path) -> Path:
    """Create an empty JSONL file (with just a newline)."""
    file_path.write_text("\n")
    return file_path


def create_mistakes_md(memory_dir: Path) -> Path:
    """Create mistakes.md with required marker."""
    content = """# Mistakes Log

<!-- New entries go below this line -->

"""
    path = memory_dir / "mistakes.md"
    path.write_text(content)
    return path


def create_ledger_md(memory_dir: Path) -> Path:
    """Create empty ledger.md."""
    content = """# Reward Ledger

"""
    path = memory_dir / "ledger.md"
    path.write_text(content)
    return path


def create_eval_history(memory_dir: Path) -> Path:
    """Create empty eval_history.json."""
    path = memory_dir / "eval_history.json"
    path.write_text("[]")
    return path


def create_project_digest(context_dir: Path, project_name: str) -> Path:
    """Create project_digest.md template."""
    content = f"""# Project Digest: {project_name}

## Overview
_Complete after context indexing._

## Key Components
- _To be filled_

## Important Patterns
- _To be filled_

## Known Constraints
- _To be filled_
"""
    path = context_dir / "project_digest.md"
    path.write_text(content)
    return path


def create_commands_md(context_dir: Path) -> Path:
    """Create commands.md placeholder."""
    content = """# Available Commands

_Discovered commands will be documented here._
"""
    path = context_dir / "commands.md"
    path.write_text(content)
    return path


def create_file_roles_md(context_dir: Path) -> Path:
    """Create file_roles.md placeholder."""
    content = """# File Roles

_File role mappings will be documented here._
"""
    path = context_dir / "file_roles.md"
    path.write_text(content)
    return path


def run_preflight_checks(project_name: str) -> bool:
    """
    Run three pre-flight checks before creating .techne/ directory.

    Returns:
        True if all checks pass (or are non-blocking).
        False if the audit chain is broken (blocks project init).
    """
    # Add scripts/ and harness/ to sys.path (same pattern as cmd_gate in techne_cli/main.py)
    script_path = Path(__file__).resolve()
    techne_root = script_path.parent.parent

    for _p in [str(techne_root / "scripts"), str(techne_root / "harness")]:
        if _p not in sys.path:
            sys.path.insert(0, _p)

    # 1. Audit chain integrity — BLOCKING on failure
    try:
        from audit_chain import verify_chain
        ok, msg = verify_chain()
        if not ok:
            print(f"⚠️  PRE-FLIGHT CHECK FAILED: Audit chain broken", file=sys.stderr)
            print(f"   {msg}", file=sys.stderr)
            print("   Run 'techne gate audit <event>' to repair or initialize the chain.", file=sys.stderr)
            return False
    except Exception as e:
        print(f"⚠️  PRE-FLIGHT WARNING: Could not verify audit chain: {e}")

    # 2. Mistakes pre-flight — never blocks, prints hits if found
    try:
        from mistakes import check_relevant
        hits = check_relevant(project_name)
        if hits:
            print("\n📋 Past mistakes relevant to this project:")
            for hit in hits:
                print(f"   [{hit.get('gate', '?')}] {hit.get('error', '?')}")
                print(f"       Lesson: {hit.get('lesson', '?')}")
    except FileNotFoundError:
        # New project with no mistakes.md yet — non-blocking
        pass
    except Exception as e:
        print(f"⚠️  PRE-FLIGHT WARNING: Could not check mistakes: {e}")

    # 3. Knowledge graph surface — never blocks, prints top 3 matches
    try:
        from knowledge_graph import cmd_search
        print(f"\n🔍 Knowledge graph matches for '{project_name}':")
        # Capture cmd_search output (it prints directly)
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        redirect_stdout(f)
        cmd_search(project_name)
        output = f.getvalue()
        if output.strip():
            lines = output.strip().split('\n')
            for line in lines[:3]:
                print(f"   {line}")
            if len(lines) > 3:
                print(f"   ... and {len(lines) - 3} more matches")
        else:
            print("   (no matching entries found)")
    except FileNotFoundError:
        # New project with no kg entries yet — non-blocking
        print("   (knowledge graph not yet initialized)")
    except Exception as e:
        print(f"⚠️  PRE-FLIGHT WARNING: Could not search knowledge graph: {e}")

    return True


def create_risk_boundaries_md(context_dir: Path) -> Path:
    """Create risk_boundaries.md with default HITL template."""
    content = """# Risk Boundaries

## Default Human-in-the-Loop Boundaries

| Risk Level | Threshold | Action Required |
|------------|-----------|-----------------|
| Low        | < 5       | Autonomous execution |
| Medium     | 5-15      | Review before execution |
| High       | > 15      | Explicit approval required |

## Command Risk Scoring
_Commands are scored during context indexing._
"""
    path = context_dir / "risk_boundaries.md"
    path.write_text(content)
    return path


def create_context_hash(context_dir: Path) -> Path:
    """Create initial context_hash.txt."""
    path = context_dir / "context_hash.txt"
    path.write_text("0000000000000000000000000000000000000000000")
    return path


def create_symlink(base_path: Path, techne_path: Path) -> Path | None:
    """Create symlink to next.py script if techne_path is valid."""
    script_path = techne_path / "scripts" / "next.py"
    link_path = base_path / "next"
    
    if script_path.exists():
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()
        link_path.symlink_to(script_path)
        return link_path
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Bootstrap a Techne workshop in a project directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "dir",
        nargs="?",
        default=".",
        help="Project root directory (default: current directory)"
    )
    parser.add_argument(
        "--project-name",
        help="Project name (default: directory name)"
    )
    parser.add_argument(
        "--techne-path",
        default=None,
        help="Path to techne repo (for symlinks, default: auto-detect from script location)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files"
    )
    
    args = parser.parse_args()
    
    # Resolve base path
    base_path = Path(args.dir).resolve()
    
    # Determine project name
    project_name = args.project_name or base_path.name
    
    # Determine techne path
    if args.techne_path:
        techne_path = Path(args.techne_path).resolve()
    else:
        # Auto-detect from script location
        script_path = Path(__file__).resolve()
        techne_path = script_path.parent.parent
    
    techne_path_str = str(techne_path)

    # Run pre-flight checks before creating .techne/
    if not run_preflight_checks(project_name):
        sys.exit(1)

    # Check if .techne/ already exists
    techne_dir = base_path / ".techne"
    if techne_dir.exists() and not args.force:
        print(f"Error: .techne/ already exists at {base_path}", file=sys.stderr)
        print("Use --force to overwrite existing files.", file=sys.stderr)
        sys.exit(1)
    
    # Create structure
    dirs = create_directory_structure(base_path)
    
    # Track created files
    created = []
    
    # Create all files
    config_path = create_config(base_path, project_name, techne_path_str)
    created.append(str(config_path.relative_to(base_path)))
    
    state_path = create_state_json(dirs["loop"])
    created.append(str(state_path.relative_to(base_path)))
    
    chain_path = create_empty_jsonl(dirs["audit"] / "chain.jsonl")
    created.append(str(chain_path.relative_to(base_path)))
    
    rl_path = create_empty_jsonl(dirs["events"] / "rl.jsonl")
    created.append(str(rl_path.relative_to(base_path)))
    
    mistakes_path = create_mistakes_md(dirs["memory"])
    created.append(str(mistakes_path.relative_to(base_path)))
    
    ledger_path = create_ledger_md(dirs["memory"])
    created.append(str(ledger_path.relative_to(base_path)))
    
    # Note: rewards.db is created by RL system, not here
    
    eval_path = create_eval_history(dirs["memory"])
    created.append(str(eval_path.relative_to(base_path)))
    
    digest_path = create_project_digest(dirs["context"], project_name)
    created.append(str(digest_path.relative_to(base_path)))
    
    commands_path = create_commands_md(dirs["context"])
    created.append(str(commands_path.relative_to(base_path)))
    
    roles_path = create_file_roles_md(dirs["context"])
    created.append(str(roles_path.relative_to(base_path)))
    
    risk_path = create_risk_boundaries_md(dirs["context"])
    created.append(str(risk_path.relative_to(base_path)))
    
    hash_path = create_context_hash(dirs["context"])
    created.append(str(hash_path.relative_to(base_path)))
    
    # Create symlink
    symlink_path = create_symlink(base_path, techne_path)
    if symlink_path:
        created.append(str(symlink_path.relative_to(base_path)))
    
    # Print summary
    print(f"✅ Techne workshop initialized at {base_path}")
    print()
    print("Created:")
    for f in sorted(created):
        print(f"  {f}")
    print()
    print("Next steps:")
    print("  1. Edit .techne/config.yaml if needed")
    print("  2. Run: python3 {}/scripts/context_index.py".format(techne_path_str))
    print("  3. Start your first task: python3 {} --init my-task".format(symlink_path or "next"))


if __name__ == "__main__":
    main()
