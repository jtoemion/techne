"""
tests/test_mode_classifier.py

Tests for classify_phase_mode(), validate_mode_fit(), and recommend_mode().
"""

import pytest
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))

from pipeline_enforcer import classify_phase_mode, validate_mode_fit, get_cost_estimate, detect_sensitive_change


# ── classify_phase_mode tests ─────────────────────────────────────────────────

class TestClassifyPhaseMode:
    def test_micro_single_line_no_logic(self):
        """1-line comment change, 1 file → micro"""
        diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1,2 @@\n-# old\n+# new comment"
        # Note: title must NOT contain fast-keywords like "typo", "review", etc.
        assert classify_phase_mode("update foo formatting", "", diff) == "micro"

    def test_micro_three_lines_no_logic(self):
        """≤3 lines, 1 file, no logic keywords → micro"""
        # exactly 3 changed lines (2 added + 1 removed = 3)
        diff = "--- a/notes.txt\n+++ b/notes.txt\n@@ -1 +1,3 @@\n-Line one.\n+Line one updated.\n+Line two."
        assert classify_phase_mode("update notes file", "", diff) == "micro"

    def test_micro_zero_lines_empty_diff_returns_full(self):
        """Empty diff — no data to classify → defaults to full"""
        assert classify_phase_mode("some task", "", "") == "full"

    def test_fast_review_keyword_in_title(self):
        """Title contains 'review' → fast"""
        assert classify_phase_mode("review PR #42", "") == "fast"

    def test_fast_audit_keyword_in_title(self):
        """Title contains 'audit' → fast"""
        assert classify_phase_mode("audit permissions module", "") == "fast"

    def test_fast_verify_in_description(self):
        """Description contains 'verify' → fast"""
        assert classify_phase_mode("check something", "verify the output format", "") == "fast"

    def test_fast_check_in_title(self):
        """Title contains 'check' → fast"""
        assert classify_phase_mode("check test coverage", "") == "fast"

    def test_fast_inspect_in_title(self):
        """Title contains 'inspect' → fast"""
        assert classify_phase_mode("inspect memory usage", "") == "fast"

    def test_fast_document_keyword(self):
        """Title contains 'document' → fast"""
        assert classify_phase_mode("document the API", "") == "fast"

    def test_fast_readme_in_title(self):
        """Title contains 'readme' → fast"""
        assert classify_phase_mode("fix readme typo", "") == "fast"

    def test_fast_typo_in_title(self):
        """Title contains 'typo' → fast"""
        assert classify_phase_mode("fix typo in bar", "") == "fast"

    def test_fast_comment_in_title(self):
        """Title contains 'comment' → fast"""
        assert classify_phase_mode("add comment to helper", "") == "fast"

    def test_full_multi_file(self):
        """Multi-file change → full"""
        diff = (
            "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1,2 @@\n+def foo(): pass\n"
            "--- a/bar.py\n+++ b/bar.py\n@@ -1 +1,2 @@\n+def bar(): pass\n"
        )
        assert classify_phase_mode("add two helpers", "", diff) == "full"

    def test_full_logic_keywords(self):
        """Diff contains 'if' keyword → full"""
        diff = "--- a/calc.py\n+++ b/calc.py\n@@ -1 +1,3 @@\n+def calc(x):\n+    if x > 0:\n+        return x"
        assert classify_phase_mode("add condition", "", diff) == "full"

    def test_full_complex_change(self):
        """Complex multi-line refactor → full"""
        diff = (
            "--- a/service.py\n+++ b/service.py\n"
            "+class MyService:\n"
            "+    def __init__(self):\n"
            "+        self.items = []\n"
        )
        assert classify_phase_mode("introduce service class", "", diff) == "full"

    def test_full_no_diff_defaults_full(self):
        """No diff provided, no fast keywords → full"""
        assert classify_phase_mode("build new feature", "add a new module", "") == "full"

    def test_classify_phase_mode_recommends_heavy_for_auth(self):
        """Task with 'auth' in title → heavy"""
        assert classify_phase_mode("add auth middleware", "", "") == "heavy"

    def test_classify_phase_mode_recommends_heavy_for_migration(self):
        """Task with 'migration' in title → heavy"""
        assert classify_phase_mode("run data migration", "", "") == "heavy"

    def test_classify_phase_mode_heavy_for_billing(self):
        """Task with 'billing' in title → heavy"""
        assert classify_phase_mode("update billing module", "", "") == "heavy"

    def test_classify_phase_mode_heavy_for_token(self):
        """Task with 'token' in description → heavy"""
        assert classify_phase_mode("add refresh token", "add token handling", "") == "heavy"

    def test_classify_phase_mode_heavy_in_description(self):
        """Heavy keyword in description → heavy"""
        assert classify_phase_mode("fix bug", "changes to auth module", "") == "heavy"


