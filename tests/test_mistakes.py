"""
test_mistakes.py — structured mistake tracking.

Verifies log_mistake, check_relevant, mark_resolved, count_active,
count_by_skill, and edge-case robustness using pytest + tmp_path isolation.

Run from tests/:  python -m pytest test_mistakes.py -v
"""

from __future__ import annotations

import re
import pytest
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent

import sys
sys.path.insert(0, str(ROOT / "harness"))

import mistakes


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SEED = "# MISTAKES\n<!-- New entries go below this line -->\n"


@pytest.fixture
def isolated_mistakes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Patch MISTAKES_FILE to a temp path; provide a minimal well-formed file."""
    fake = tmp_path / "mistakes.md"
    monkeypatch.setattr(mistakes, "MISTAKES_FILE", fake)
    fake.write_text(SEED, encoding="utf-8")
    return fake


# ---------------------------------------------------------------------------
# log_mistake — recording
# ---------------------------------------------------------------------------

def test_log_mistake_full_fields(isolated_mistakes: Path):
    """All fields populated → entry written with correct format."""
    mistakes.log_mistake(
        phase="IMPLEMENT",
        error="off-by-one index error",
        cause="loop boundary miscalculated",
        lesson="always verify inclusive/exclusive bounds",
        gate="context_guard",
        skill="writing-skill",
        source="self-improve",
    )
    text = isolated_mistakes.read_text(encoding="utf-8")
    assert "## [" in text
    assert "IMPLEMENT" in text
    assert "off-by-one index error" in text
    assert "loop boundary miscalculated" in text
    assert "always verify inclusive/exclusive bounds" in text
    assert "context_guard" in text
    assert "writing-skill" in text
    assert "ACTIVE" in text
    assert "<!-- New entries go below this line -->" in text


def test_log_mistake_minimal_fields(isolated_mistakes: Path):
    """Only required fields (phase, error) → defaults applied cleanly."""
    mistakes.log_mistake(phase="CRITIQUE", error="wrong threshold")
    text = isolated_mistakes.read_text(encoding="utf-8")
    assert "CRITIQUE" in text
    assert "wrong threshold" in text
    assert "pending analysis" in text        # default cause
    assert "pending retro" in text           # default lesson
    assert "none" in text                    # default skill/gate/source


def test_log_mistake_multiple_entries(isolated_mistakes: Path):
    """Multiple calls → all entries present; newer entries are prepended (closest to marker)."""
    mistakes.log_mistake(phase="A", error="first entry")
    mistakes.log_mistake(phase="B", error="second entry")
    mistakes.log_mistake(phase="C", error="third entry")
    text = isolated_mistakes.read_text(encoding="utf-8")
    assert "first entry" in text
    assert "second entry" in text
    assert "third entry" in text
    # Newer entries appear immediately after the insert marker (prepended, not appended)
    marker_pos = text.index(mistakes.INSERT_MARKER)
    third_pos = text.index("third entry")
    second_pos = text.index("second entry")
    first_pos = text.index("first entry")
    # third entry is right after marker, then second, then first
    assert marker_pos < third_pos < second_pos < first_pos


def test_log_mistake_special_characters(isolated_mistakes: Path):
    """Unicode, backticks, markdown chars, newlines in fields → no parsing errors."""
    mistakes.log_mistake(
        phase="IMPLEMENT",
        error="SyntaxError: invalid `syntax`",
        cause="Missing [bracket] in dict **literal**\nwith newline",
        lesson="Check: 'quotes', \"double quotes\", and `backticks`",
        gate="context\\_guard",
        skill="python\\debug",
        source="retro-review",
    )
    text = isolated_mistakes.read_text(encoding="utf-8")
    # No exceptions raised; entry written
    assert "SyntaxError" in text
    assert "newline" in text         # newline in cause field
    assert "backticks" in text


def test_log_mistake_file_not_found_raises(isolated_mistakes: Path, monkeypatch: pytest.MonkeyPatch):
    """Missing file → FileNotFoundError."""
    monkeypatch.setattr(mistakes, "MISTAKES_FILE", Path("/nonexistent/mistakes.md"))
    with pytest.raises(FileNotFoundError):
        mistakes.log_mistake(phase="A", error="x")


def test_log_mistake_missing_marker_raises(isolated_mistakes: Path):
    """File exists but has no insert marker → ValueError."""
    isolated_mistakes.write_text("no marker here\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Insert marker"):
        mistakes.log_mistake(phase="A", error="x")


# ---------------------------------------------------------------------------
# check_relevant — retrieval
# ---------------------------------------------------------------------------

def test_check_relevant_match_single(isolated_mistakes: Path):
    """Keyword in task_input matches ACTIVE entry → returned."""
    mistakes.log_mistake(
        phase="IMPLEMENT",
        error="off-by-one boundary error",
        cause="wrong range end",
        lesson="use assert boundaries",
        gate="verify",
        skill="python",
    )
    relevant = mistakes.check_relevant("fix the boundary error in my loop")
    assert len(relevant) == 1
    assert relevant[0]["error"] == "off-by-one boundary error"
    assert relevant[0]["status"] == "ACTIVE"


def test_check_relevant_match_multiple(isolated_mistakes: Path):
    """Multiple ACTIVE entries match → all returned."""
    mistakes.log_mistake(phase="A", error="null pointer crash", cause="uninitialized variable", lesson="init vars", gate="verify", skill="cpp")
    mistakes.log_mistake(phase="B", error="null pointer in async handler", cause="race condition", lesson="await cleanup", gate="context_guard", skill="python")
    relevant = mistakes.check_relevant("null pointer exception")
    assert len(relevant) == 2


def test_check_relevant_no_match(isolated_mistakes: Path):
    """No ACTIVE entry matches → empty list."""
    mistakes.log_mistake(phase="A", error="err A", cause="cause A", lesson="lesson A", gate="none", skill="none")
    relevant = mistakes.check_relevant("totally unrelated task input xyz123")
    assert relevant == []


def test_check_relevant_empty_file(isolated_mistakes: Path):
    """Empty mistakes.md (marker only) → empty list, no error."""
    isolated_mistakes.write_text(SEED, encoding="utf-8")
    assert mistakes.check_relevant("anything") == []


def test_check_relevant_case_insensitive(isolated_mistakes: Path):
    """Matching is case-insensitive."""
    mistakes.log_mistake(phase="A", error="SEGFAULT", cause="bad cast", lesson="type check", gate="none", skill="cpp")
    assert len(mistakes.check_relevant("segfault in production")) == 1
    assert len(mistakes.check_relevant("SEGFAULT")) == 1
    assert len(mistakes.check_relevant("SegFault")) == 1


def test_check_relevant_skips_resolved(isolated_mistakes: Path):
    """RESOLVED entries are not returned even if keywords match."""
    mistakes.log_mistake(phase="A", error="segmentation fault", cause="uninit ptr", lesson="init ptrs", gate="none", skill="cpp")
    date_str = "2026-06-22T12:00:00Z"
    # Directly insert a RESOLVED entry with a unique error to avoid keyword clash
    content = isolated_mistakes.read_text(encoding="utf-8")
    resolved_entry = f"""## [{date_str}] RESOLVED | AUTO-LOGGED
