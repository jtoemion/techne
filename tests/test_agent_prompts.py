"""
test_agent_prompts.py — Domain 6: Phase Agent Prompts hardening tests.

Validates:
- All 11 agents have valid YAML frontmatter (name, description, model, skills, tools)
- All referenced skill paths exist
- All referenced tools are valid Hermes tool names
- All agents have required sections (Role, Output Format, Hard Constraints / Constraints)
- No broken companion script references

Run: python test_agent_prompts.py -v
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
AGENTS_DIR = ROOT / "agents"
SKILLS_DIR = ROOT / "skills"
SCRIPTS_DIR = ROOT / "scripts"

# Valid Hermes tools that agents may reference
VALID_TOOLS = {
    "Read", "Write", "Edit", "Bash", "Glob", "Grep",
    "WebSearch", "Agent", "terminal",
}

# Required markdown sections (case-insensitive check)
REQUIRED_SECTIONS = ["role", "output format"]


def parse_frontmatter(text: str) -> dict | None:
    """Parse YAML frontmatter block. Returns None if not found or invalid."""
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    yaml_block = parts[1]
    result = {}
    for line in yaml_block.splitlines():
        line = line.rstrip()
        if ": " in line:
            key, val = line.split(": ", 1)
            result[key.strip()] = val.strip().strip("[]\"'")
        elif line.strip().startswith("-"):
            # list item (multiline list)
            pass
    return result


def parse_skills_list(yaml_text: str) -> list[str]:
    """Extract skill paths from YAML block, handling both [a, b] and block forms."""
    skills = []
    # Remove the opening --- and closing ---
    lines = yaml_text.splitlines()
    in_skills = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("---"):
            continue
        if in_skills:
            if stripped.startswith("- "):
                skills.append(stripped[1:].strip())
            elif stripped and not stripped.startswith("#") and ":" in stripped:
                # next field
                in_skills = False
        if stripped.startswith("skills:"):
            in_skills = True
            # inline list [a, b]
            rest = stripped.split("skills:", 1)[1].strip()
            if rest.startswith("["):
                inner = rest.strip("[]")
                for s in inner.split(","):
                    s = s.strip().strip("'\"")
                    if s:
                        skills.append(s)
    return skills


def section_exists(content: str, section_name: str) -> bool:
    """Check if a markdown section exists (case-insensitive, with leading #)."""
    pattern = re.compile(r"^#+\s+" + re.escape(section_name), re.MULTILINE | re.IGNORECASE)
    return bool(pattern.search(content))


def test_all_agents_exist():
    """All 11 agent files must exist."""
    agents = list(AGENTS_DIR.glob("*.md"))
    names = [a.stem for a in agents]
    assert len(agents) == 11, f"Expected 11 agents, found {len(agents)}: {names}"
    for name in ["concluder", "conductor", "context-guard", "context-preflight",
                 "critique", "debugger", "implementer", "recaller",
                 "retro", "reviewer", "verifier"]:
        assert (AGENTS_DIR / f"{name}.md").exists(), f"Missing agent: {name}.md"


def _check_frontmatter_name(agent_path):
    """Agent must have a name field in frontmatter."""
    text = agent_path.read_text()
    fm = parse_frontmatter(text)
    assert fm is not None, f"{agent_path.name}: No frontmatter found"
    assert "name" in fm, f"{agent_path.name}: Missing 'name' field in frontmatter"
    assert fm["name"] == agent_path.stem, (
        f"{agent_path.name}: name field '{fm['name']}' != filename stem '{agent_path.stem}'"
    )


def _check_frontmatter_description(agent_path):
    """Agent must have a non-empty description field."""
    text = agent_path.read_text()
    fm = parse_frontmatter(text)
    assert fm is not None, f"{agent_path.name}: No frontmatter found"
    assert "description" in fm, f"{agent_path.name}: Missing 'description' field"
    assert len(fm["description"]) > 10, (
        f"{agent_path.name}: description too short (got: {fm['description']!r})"
    )


def _check_frontmatter_model(agent_path):
    """Agent must have a model field."""
    text = agent_path.read_text()
    fm = parse_frontmatter(text)
    assert fm is not None, f"{agent_path.name}: No frontmatter found"
    assert "model" in fm, f"{agent_path.name}: Missing 'model' field"


def _check_frontmatter_skills(agent_path):
    """Agent must have skills that reference existing files."""
    text = agent_path.read_text()
    fm = parse_frontmatter(text)
    assert fm is not None, f"{agent_path.name}: No frontmatter found"
    assert "skills" in fm or "skills:\n" in text, f"{agent_path.name}: Missing 'skills' field"

    skill_paths = parse_skills_list(text)
    assert len(skill_paths) > 0, f"{agent_path.name}: No skill paths found"

    for sp in skill_paths:
        sp = sp.strip()
        if not sp.startswith("skills/"):
            sp = f"skills/{sp}"
            if not sp.endswith(".md") and not Path(ROOT / sp).exists():
                sp = sp.replace("/diagnose/", "/diagnose/SKILL.md")
                sp = sp.replace("/diagnose", "/diagnose/SKILL.md")

        full_path = ROOT / sp
        assert full_path.exists(), (
            f"{agent_path.name}: skill path does not exist: {sp} (resolved to {full_path})"
        )


def _check_frontmatter_tools(agent_path):
    """Agent must have tools from the valid Hermes tool set."""
    text = agent_path.read_text()
    fm = parse_frontmatter(text)
    assert fm is not None, f"{agent_path.name}: No frontmatter found"
    assert "tools" in fm, f"{agent_path.name}: Missing 'tools' field"

    tools_str = fm.get("tools", "")
    tools = [t.strip() for t in tools_str.replace("[", "").replace("]", "").split(",")]
    tools = [t for t in tools if t]

    assert len(tools) > 0, f"{agent_path.name}: No tools listed"
    for tool in tools:
        assert tool in VALID_TOOLS, (
            f"{agent_path.name}: Invalid tool '{tool}'. Valid: {VALID_TOOLS}"
        )


def _check_output_format_section(agent_path):
    """Agent must have an Output Format section."""
    text = agent_path.read_text()
    assert section_exists(text, "Output Format"), (
        f"{agent_path.name}: Missing '## Output Format' section"
    )


def _check_role_section(agent_path):
    """Agent must have a Role section."""
    text = agent_path.read_text()
    assert section_exists(text, "Role"), (
        f"{agent_path.name}: Missing '## Role' section"
    )


def _check_constraints_section(agent_path):
    """Agent must have a Constraints or Hard Constraints section."""
    text = agent_path.read_text()
    has_constraints = section_exists(text, "Constraints")
    has_hard_constraints = section_exists(text, "Hard Constraints")
    assert has_constraints or has_hard_constraints, (
        f"{agent_path.name}: Missing '## Constraints' or '## Hard Constraints' section"
    )


def _check_no_duplicate_frontmatter_keys(agent_path):
    """Frontmatter must not have duplicate keys (e.g. duplicate 'skills:' lines)."""
    text = agent_path.read_text()
    fm_start = text.find("---\n")
    fm_end = text.find("\n---\n", fm_start + 3)
    assert fm_start != -1 and fm_end != -1, f"{agent_path.name}: Malformed frontmatter"
    fm_block = text[fm_start:fm_end + 5]

    # Check for duplicate top-level keys (things like "skills:" appearing twice)
    lines = fm_block.splitlines()
    seen_keys = set()
    for line in lines:
        if not line.strip() or line.strip().startswith("#"):
            continue
        # Top-level key: "key: value" with no leading whitespace
        if line == line.lstrip() and ": " in line:
            key = line.split(":")[0].strip()
            assert key not in seen_keys, (
                f"{agent_path.name}: Duplicate frontmatter key '{key}'"
            )
            seen_keys.add(key)


def test_companion_scripts_exist():
    """Companion script references in agent bodies must point to existing files."""
    # Search agent files for script references
    script_refs = set()
    for agent_file in AGENTS_DIR.glob("*.md"):
        found = re.findall(r"python3 scripts/([\w_]+\.py)", agent_file.read_text())
        script_refs.update(found)
    for script_name in script_refs:
        path = SCRIPTS_DIR / script_name
        assert path.exists(), f"Referenced script does not exist: scripts/{script_name}"


# ---------------------------------------------------------------------------
# Per-agent test generators
# ---------------------------------------------------------------------------

_agent_files = sorted(AGENTS_DIR.glob("*.md"))

for _path in _agent_files:
    _name = f"test_{_path.stem}_frontmatter_name"
    globals()[_name] = lambda p=_path: _check_frontmatter_name(p)

    _name = f"test_{_path.stem}_frontmatter_description"
    globals()[_name] = lambda p=_path: _check_frontmatter_description(p)

    _name = f"test_{_path.stem}_frontmatter_model"
    globals()[_name] = lambda p=_path: _check_frontmatter_model(p)

    _name = f"test_{_path.stem}_frontmatter_skills"
    globals()[_name] = lambda p=_path: _check_frontmatter_skills(p)

    _name = f"test_{_path.stem}_frontmatter_tools"
    globals()[_name] = lambda p=_path: _check_frontmatter_tools(p)

    _name = f"test_{_path.stem}_output_format"
    globals()[_name] = lambda p=_path: _check_output_format_section(p)

    _name = f"test_{_path.stem}_role_section"
    globals()[_name] = lambda p=_path: _check_role_section(p)

    _name = f"test_{_path.stem}_constraints_section"
    globals()[_name] = lambda p=_path: _check_constraints_section(p)

    _name = f"test_{_path.stem}_no_duplicate_keys"
    globals()[_name] = lambda p=_path: _check_no_duplicate_frontmatter_keys(p)