# ── validate_mode_fit tests ───────────────────────────────────────────────────

class TestValidateModeFit:
    def test_micro_valid_trivial_diff(self):
        """micro mode with ≤3 lines, 1 file, no logic → valid"""
        diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1,2 @@\n-# old\n+# new"
        valid, reason, suggested = validate_mode_fit("micro", diff, 1)
        assert valid is True
        assert reason == ""

    def test_micro_invalid_too_many_lines(self):
        """micro mode with 8-line diff → invalid, suggest full"""
        diff = (
            "--- a/foo.py\n+++ b/foo.py\n"
            "+line1\n+line2\n+line3\n+line4\n+line5\n+line6\n+line7\n+line8\n"
        )
        valid, reason, suggested = validate_mode_fit("micro", diff, 1)
        assert valid is False
        assert "8" in reason
        assert suggested == "full"

    def test_micro_invalid_multi_file(self):
        """micro mode with 2 files → invalid, suggest full"""
        diff = (
            "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1,2 @@\n+def foo(): pass\n"
            "--- a/bar.py\n+++ b/bar.py\n@@ -1 +1,2 @@\n+def bar(): pass\n"
        )
        valid, reason, suggested = validate_mode_fit("micro", diff, 2)
        assert valid is False
        assert "2" in reason
        assert suggested == "full"

    def test_micro_invalid_has_logic_keyword(self):
        """micro mode with 'if' keyword → invalid, suggest full"""
        diff = "--- a/calc.py\n+++ b/calc.py\n@@ -1 +1,2 @@\n+if x > 0: pass"
        valid, reason, suggested = validate_mode_fit("micro", diff, 1)
        assert valid is False
        assert "logic" in reason.lower()
        assert suggested == "full"

    def test_full_invalid_trivial_change(self):
        """full mode on 1-line comment → invalid, suggest micro"""
        diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1,2 @@\n-# old\n+# new"
        valid, reason, suggested = validate_mode_fit("full", diff, 1)
        assert valid is False
        assert "trivial" in reason.lower()
        assert suggested == "micro"

    def test_full_valid_normal_change(self):
        """full mode with multi-line code change → valid"""
        diff = (
            "--- a/service.py\n+++ b/service.py\n"
            "+class Service:\n"
            "+    def run(self):\n"
            "+        pass\n"
        )
        valid, reason, suggested = validate_mode_fit("full", diff, 1)
        assert valid is True

    def test_full_valid_empty_diff(self):
        """full mode with no diff yet → valid (pre-implement)"""
        valid, reason, suggested = validate_mode_fit("full", "", 0)
        assert valid is True

    def test_fast_always_valid(self):
        """fast mode is always valid — it's a subset"""
        valid, reason, suggested = validate_mode_fit("fast", "", 0)
        assert valid is True
        valid2, reason2, suggested2 = validate_mode_fit(
            "fast",
            "--- a/foo.py\n+++ a/foo.py\n+def foo(): pass\n",
            1,
        )
        assert valid2 is True

    def test_micro_empty_diff_file_count_zero_valid(self):
        """micro mode, empty diff, file_count=0 → valid (pre-implement)"""
        valid, reason, suggested = validate_mode_fit("micro", "", 0)
        assert valid is True

    def test_micro_empty_diff_file_count_nonzero_invalid(self):
        """micro mode, empty diff but files already touched → invalid"""
        valid, reason, suggested = validate_mode_fit("micro", "", 2)
        assert valid is False
        assert "touched" in reason.lower()

    def test_unknown_mode_always_valid(self):
        """Unknown mode string → valid (passthrough)"""
        valid, reason, suggested = validate_mode_fit("foobar", "", 0)
        assert valid is True


