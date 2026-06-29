"""Tests for scripts/no_telemetry.py — W9 no-telemetry posture gate."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import no_telemetry


# ── check_no_telemetry ────────────────────────────────────────────────────────

def test_clean_code_passes() -> None:
    code = "def add(a, b):\n    return a + b\n"
    clean, violations = no_telemetry.check_no_telemetry(code)
    assert clean
    assert violations == []


def test_sentry_import_blocked() -> None:
    code = "import sentry_sdk\nsentry_sdk.init(dsn='...')\n"
    clean, violations = no_telemetry.check_no_telemetry(code)
    assert not clean
    assert any("sentry" in v.lower() for v in violations)


def test_datadog_import_blocked() -> None:
    code = "import datadog\ndatadog.initialize(api_key='secret')\n"
    clean, violations = no_telemetry.check_no_telemetry(code)
    assert not clean
    assert any("datadog" in v.lower() for v in violations)


def test_requests_call_blocked() -> None:
    code = "import requests\nresults = requests.get('https://analytics.example.com/track')\n"
    clean, violations = no_telemetry.check_no_telemetry(code)
    assert not clean
    assert any("requests" in v.lower() for v in violations)


def test_httpx_call_blocked() -> None:
    code = "import httpx\nhttpx.post('https://events.io', json=data)\n"
    clean, violations = no_telemetry.check_no_telemetry(code)
    assert not clean
    assert any("httpx" in v.lower() for v in violations)


def test_boto3_import_blocked() -> None:
    code = "import boto3\ns3 = boto3.client('s3')\n"
    clean, violations = no_telemetry.check_no_telemetry(code)
    assert not clean
    assert any("boto3" in v.lower() for v in violations)


def test_posthog_import_blocked() -> None:
    code = "import posthog\nposthog.capture('user', 'event')\n"
    clean, violations = no_telemetry.check_no_telemetry(code)
    assert not clean
    assert any("posthog" in v.lower() for v in violations)


def test_opentelemetry_from_import_blocked() -> None:
    code = "from opentelemetry import trace\ntracer = trace.get_tracer('my.tracer')\n"
    clean, violations = no_telemetry.check_no_telemetry(code)
    assert not clean
    assert any("opentelemetry" in v.lower() for v in violations)


def test_multiple_violations_all_reported() -> None:
    code = "import sentry_sdk\nimport posthog\nrequests.get('http://x.com')\n"
    clean, violations = no_telemetry.check_no_telemetry(code)
    assert not clean
    assert len(violations) >= 2


# ── get_posture ───────────────────────────────────────────────────────────────

def test_posture_default_true_when_no_config() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        nonexistent = Path(tmp) / "missing.yaml"
        posture = no_telemetry.get_posture(nonexistent)
    assert posture is True


def test_posture_reads_config_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.yaml"
        cfg.write_text("no_telemetry: false\n", encoding="utf-8")
        posture = no_telemetry.get_posture(cfg)
    assert posture is False


def test_posture_true_from_config() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.yaml"
        cfg.write_text("no_telemetry: true\n", encoding="utf-8")
        posture = no_telemetry.get_posture(cfg)
    assert posture is True


# ── gate_check ────────────────────────────────────────────────────────────────

def test_gate_passes_clean_code() -> None:
    result = no_telemetry.gate_check("def foo(): pass")
    assert result["passed"]
    assert result["violations"] == []


def test_gate_blocks_telemetry() -> None:
    result = no_telemetry.gate_check("import sentry_sdk\nsentry_sdk.init()")
    assert not result["passed"]
    assert len(result["violations"]) >= 1
    assert "sentry" in result["reason"].lower()


def test_gate_skipped_when_posture_disabled() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.yaml"
        cfg.write_text("no_telemetry: false\n", encoding="utf-8")
        result = no_telemetry.gate_check("import sentry_sdk", config_path=cfg)
    assert result["passed"]
    assert "disabled" in result["reason"]
