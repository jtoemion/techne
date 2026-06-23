"""
phase_skills.py — phase/skill prompt utilities shared by the pipeline.

Helpers for the live pipeline (pipeline_enforcer + orchestrator_loop):

  - _load_phase_skills(phase)   → companion skill files + scripts for a phase
  - parse_retro_markers(text)   → (kind, what, why) tuples from retro output

Pure functions, no model calls, no network.
"""

from __future__ import annotations

import re
from pathlib import Path

HARNESS_DIR = Path(__file__).parent          # techne/harness/
ROOT = HARNESS_DIR.parent                     # techne/
AGENTS_DIR = ROOT / "agents"

# The retro agent emits durable method-layer entries as one-line markers.
# Format: KIND: <what> [| WHY: <why>] [| SKILL: <skill>]
#
# Example:
#   DECISION: Use line-prefix validation in CONCLUDE | WHY: keyword-match too loose | SKILL: orchestrator
#   LESSON: SHA must be scoped to CONTEXT line | WHY: bypass via HONCHO line was possible
#   DISCIPLINE: Gate self-improvement on recurrence, not scores | SKILL: writing-skill
#
# Parsing is permissive: WHY and SKILL are optional (defaults applied in log_*).
# Each line is independent — agent can emit any number of any kind.
_RETRO_MARKER_RE = re.compile(
    r"^\s*(?P<kind>DECISION|LESSON|DISCIPLINE)\s*:\s*"
    r"(?P<what>.+?)"
    r"(?:\s*\|\s*WHY\s*:\s*(?P<why>.+?))?"
    r"(?:\s*\|\s*SKILL\s*:\s*(?P<skill>[^\n|]+?))?"
    r"\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def parse_retro_markers(output: str) -> list[tuple[str, str, str]]:
    """Extract (kind, what, why) tuples from retro output.

    SKILL field is parsed but NOT returned — caller applies the routed skill_id
    so attribution stays consistent (a retro mentioning a different skill could
    otherwise misattribute the entry).
    """
    if not output:
        return []
    found: list[tuple[str, str, str]] = []
    for m in _RETRO_MARKER_RE.finditer(output):
        kind = m.group("kind").upper()
        what = m.group("what").strip()
        why = (m.group("why") or "").strip()
        if what:
            found.append((kind, what, why))
    return found


def _parse_agent_frontmatter(agent_name: str) -> dict:
    """Parse YAML frontmatter from an agents/<name>.md file."""
    path = AGENTS_DIR / f"{agent_name}.md"
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    _, _, body = text.partition("---\n")
    front, _, _ = body.partition("---\n")
    result: dict[str, list[str]] = {}
    for line in front.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val.startswith("[") and val.endswith("]"):
                result[key] = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",")]
            else:
                result[key] = val
    return result


def _load_phase_skills(phase_name: str) -> str:
    """Load the phase-specific skill file(s) referenced in the agent's
    frontmatter and find companion scripts.
    Returns formatted context block or empty string."""
    # Map phase name to agent name
    AGENT_MAP = {
        "recall": "recaller", "implement": "implementer", "context-guard": "context-guard",
        "critique": "critique", "review": "reviewer", "verify": "verifier",
        "eval": None, "retro": "retro", "conclude": "concluder",
        "refresh-context": None, "debug": "debugger", "preflight": "context-preflight",
        "approval": None, "conductor": "conductor",
    }
    agent_name = AGENT_MAP.get(phase_name)
    if not agent_name:
        return ""

    front = _parse_agent_frontmatter(agent_name)
    skills_list = front.get("skills", [])
    parts = []

    # Load skill files
    for skill_path in skills_list:
        full_path = (ROOT / skill_path)
        if full_path.exists():
            parts.append(f"=== Phase Skill: {skill_path} ===\n{full_path.read_text(encoding='utf-8')}")

    # Find companion scripts
    for script in sorted((ROOT / "scripts").glob(f"{phase_name.replace('-', '_')}*.py")):
        parts.append(f"[Available Tool] python3 scripts/{script.name}")
    for script in sorted((ROOT / "scripts").glob(f"{phase_name}*.py")):
        if script.suffix == ".py" and script.stem != phase_name.replace('-', '_') and f"scripts/{script.name}" not in str(parts):
            parts.append(f"[Available Tool] python3 scripts/{script.name}")

    # Add universal tools
    universal_tools = [
        "scripts/pipeline_health.py",
        "scripts/mistakes_logger.py",
        "scripts/session_reporter.py",
        "scripts/diff_gate_checker.py",
        "scripts/task_gardener.py",
        "scripts/knowledge_graph.py",
        "scripts/project_graph_build.py",
    ]
    for tool in universal_tools:
        if (ROOT / tool).exists():
            parts.append(f"[Available Tool] python3 {tool}")

    return "\n".join(parts) if parts else ""