# ── get_cost_estimate tests ───────────────────────────────────────────────────

class TestGetCostEstimate:
    def test_micro_cost(self):
        """micro → 4 API calls"""
        result = get_cost_estimate("micro")
        assert result["api_calls"] == 4
        assert "IMPLEMENT" in result["notes"]

    def test_fast_cost(self):
        """fast → 7 API calls"""
        result = get_cost_estimate("fast")
        assert result["api_calls"] == 7
        assert "CRITIQUE" in result["notes"]

    def test_full_cost(self):
        """full → 11 API calls"""
        result = get_cost_estimate("full")
        assert result["api_calls"] == 11
        assert "RECALL" in result["notes"]

    def test_heavy_cost(self):
        """heavy → 12 API calls (full + 1 APPROVAL)"""
        result = get_cost_estimate("heavy")
        assert result["api_calls"] == 12
        assert "APPROVAL" in result["notes"]

    def test_unknown_mode_returns_full(self):
        """unknown mode → defaults to full estimate"""
        result = get_cost_estimate("foobar")
        assert result["api_calls"] == 11

    def test_case_insensitive(self):
        """mode lookup is case-insensitive"""
        assert get_cost_estimate("MICRO")["api_calls"] == 4
        assert get_cost_estimate("Fast")["api_calls"] == 7
        assert get_cost_estimate("FULL")["api_calls"] == 11


# ── validate_mode_fit cost message tests ──────────────────────────────────────

class TestValidateModeFitCostMessages:
    def test_micro_too_many_lines_includes_cost(self):
        """mismatch reason includes API call count"""
        diff = (
            "--- a/foo.py\n+++ b/foo.py\n"
            "+line1\n+line2\n+line3\n+line4\n+line5\n+line6\n+line7\n+line8\n"
        )
        valid, reason, suggested = validate_mode_fit("micro", diff, 1)
        assert valid is False
        assert "11" in reason  # full mode API calls
        assert "API calls" in reason
        assert suggested == "full"

    def test_micro_multi_file_includes_cost(self):
        """multi-file micro mismatch includes cost"""
        diff = (
            "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1,2 @@\n+def foo(): pass\n"
            "--- a/bar.py\n+++ b/bar.py\n@@ -1 +1,2 @@\n+def bar(): pass\n"
        )
        valid, reason, suggested = validate_mode_fit("micro", diff, 2)
        assert valid is False
        assert "11" in reason
        assert "API calls" in reason

    def test_full_trivial_includes_cost(self):
        """full on trivial change includes both costs in message"""
        diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1,2 @@\n-# old\n+# new"
        valid, reason, suggested = validate_mode_fit("full", diff, 1)
        assert valid is False
        assert "11" in reason
        assert "4" in reason
        assert "API calls" in reason


# ── Integration: OrchestratorLoop.recommend_mode ───────────────────────────────

class TestRecommendMode:
    def test_recommend_mode_returns_micro_with_cost(self):
        """recommend_mode returns cost info for micro"""
        from task_db import TaskDB
        from orchestrator_loop import OrchestratorLoop

        db = TaskDB(":memory:")
        loop = OrchestratorLoop(db)

        diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1,2 @@\n+# typo"
        result = loop.recommend_mode("update foo", "", diff)
        assert "micro" in result
        assert "4" in result
        assert "7" in result
        assert "11" in result

    def test_recommend_mode_returns_fast_with_cost(self):
        """recommend_mode returns cost info for fast"""
        from task_db import TaskDB
        from orchestrator_loop import OrchestratorLoop

        db = TaskDB(":memory:")
        loop = OrchestratorLoop(db)

        result = loop.recommend_mode("review PR", "", "")
        assert "fast" in result
        assert "4" in result
        assert "7" in result
        assert "11" in result

    def test_recommend_mode_returns_full_with_cost(self):
        """recommend_mode returns cost info for full"""
        from task_db import TaskDB
        from orchestrator_loop import OrchestratorLoop

        db = TaskDB(":memory:")
        loop = OrchestratorLoop(db)

        complex_diff = (
            "--- a/svc.py\n+++ a/svc.py\n"
            "+class Svc:\n"
            "+    def run(self):\n"
            "+        pass\n"
        )
        result = loop.recommend_mode("implement service", "", complex_diff)
        assert "full" in result
        assert "4" in result
        assert "7" in result
        assert "11" in result


