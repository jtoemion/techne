"""
tests/test_skill_router.py — Validate skill-router.yaml integrity.

Checks:
1. Every skill_path in the routing table exists on disk
2. Every folder skill (skills/<name>/) has a SKILL.md (or .md symlink)
3. Top-level .md skill files are referenced by the router (or noted as always-loaded/stack-gated)
4. No duplicate condition keywords across high-weight entries
5. always_loaded paths match what conductor.py get_always_loaded() returns
"""

import sys
from pathlib import Path

# Ensure harness is on path
sys.path.insert(0, str(Path(__file__).parent.parent / "harness"))

import yaml

ROOT = Path(__file__).parent.parent
ROUTER_PATH = ROOT / "skills" / "skill-router.yaml"
SKILLS_DIR = ROOT / "skills"


def load_router():
    with open(ROUTER_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


class TestRouterValid:
    """Router table structural validation."""

    def test_router_file_parses(self):
        """skill-router.yaml must be valid YAML."""
        data = load_router()
        assert "routing" in data, "Missing 'routing' key"

    def test_routing_entries_have_required_fields(self):
        """Each routing entry must have id, condition, skill_path, weight."""
        data = load_router()
        required = {"id", "condition", "skill_path", "weight"}
        for entry in data["routing"]:
            missing = required - set(entry.keys())
            assert not missing, f"Entry {entry.get('id','?')} missing fields: {missing}"

    def test_skill_paths_exist(self):
        """Every skill_path in the router must exist on disk."""
        data = load_router()
        missing = []
        for entry in data["routing"]:
            path = ROOT / entry["skill_path"]
            if not path.exists():
                missing.append(f"{entry['id']}: {entry['skill_path']}")
        assert not missing, "Missing skill files:\n  " + "\n  ".join(missing)

    def test_folder_skills_have_skill_md(self):
        """Every skills/<name>/ directory that appears in a route must have SKILL.md."""
        data = load_router()
        missing = []
        for entry in data["routing"]:
            # Extract folder name from path like "skills/foo/SKILL.md" or "skills/foo.md"
            sp = entry["skill_path"]
            if sp.startswith("skills/"):
                rest = sp[7:]  #去掉 "skills/"
                if "/" in rest:
                    folder = rest.split("/")[0]
                    skill_md = SKILLS_DIR / folder / "SKILL.md"
                    if not skill_md.exists():
                        missing.append(f"{entry['id']} folder {folder} has no SKILL.md")
        assert not missing, "Missing SKILL.md in folder skills:\n  " + "\n  ".join(missing)

    def test_all_top_level_md_are_referenced(self):
        """Every top-level skills/*.md (not a symlink to folder) must be referenced
        in the router, always_loaded, or stack_loaded.

        SOURCES.md is documentation, not a skill — skip it.
        Symlinks like react-vite.md -> react-vite/SKILL.md are resolved by the router
        via the folder path; skip them too since they are not independent skills.
        """
        data = load_router()
        referenced = set()
        # Collect from routing entries
        for entry in data.get("routing", []):
            referenced.add(entry["skill_path"])
        # Collect from always_loaded
        for p in data.get("always_loaded", []):
            referenced.add(p)
        # Collect from stack_loaded
        for p in data.get("stack_loaded", {}).values():
            referenced.add(p)

        # Documentation files that live in skills/ but are not skill files
        skip_names = {"SOURCES.md", "README.md", "SKILL.md"}

        issues = []
        for md in SKILLS_DIR.glob("*.md"):
            # Skip symlinks (e.g. react-vite.md -> react-vite/SKILL.md)
            # and known non-skill files
            if md.is_symlink() or md.name in skip_names:
                continue
            rel = f"skills/{md.name}"
            if rel not in referenced:
                issues.append(md.name)
        assert not issues, f"Top-level .md files not referenced in router:\n  " + "\n  ".join(issues)

    def test_no_duplicate_condition_keywords(self):
        """No pair of entries with weight >= 70 should share more than 4 keywords."""
        data = load_router()
        stopwords = {
            "a", "an", "the", "or", "and", "in", "on", "at", "to", "for", "of",
            "with", "is", "are", "was", "not", "no", "user", "says", "your",
        }
        import re

        def keywords(condition):
            words = re.findall(r"\b\w+\b", condition.lower())
            return {w for w in words if len(w) > 2 and w not in stopwords}

        high_weight = [e for e in data["routing"] if e.get("weight", 0) >= 70]
        dupes = []
        for i, a in enumerate(high_weight):
            for b in high_weight[i + 1 :]:
                ka = keywords(a["condition"])
                kb = keywords(b["condition"])
                overlap = ka & kb
                if len(overlap) > 4:
                    dupes.append(
                        f"  {a['id']}(w={a['weight']}) & {b['id']}(w={b['weight']}) "
                        f"share {len(overlap)} keywords: {sorted(overlap)}"
                    )
        assert not dupes, "High-overlap condition pairs (may cause routing ambiguity):\n" + "\n".join(dupes)

    def test_always_loaded_matches_conductor(self):
        """always_loaded in YAML must match what router.get_always_loaded() returns."""
        from router import get_always_loaded

        yaml_al = set(load_router().get("always_loaded", []))
        fn_al = set(get_always_loaded())
        diff_yaml = yaml_al - fn_al
        diff_fn = fn_al - yaml_al
        msg = []
        if diff_yaml:
            msg.append(f"In YAML but not in get_always_loaded(): {sorted(diff_yaml)}")
        if diff_fn:
            msg.append(f"In get_always_loaded() but not in YAML: {sorted(diff_fn)}")
        assert not msg, "\n".join(msg)

    def test_stack_loaded_values_are_valid(self):
        """stack_loaded values must point to existing files."""
        data = load_router()
        missing = []
        for tag, path in data.get("stack_loaded", {}).items():
            full = ROOT / path
            if not full.exists():
                missing.append(f"{tag}: {path}")
        assert not missing, "Missing stack_loaded skill files:\n  " + "\n  ".join(missing)

    def test_always_loaded_files_exist(self):
        """always_loaded paths must exist on disk."""
        data = load_router()
        missing = []
        for p in data.get("always_loaded", []):
            if not (ROOT / p).exists():
                missing.append(p)
        assert not missing, "Missing always_loaded files:\n  " + "\n  ".join(missing)

    def test_no_id_collisions(self):
        """No duplicate skill ids in routing table."""
        data = load_router()
        ids = [e["id"] for e in data["routing"]]
        dups = set(id for id in ids if ids.count(id) > 1)
        assert not dups, f"Duplicate skill ids: {sorted(dups)}"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
