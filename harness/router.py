"""
router.py — skill routing via skill-router.yaml.

Adopted from jtoemion/harness-engineering-skills/runtime/conductor.py.
Parses the YAML routing table and returns the best-matching skill
for a given task input. First match wins, weight resolves ties.
"""

import re
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    yaml = None

HARNESS_DIR = Path(__file__).parent
ROOT = HARNESS_DIR.parent
ROUTER_PATH = HARNESS_DIR.parent / "skills" / "skill-router.yaml"


def _load_router() -> dict:
    """Load and parse skill-router.yaml."""
    if yaml is None:
        # Fallback: simple line parser for environments without PyYAML
        return _fallback_parse()

    with open(ROUTER_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _fallback_parse() -> dict:
    """Minimal parser when PyYAML isn't installed — extracts routing entries."""
    text = ROUTER_PATH.read_text(encoding="utf-8")
    entries = []
    current: dict = {}

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- id:"):
            if current:
                entries.append(current)
            current = {"id": stripped.split('"')[1]}
        elif stripped.startswith("condition:") and current:
            current["condition"] = stripped.split('"')[1]
        elif stripped.startswith("skill_path:") and current:
            current["skill_path"] = stripped.split('"')[1]
        elif stripped.startswith("weight:") and current:
            current["weight"] = int(stripped.split(":")[1].strip())

    if current:
        entries.append(current)

    return {"routing": entries}


def _extract_keywords(condition: str) -> list[str]:
    """Extract meaningful keywords from a condition string."""
    stopwords = {
        "a", "an", "the", "or", "and", "in", "on", "at", "to", "for", "of",
        "with", "is", "are", "was", "not", "no", "user", "says",
    }
    words = re.findall(r"\b\w+\b", condition.lower())
    return [w for w in words if len(w) > 2 and w not in stopwords]


def route(task_input: str) -> Optional[dict]:
    """Route task to skill. Returns skill dict or None."""
    router = _load_router()
    routing_table = router.get("routing", [])
    task_lower = task_input.lower()

    candidates = []

    for skill in routing_table:
        condition = skill.get("condition", "")
        keywords = _extract_keywords(condition)

        if not keywords:
            continue

        matches = sum(1 for kw in keywords if kw in task_lower)
        # 2+ keyword matches is enough to route; single match only for short conditions
        threshold = 1 if len(keywords) <= 3 else 2

        if matches >= threshold:
            score = matches * 10 + skill.get("weight", 0)
            candidates.append((skill, score))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]


def get_always_loaded() -> list[str]:
    """Return skill paths loaded for EVERY task, regardless of stack (the
    stack-independent globals: default behavior + context + checkpoint rules)."""
    router = _load_router()
    return router.get("always_loaded", [])


def get_stack_loaded() -> dict[str, str]:
    """Return the stack-tag → skill-path map. These framework pattern files load
    ONLY when stack_detect.detect_stack() finds the tag in the target project."""
    router = _load_router()
    mapping = router.get("stack_loaded", {})
    return mapping if isinstance(mapping, dict) else {}


def resolve_stack_skills(root=ROOT) -> list[str]:
    """Skill paths to inject for the stack detected at `root` (deduped, ordered
    by the yaml mapping for determinism). Empty when no framework is detected."""
    from stack_detect import detect_stack

    tags = detect_stack(root)
    out: list[str] = []
    for tag, path in get_stack_loaded().items():
        if tag in tags and path not in out:
            out.append(path)
    return out


def stack_gated_paths() -> set[str]:
    """Every skill path that is stack-gated. The conductor's catch-all fallback
    must NOT load these — they load only when their stack is detected."""
    return set(get_stack_loaded().values())


def get_common_loaded() -> list[str]:
    """Return list of common-loaded skill paths (fallback when no specific skill matches)."""
    router = _load_router()
    return router.get("common_loaded", [])


def route_with_explanation(task_input: str) -> str:
    """Route and return a human-readable explanation."""
    result = route(task_input)
    if result:
        return (
            f"Routed to: {result['id']}\n"
            f"Skill:     {result.get('skill_path', 'N/A')}\n"
            f"Weight:    {result.get('weight', 0)}\n"
            f"Note:      {result.get('note', '-')}"
        )
    return "No skill matched for this task."