# ── Mode-override telemetry tests ─────────────────────────────────────────────

import tempfile
import os


class TestLogModeOverride:
    """Tests for _log_mode_override() and get_mode_overrides()."""

    def test_log_mode_override_writes_to_file(self, tmp_path, monkeypatch):
        """_log_mode_override creates the log file and writes a JSON entry."""
        # Patch OVERRIDES_LOG to use tmp_path
        import pipeline_enforcer
        monkeypatch.setattr(pipeline_enforcer, "OVERRIDES_LOG", tmp_path / "mode_overrides.log")
        monkeypatch.setattr(pipeline_enforcer, "_MAX_LOG_LINES", 1000)

        pipeline_enforcer._log_mode_override(
            "task-abc",
            "micro",
            "full",
            {"diff_lines": 10, "file_count": 2, "has_logic": True},
        )

        log_file = tmp_path / "mode_overrides.log"
        assert log_file.exists(), "mode_overrides.log was not created"
        content = log_file.read_text()
        import json
        entry = json.loads(content.strip().split("\n")[0])
        assert entry["task_id"] == "task-abc"
        assert entry["chosen_mode"] == "micro"
        assert entry["suggested_mode"] == "full"
        assert entry["diff_lines"] == 10
        assert entry["file_count"] == 2
        assert entry["has_logic"] is True
        assert "timestamp" in entry

    def test_get_mode_overrides_returns_recent(self, tmp_path, monkeypatch):
        """get_mode_overrides returns the last N entries."""
        import pipeline_enforcer
        monkeypatch.setattr(pipeline_enforcer, "OVERRIDES_LOG", tmp_path / "mode_overrides.log")
        monkeypatch.setattr(pipeline_enforcer, "_MAX_LOG_LINES", 1000)

        # Write 5 entries
        for i in range(5):
            pipeline_enforcer._log_mode_override(
                f"task-{i}",
                "micro",
                "full",
                {"diff_lines": i, "file_count": 1, "has_logic": False},
            )

        # Read last 3 — should be task-2, task-3, task-4
        entries = pipeline_enforcer.get_mode_overrides(limit=3)
        assert len(entries) == 3
        assert entries[0]["task_id"] == "task-2"
        assert entries[1]["task_id"] == "task-3"
        assert entries[2]["task_id"] == "task-4"

    def test_validate_mode_fit_logs_override(self, tmp_path, monkeypatch):
        """validate_mode_fit writes an override entry when mode is invalid."""
        import pipeline_enforcer
        monkeypatch.setattr(pipeline_enforcer, "OVERRIDES_LOG", tmp_path / "mode_overrides.log")
        monkeypatch.setattr(pipeline_enforcer, "_MAX_LOG_LINES", 1000)

        diff = (
            "--- a/foo.py\n+++ b/foo.py\n"
            "+line1\n+line2\n+line3\n+line4\n+line5\n"
        )
        valid, reason, suggested = pipeline_enforcer.validate_mode_fit(
            "micro", diff, 1, task_id="task-xyz"
        )
        assert valid is False
        assert suggested == "full"

        log_file = tmp_path / "mode_overrides.log"
        assert log_file.exists()
        content = log_file.read_text()
        import json
        entries = [json.loads(line) for line in content.strip().split("\n") if line]
        assert len(entries) == 1
        assert entries[0]["task_id"] == "task-xyz"
        assert entries[0]["chosen_mode"] == "micro"
        assert entries[0]["suggested_mode"] == "full"

    def test_mode_overrides_log_rotation(self, tmp_path, monkeypatch):
        """When log exceeds _MAX_LOG_LINES (1000), only last 1000 lines are kept."""
        import pipeline_enforcer
        monkeypatch.setattr(pipeline_enforcer, "OVERRIDES_LOG", tmp_path / "mode_overrides.log")
        monkeypatch.setattr(pipeline_enforcer, "_MAX_LOG_LINES", 1000)

        # Write 1002 entries
        for i in range(1002):
            pipeline_enforcer._log_mode_override(
                f"task-{i}",
                "micro",
                "full",
                {"diff_lines": 1, "file_count": 1, "has_logic": False},
            )

        log_file = tmp_path / "mode_overrides.log"
        lines = log_file.read_text().strip().split("\n")
        # Should have exactly 1000 (last 1000 of 1002)
        assert len(lines) == 1000
        # First entry should be task-2 (0-indexed: 1002-1000=2)
        import json
        first_entry = json.loads(lines[0])
        assert first_entry["task_id"] == "task-2"
        last_entry = json.loads(lines[-1])
        assert last_entry["task_id"] == "task-1001"

    def test_get_mode_overrides_empty_when_no_file(self, tmp_path, monkeypatch):
        """get_mode_overrides returns [] when log file does not exist."""
        import pipeline_enforcer
        monkeypatch.setattr(pipeline_enforcer, "OVERRIDES_LOG", tmp_path / "nonexistent.log")
        entries = pipeline_enforcer.get_mode_overrides(limit=20)
        assert entries == []

    def test_get_mode_overrides_respects_zero_limit(self, tmp_path, monkeypatch):
        """limit=0 returns all entries."""
        import pipeline_enforcer
        monkeypatch.setattr(pipeline_enforcer, "OVERRIDES_LOG", tmp_path / "mode_overrides.log")
        monkeypatch.setattr(pipeline_enforcer, "_MAX_LOG_LINES", 1000)

        for i in range(5):
            pipeline_enforcer._log_mode_override(
                f"task-{i}", "micro", "full",
                {"diff_lines": 1, "file_count": 1, "has_logic": False},
            )
        entries = pipeline_enforcer.get_mode_overrides(limit=0)
        assert len(entries) == 5

    def test_validate_mode_fit_no_override_when_valid(self, tmp_path, monkeypatch):
        """No override is logged when mode is valid."""
        import pipeline_enforcer
        monkeypatch.setattr(pipeline_enforcer, "OVERRIDES_LOG", tmp_path / "mode_overrides.log")
        monkeypatch.setattr(pipeline_enforcer, "_MAX_LOG_LINES", 1000)

        diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1,2 @@\n-# old\n+# new"
        valid, reason, suggested = pipeline_enforcer.validate_mode_fit(
            "micro", diff, 1, task_id="task-valid"
        )
        assert valid is True
        log_file = tmp_path / "mode_overrides.log"
        assert not log_file.exists()

    def test_orchestrator_loop_get_mode_overrides(self, tmp_path, monkeypatch):
        """OrchestratorLoop.get_mode_overrides delegates to pipeline_enforcer."""
        import pipeline_enforcer
        monkeypatch.setattr(pipeline_enforcer, "OVERRIDES_LOG", tmp_path / "mode_overrides.log")
        monkeypatch.setattr(pipeline_enforcer, "_MAX_LOG_LINES", 1000)

        pipeline_enforcer._log_mode_override(
            "task-loop", "full", "micro",
            {"diff_lines": 1, "file_count": 1, "has_logic": False},
        )

        from task_db import TaskDB
        from orchestrator_loop import OrchestratorLoop
        db = TaskDB(":memory:")
        loop = OrchestratorLoop(db)
        overrides = loop.get_mode_overrides(limit=5)
        assert len(overrides) == 1
        assert overrides[0]["task_id"] == "task-loop"