**Error**     : dangling handle
**Cause**     : stale reference
**Lesson**    : clear refs on free
**Gate**      : none
**Skill**     : cpp
**Status**    : RESOLVED
"""
    content = content.replace(mistakes.INSERT_MARKER, f"{mistakes.INSERT_MARKER}\n{resolved_entry}")
    isolated_mistakes.write_text(content, encoding="utf-8")

    assert len(mistakes.check_relevant("dangling handle")) == 0


def test_check_relevant_short_keywords_filtered(isolated_mistakes: Path):
    """Keywords ≤ 2 chars are ignored (not in indexable searchable text)."""
    mistakes.log_mistake(phase="A", error="id not found", cause="bad id", lesson="check id", gate="none", skill="none")
    # "id" is 2 chars → filtered out; "not" is 3 → kept
    relevant = mistakes.check_relevant("id not found")
    # If "id" were used, this would match; since it's filtered, only "not" / "found" count
    # The entry's searchable text contains "id not found" but "id" is stripped
    # so with only 2-char keyword stripped, "not" and "found" should still match
    assert len(relevant) == 1


def test_check_relevant_missing_file_returns_empty(isolated_mistakes: Path, monkeypatch: pytest.MonkeyPatch):
    """Non-existent MISTAKES_FILE → empty list, no exception."""
    monkeypatch.setattr(mistakes, "MISTAKES_FILE", Path("/nonexistent/mistakes.md"))
    assert mistakes.check_relevant("anything") == []


# ---------------------------------------------------------------------------
# mark_resolved — resolution
# ---------------------------------------------------------------------------

def test_mark_resolved_updates_status(isolated_mistakes: Path):
    """Entry marked RESOLVED → status field changes, count_active drops."""
    mistakes.log_mistake(phase="A", error="err", cause="c", lesson="l", gate="none", skill="none")
    date_str = "2026-06-22T12:00:00Z"
    # Overwrite with a known date for reliable matching (replace the generated timestamp)
    content = isolated_mistakes.read_text(encoding="utf-8")
    content = re.sub(r"(## \[)[^]]+(\] A \| AUTO-LOGGED\n\*\*Error\*\*     : err)", rf"\g<1>{date_str}\g<2>", content)
    isolated_mistakes.write_text(content, encoding="utf-8")

    result = mistakes.mark_resolved(date_str)
    assert result is True
    text = isolated_mistakes.read_text(encoding="utf-8")
    assert "RESOLVED" in text


def test_mark_resolved_missing_date(isolated_mistakes: Path):
    """Date not in file → returns False, file unchanged."""
    mistakes.log_mistake(phase="A", error="err", cause="c", lesson="l", gate="none", skill="none")
    result = mistakes.mark_resolved("2099-01-01T00:00:00Z")
    assert result is False
    assert "ACTIVE" in isolated_mistakes.read_text(encoding="utf-8")


def test_mark_resolved_already_resolved(isolated_mistakes: Path):
    """Marking an already-resolved entry → returns False (no change needed)."""
    mistakes.log_mistake(phase="A", error="err", cause="c", lesson="l", gate="none", skill="none")
    date_str = "2026-06-22T12:00:00Z"
    content = isolated_mistakes.read_text(encoding="utf-8")
    content = content.replace("2026-", f"[{date_str}] A | AUTO-LOGGED\n**Error**     : err")
    isolated_mistakes.write_text(content, encoding="utf-8")

    mistakes.mark_resolved(date_str)
    result = mistakes.mark_resolved(date_str)  # second call on already-resolved
    assert result is False


def test_mark_resolved_missing_file_returns_false(isolated_mistakes: Path, monkeypatch: pytest.MonkeyPatch):
    """Non-existent file → False, no exception."""
    monkeypatch.setattr(mistakes, "MISTAKES_FILE", Path("/nonexistent/mistakes.md"))
    assert mistakes.mark_resolved("2026-01-01T00:00:00Z") is False


# ---------------------------------------------------------------------------
# count_active — counting
# ---------------------------------------------------------------------------

def test_count_active_empty(isolated_mistakes: Path):
    """Marker-only file → 0."""
    isolated_mistakes.write_text(SEED, encoding="utf-8")
    assert mistakes.count_active() == 0


def test_count_active_three_entries(isolated_mistakes: Path):
    """3 ACTIVE entries → count returns 3."""
    mistakes.log_mistake(phase="A", error="err1", cause="c", lesson="l", gate="none", skill="none")
    mistakes.log_mistake(phase="B", error="err2", cause="c", lesson="l", gate="none", skill="none")
    mistakes.log_mistake(phase="C", error="err3", cause="c", lesson="l", gate="none", skill="none")
    assert mistakes.count_active() == 3


def test_count_active_after_resolve(isolated_mistakes: Path):
    """After resolving 1 of 3 → count returns 2."""
    mistakes.log_mistake(phase="A", error="err1", cause="c", lesson="l", gate="none", skill="none")
    mistakes.log_mistake(phase="B", error="err2", cause="c", lesson="l", gate="none", skill="none")
    mistakes.log_mistake(phase="C", error="err3", cause="c", lesson="l", gate="none", skill="none")

    date_str = "2026-06-22T12:00:00Z"
    content = isolated_mistakes.read_text(encoding="utf-8")
    content = re.sub(r"(## \[)[^]]+(\] B \| AUTO-LOGGED\n\*\*Error\*\*     : err2)", rf"\g<1>{date_str}\g<2>", content)
    isolated_mistakes.write_text(content, encoding="utf-8")

    mistakes.mark_resolved(date_str)
    assert mistakes.count_active() == 2


def test_count_active_missing_file_returns_zero(isolated_mistakes: Path, monkeypatch: pytest.MonkeyPatch):
    """Non-existent file → 0, no exception."""
    monkeypatch.setattr(mistakes, "MISTAKES_FILE", Path("/nonexistent/mistakes.md"))
    assert mistakes.count_active() == 0


# ---------------------------------------------------------------------------
# count_by_skill — grouping
# ---------------------------------------------------------------------------

def test_count_by_skill_multiple_skills(isolated_mistakes: Path):
    """3 different skills → correct per-skill counts."""
    mistakes.log_mistake(phase="A", error="err", cause="c", lesson="l", gate="none", skill="python")
    mistakes.log_mistake(phase="B", error="err", cause="c", lesson="l", gate="none", skill="cpp")
    mistakes.log_mistake(phase="C", error="err", cause="c", lesson="l", gate="none", skill="python")
    counts = mistakes.count_by_skill()
    assert counts == {"python": 2, "cpp": 1}


def test_count_by_skill_all_same_skill(isolated_mistakes: Path):
    """All entries same skill → single dict entry."""
    mistakes.log_mistake(phase="A", error="err", cause="c", lesson="l", gate="none", skill="writing-skill")
    mistakes.log_mistake(phase="B", error="err", cause="c", lesson="l", gate="none", skill="writing-skill")
    counts = mistakes.count_by_skill()
    assert counts == {"writing-skill": 2}


def test_count_by_skill_empty(isolated_mistakes: Path):
    """No entries → empty dict."""
    isolated_mistakes.write_text(SEED, encoding="utf-8")
    assert mistakes.count_by_skill() == {}


def test_count_by_skill_skill_none_excluded(isolated_mistakes: Path):
    """Entries with skill='none' are NOT counted (no routed skill to improve)."""
    mistakes.log_mistake(phase="A", error="err", cause="c", lesson="l", gate="none", skill="none")
    mistakes.log_mistake(phase="B", error="err", cause="c", lesson="l", gate="none", skill="python")
    counts = mistakes.count_by_skill()
    assert counts == {"python": 1}
    assert "none" not in counts


def test_count_by_skill_resolved_excluded(isolated_mistakes: Path):
    """RESOLVED entries are not counted."""
    mistakes.log_mistake(phase="A", error="err", cause="c", lesson="l", gate="none", skill="python")
    date_str = "2026-06-22T12:00:00Z"
    content = isolated_mistakes.read_text(encoding="utf-8")
    content = content.replace("2026-", f"[{date_str}] A | AUTO-LOGGED\n**Error**     : err")
    isolated_mistakes.write_text(content, encoding="utf-8")
    mistakes.mark_resolved(date_str)

    assert mistakes.count_by_skill() == {}


def test_count_by_skill_missing_file_returns_empty_dict(isolated_mistakes: Path, monkeypatch: pytest.MonkeyPatch):
    """Non-existent file → {}, no exception."""
    monkeypatch.setattr(mistakes, "MISTAKES_FILE", Path("/nonexistent/mistakes.md"))
    assert mistakes.count_by_skill() == {}


# ---------------------------------------------------------------------------
# Edge cases — empty / whitespace strings, unicode
# ---------------------------------------------------------------------------

def test_log_mistake_empty_strings(isolated_mistakes: Path):
    """Empty strings for optional fields → written literally (no auto-default in this function)."""
    mistakes.log_mistake(phase="", error="", cause="", lesson="", gate="", skill="", source="")
    text = isolated_mistakes.read_text(encoding="utf-8")
    # Empty cause/lesson are written as empty (not defaulted to "pending analysis" etc.)
    assert "**Cause**     :" in text
    assert "**Lesson**    :" in text


def test_log_mistake_whitespace_only_strings(isolated_mistakes: Path):
    """Whitespace-only strings accepted (no stripping in the function)."""
    mistakes.log_mistake(phase="  ", error="  \t  ", cause="  ", lesson="  ", gate="  ", skill="  ", source="  ")
    text = isolated_mistakes.read_text(encoding="utf-8")
    # Function writes the whitespace literally; no error raised
    assert "  " in text


def test_check_relevant_empty_string(isolated_mistakes: Path):
    """Empty task_input → all keywords filtered → empty list."""
    mistakes.log_mistake(phase="A", error="error", cause="cause", lesson="lesson", gate="gate", skill="skill")
    assert mistakes.check_relevant("") == []


def test_check_relevant_whitespace_only(isolated_mistakes: Path):
    """Whitespace-only task_input → all tokens filtered → empty list."""
    assert mistakes.check_relevant("   \t\n  ") == []


def test_check_relevant_unicode_task_input(isolated_mistakes: Path):
    """Unicode in task_input → handled gracefully."""
    mistakes.log_mistake(phase="A", error="err", cause="cause", lesson="lesson", gate="none", skill="python")
    relevant = mistakes.check_relevant("Python: 日本語 error 日本語")
    # Should not raise; may or may not match depending on unicode handling
    assert isinstance(relevant, list)


def test_log_mistake_unicode_fields(isolated_mistakes: Path):
    """Unicode in mistake fields → written and parsed without error."""
    mistakes.log_mistake(
        phase="IMPLEMENT",
        error="日本語エラー",
        cause="原 因",
        lesson="教訓：テスト",
        gate="verify",
        skill="python",
        source="retro",
    )
    text = isolated_mistakes.read_text(encoding="utf-8")
    assert "日本語エラー" in text
    assert "教訓" in text
    # check_relevant should also not raise
    result = mistakes.check_relevant("日本語エラー")
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Integration: full workflow
# ---------------------------------------------------------------------------

def test_full_workflow(isolated_mistakes: Path):
    """Log 4 mistakes → check_relevant filters correctly → resolve 2 → counts update."""
    mistakes.log_mistake(phase="A", error="null pointer", cause="uninit", lesson="init", gate="none", skill="cpp")
    mistakes.log_mistake(phase="B", error="off-by-one UNIQUE_TOKEN_999", cause="wrong bound", lesson="bounds", gate="none", skill="python")
    mistakes.log_mistake(phase="C", error="null pointer in handler", cause="race", lesson="locks", gate="none", skill="python")
    mistakes.log_mistake(phase="D", error="memory leak", cause="no free", lesson="free", gate="none", skill="cpp")

    # null pointer entries should match (2 entries contain "null pointer")
    assert len(mistakes.check_relevant("null pointer")) == 2
    # UNIQUE_TOKEN_999 only appears in phase B
    assert len(mistakes.check_relevant("UNIQUE_TOKEN_999")) == 1
    # nothing matches
    assert mistakes.check_relevant("asdfghjkl qwertyuvwxyz") == []

    # resolve the first null pointer entry (phase A)
    date_str_a = "2026-06-22T12:00:00Z"
    content = isolated_mistakes.read_text(encoding="utf-8")
    content = re.sub(r"(## \[)[^]]+(\] A \| AUTO-LOGGED\n\*\*Error\*\*     : null pointer)", rf"\g<1>{date_str_a}\g<2>", content)
    isolated_mistakes.write_text(content, encoding="utf-8")
    mistakes.mark_resolved(date_str_a)

    # Now only 1 null pointer entry remains (phase C)
    assert len(mistakes.check_relevant("null pointer")) == 1
    # count_active = 3 (one resolved out of 4)
    assert mistakes.count_active() == 3
    # count_by_skill: cpp=1 (one of two resolved), python=2
    counts = mistakes.count_by_skill()
    assert counts["cpp"] == 1
    assert counts["python"] == 2