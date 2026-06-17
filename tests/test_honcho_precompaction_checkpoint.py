"""
test_honcho_precompaction_checkpoint.py — deterministic checks for Honcho checkpoint skill.
Run:
    python -X utf8 tests/test_honcho_precompaction_checkpoint.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))

from router import route, get_always_loaded


def test_honcho_checkpoint_skill_exists_and_compact():
    skill = ROOT / "skills" / "honcho-precompaction-checkpoint.md"
    text = skill.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert skill.exists(), "Honcho precompaction skill must exist"
    assert len(lines) <= 100, f"skill should be compact: {len(lines)} lines"
    assert "honcho_conclude" in text
    assert "Before any session compaction" in text


def test_honcho_checkpoint_routes_and_is_always_loaded():
    assert get_always_loaded() == [
        "skills/context-amortization.md",
        "skills/honcho-precompaction-checkpoint.md",
        "skills/nextjs.md",
        "skills/typescript.md",
    ]

    match = route("checkpoint honcho before compaction")
    assert match is not None
    assert match.id == "techne/honcho-precompaction-checkpoint"
    assert match.skill_path == "skills/honcho-precompaction-checkpoint.md"


def test_orchestrator_mentions_precompaction_checkpoint():
    text = (ROOT / "skills" / "orchestrator.md").read_text(encoding="utf-8")
    assert "Step 0: Pre-Compaction Honcho Checkpoint" in text
    assert "honcho_conclude" in text


def test_skill_router_yaml_mentions_precompaction_checkpoint():
    text = (ROOT / "harness" / "skill-router.yaml").read_text(encoding="utf-8")
    assert "techne/honcho-precompaction-checkpoint" in text
    assert "skills/honcho-precompaction-checkpoint.md" in text