# ── Learning loop tests ────────────────────────────────────────────────────────

class TestAnalyzeOverridePatterns:
    """Tests for analyze_override_patterns() and suggest_classifier_updates()."""

    def test_analyze_override_patterns_detects_logic_pattern(self, tmp_path, monkeypatch):
        """5 'micro->full with logic' entries are detected as a pattern."""
        import pipeline_enforcer
        monkeypatch.setattr(pipeline_enforcer, "OVERRIDES_LOG", tmp_path / "mode_overrides.log")
        monkeypatch.setattr(pipeline_enforcer, "_MAX_LOG_LINES", 1000)
        monkeypatch.setattr(pipeline_enforcer, "_reset_learning_state", lambda: None)
        # Simulate entries that chose full when micro was suggested, with logic
        for i in range(5):
            pipeline_enforcer._log_mode_override(
                f"task-{i}",
                "micro",
                "full",
                {"diff_lines": 2, "file_count": 1, "has_logic": True},
            )

        patterns = pipeline_enforcer.analyze_override_patterns(limit=20)
        assert len(patterns) > 0
        # Should find the micro->full with logic pattern
        logic_patterns = [p for p in patterns if "logic" in p["pattern"].lower()]
        assert len(logic_patterns) > 0
        # All 5 entries should be in the same pattern group
        logic_pattern = logic_patterns[0]
        assert logic_pattern["count"] == 5

    def test_analyze_override_patterns_empty_log(self, tmp_path, monkeypatch):
        """Empty override log → empty pattern list."""
        import pipeline_enforcer
        monkeypatch.setattr(pipeline_enforcer, "OVERRIDES_LOG", tmp_path / "empty.log")
        monkeypatch.setattr(pipeline_enforcer, "_reset_learning_state", lambda: None)
        patterns = pipeline_enforcer.analyze_override_patterns(limit=200)
        assert patterns == []

    def test_analyze_override_patterns_too_few_entries(self, tmp_path, monkeypatch):
        """Only 2 entries below threshold → no strong patterns (but still returns grouped)."""
        import pipeline_enforcer
        monkeypatch.setattr(pipeline_enforcer, "OVERRIDES_LOG", tmp_path / "mode_overrides.log")
        monkeypatch.setattr(pipeline_enforcer, "_MAX_LOG_LINES", 1000)
        monkeypatch.setattr(pipeline_enforcer, "_reset_learning_state", lambda: None)

        # 2 entries: micro->full with logic
        for i in range(2):
            pipeline_enforcer._log_mode_override(
                f"task-{i}",
                "micro",
                "full",
                {"diff_lines": 2, "file_count": 1, "has_logic": True},
            )

        suggestions = pipeline_enforcer.suggest_classifier_updates(threshold=3)
        # Below threshold=3 → should not suggest (classifier correct patterns are filtered)
        # Only micro->full with logic → "strict micro correct" → filtered out
        assert suggestions == []

    def test_suggest_classifier_updates_returns_actionable(self, tmp_path, monkeypatch):
        """5 micro->full small_clean entries → returns actionable relaxation suggestion."""
        import pipeline_enforcer
        monkeypatch.setattr(pipeline_enforcer, "OVERRIDES_LOG", tmp_path / "mode_overrides.log")
        monkeypatch.setattr(pipeline_enforcer, "_MAX_LOG_LINES", 1000)
        monkeypatch.setattr(pipeline_enforcer, "_reset_learning_state", lambda: None)

        # 5 entries: micro chosen when full suggested, small clean diff (no logic, <=3 lines, 1 file)
        for i in range(5):
            pipeline_enforcer._log_mode_override(
                f"task-{i}",
                "micro",
                "full",
                {"diff_lines": 2, "file_count": 1, "has_logic": False},
            )

        suggestions = pipeline_enforcer.suggest_classifier_updates(threshold=3)
        assert len(suggestions) > 0
        # Should surface the relaxation candidate
        assert any("relax" in s.lower() for s in suggestions)

    def test_suggest_classifier_updates_below_threshold(self, tmp_path, monkeypatch):
        """2 entries → below threshold=3 → empty suggestion list."""
        import pipeline_enforcer
        monkeypatch.setattr(pipeline_enforcer, "OVERRIDES_LOG", tmp_path / "mode_overrides.log")
        monkeypatch.setattr(pipeline_enforcer, "_MAX_LOG_LINES", 1000)
        monkeypatch.setattr(pipeline_enforcer, "_reset_learning_state", lambda: None)

        for i in range(2):
            pipeline_enforcer._log_mode_override(
                f"task-{i}",
                "micro",
                "full",
                {"diff_lines": 2, "file_count": 1, "has_logic": False},
            )

        suggestions = pipeline_enforcer.suggest_classifier_updates(threshold=3)
        assert suggestions == []

    def test_learning_loop_triggers_after_20_entries(self, tmp_path, monkeypatch):
        """Write 25 entries → auto-analysis fires at 20, classifier_insights.log is written."""
        import pipeline_enforcer
        monkeypatch.setattr(pipeline_enforcer, "OVERRIDES_LOG", tmp_path / "mode_overrides.log")
        monkeypatch.setattr(pipeline_enforcer, "_MAX_LOG_LINES", 1000)
        monkeypatch.setattr(pipeline_enforcer, "_AUTO_ANALYSIS_THRESHOLD", 20)
        monkeypatch.setattr(pipeline_enforcer, "_CLASSIFIER_INSIGHTS_LOG", tmp_path / "classifier_insights.log")
        # Reset counters so delta builds up from 0
        monkeypatch.setattr(pipeline_enforcer, "_LEARNING_COUNTER", 0)
        monkeypatch.setattr(pipeline_enforcer, "_LAST_ANALYZED_COUNT", 0)

        # Write 25 entries (delta reaches 20 at entry 20, triggering analysis)
        for i in range(25):
            pipeline_enforcer._log_mode_override(
                f"task-{i}",
                "micro",
                "full",
                {"diff_lines": 2, "file_count": 1, "has_logic": False},
            )

        insights_file = tmp_path / "classifier_insights.log"
        assert insights_file.exists(), "classifier_insights.log was not created after 20 entries"
        content = insights_file.read_text()
        assert "Auto-analysis" in content
        assert "Patterns found:" in content

    def test_get_learning_insights_on_orchestrator_loop(self, tmp_path, monkeypatch):
        """OrchestratorLoop.get_learning_insights delegates to suggest_classifier_updates."""
        import pipeline_enforcer
        monkeypatch.setattr(pipeline_enforcer, "OVERRIDES_LOG", tmp_path / "mode_overrides.log")
        monkeypatch.setattr(pipeline_enforcer, "_MAX_LOG_LINES", 1000)
        monkeypatch.setattr(pipeline_enforcer, "_reset_learning_state", lambda: None)

        # Write 5 micro->full small_clean entries (relaxation candidate)
        for i in range(5):
            pipeline_enforcer._log_mode_override(
                f"task-{i}",
                "micro",
                "full",
                {"diff_lines": 2, "file_count": 1, "has_logic": False},
            )

        from task_db import TaskDB
        from orchestrator_loop import OrchestratorLoop
        db = TaskDB(":memory:")
        loop = OrchestratorLoop(db)
        insights = loop.get_learning_insights(threshold=3)
        assert len(insights) > 0
        assert any("relax" in s.lower() for s in insights)


# ── detect_sensitive_change tests ─────────────────────────────────────────────

class TestDetectSensitiveChange:
    def test_detect_auth_in_filename(self):
        """Files with 'auth' in path → sensitive"""
        files = ["src/auth/login.py", "lib/auth.py"]
        is_sensitive, matched = detect_sensitive_change(files, "")
        assert is_sensitive is True
        assert len(matched) > 0
        assert all("auth" in f for f in matched)

    def test_detect_billing_in_filename(self):
        """Files with 'billing' in path → sensitive"""
        files = ["src/billing/stripe.py", "payments.py"]
        is_sensitive, matched = detect_sensitive_change(files, "")
        assert is_sensitive is True
        assert any("billing" in f for f in matched)

    def test_detect_migration_in_filename(self):
        """Files with 'migration' in path → sensitive"""
        files = ["db/migrate.py", "migrations/001_add_users.py"]
        is_sensitive, matched = detect_sensitive_change(files, "")
        assert is_sensitive is True
        assert any("migration" in f for f in matched)

    def test_detect_password_in_filename(self):
        """Files with 'password' in path → sensitive"""
        files = ["config.py", "passwords.py"]
        is_sensitive, matched = detect_sensitive_change(files, "")
        assert is_sensitive is True

    def test_detect_ignore_normal_files(self):
        """Normal files (README, .md) → not sensitive"""
        files = ["README.md", "docs/guide.md", "tests/test_foo.py"]
        is_sensitive, matched = detect_sensitive_change(files, "")
        assert is_sensitive is False
        assert matched == []

    def test_detect_multiple_sensitive_keywords(self):
        """Multiple keywords matched → all returned"""
        files = ["auth/token.py", "billing/payment.py", "db/migration.py"]
        is_sensitive, matched = detect_sensitive_change(files, "")
        assert is_sensitive is True
        assert len(matched) >= 2

    def test_detect_sensitive_change_empty_inputs(self):
        """Empty files and diff → not sensitive"""
        is_sensitive, matched = detect_sensitive_change([], "")
        assert is_sensitive is False
        assert matched == []

