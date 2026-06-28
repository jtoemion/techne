"""Tests for scripts/boundary.py — W1 Immutable Trust Boundary."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import boundary


ROOT = REPO_ROOT  # use repo root as the project_root in tests


# ── L1: network egress ───────────────────────────────────────────────────────

def test_l1_curl_blocked() -> None:
    r = boundary.check_tool_call("Bash", {"command": "curl https://example.com"}, ROOT)
    assert not r.allowed
    assert any(v.layer == "L1_network" for v in r.violations)


def test_l1_wget_blocked() -> None:
    r = boundary.check_tool_call("Bash", {"command": "wget https://example.com -O out.txt"}, ROOT)
    assert not r.allowed


def test_l1_requests_blocked() -> None:
    r = boundary.check_tool_call("Bash", {"command": "python -c 'import requests; requests.get(url)'"}, ROOT)
    assert not r.allowed


def test_l1_safe_pytest_allowed() -> None:
    r = boundary.check_tool_call("Bash", {"command": "pytest -q tests/"}, ROOT)
    assert r.allowed


def test_l1_non_bash_not_checked() -> None:
    r = boundary.check_tool_call("Read", {"file_path": "foo.py"}, ROOT)
    assert r.allowed  # Read tool is not network-gated


# ── L2: filesystem scope ─────────────────────────────────────────────────────

def test_l2_system_path_blocked() -> None:
    r = boundary.check_tool_call("Write", {"file_path": "/etc/passwd", "content": "x"}, ROOT)
    assert not r.allowed
    assert any(v.layer == "L2_filesystem" for v in r.violations)


def test_l2_outside_project_blocked() -> None:
    r = boundary.check_tool_call("Write", {"file_path": "/tmp/evil.py", "content": "x"}, ROOT)
    assert not r.allowed


def test_l2_project_path_allowed() -> None:
    r = boundary.check_tool_call("Write", {
        "file_path": str(ROOT / "src" / "foo.py"), "content": "x"
    }, ROOT)
    assert r.allowed


# ── L3: secrets ─────────────────────────────────────────────────────────────

def test_l3_api_key_blocked() -> None:
    r = boundary.check_tool_call("Write", {
        "file_path": str(ROOT / "config.py"),
        "content": 'API_KEY = "sk-abcdefghijklmnopqrstuvwxyz123456"'
    }, ROOT)
    assert not r.allowed
    assert any(v.layer == "L3_secrets" for v in r.violations)


def test_l3_pem_key_blocked() -> None:
    r = boundary.check_tool_call("Write", {
        "file_path": str(ROOT / "config.py"),
        "content": "-----BEGIN RSA PRIVATE KEY-----\nMIIE..."
    }, ROOT)
    assert not r.allowed


def test_l3_test_fixture_allowed() -> None:
    r = boundary.check_tool_call("Write", {
        "file_path": str(ROOT / "tests" / "test_auth.py"),
        "content": 'api_key = "fake_placeholder_test_key_1234567890abcdef"'
    }, ROOT)
    assert r.allowed  # test/example fixtures are exempted


def test_l3_normal_code_allowed() -> None:
    r = boundary.check_tool_call("Write", {
        "file_path": str(ROOT / "src" / "app.py"),
        "content": "def main():\n    return 0\n"
    }, ROOT)
    assert r.allowed


# ── L4: config protection ────────────────────────────────────────────────────

def test_l4_settings_json_blocked() -> None:
    r = boundary.check_tool_call("Write", {
        "file_path": ".claude/settings.json", "content": "{}"
    }, ROOT)
    assert not r.allowed
    assert any(v.layer == "L4_config" for v in r.violations)


def test_l4_pem_extension_blocked() -> None:
    r = boundary.check_tool_call("Write", {
        "file_path": str(ROOT / "deploy" / "server.pem"), "content": "cert"
    }, ROOT)
    assert not r.allowed


def test_l4_audit_chain_blocked() -> None:
    r = boundary.check_tool_call("Edit", {
        "file_path": ".techne/audit/chain.jsonl", "old_string": "x", "new_string": "y"
    }, ROOT)
    assert not r.allowed


def test_l4_normal_source_allowed() -> None:
    r = boundary.check_tool_call("Write", {
        "file_path": str(ROOT / "src" / "app.py"), "content": "x = 1"
    }, ROOT)
    assert r.allowed


# ── BoundaryResult structure ──────────────────────────────────────────────────

def test_result_allowed_has_no_violations() -> None:
    r = boundary.check_tool_call("Bash", {"command": "echo hello"}, ROOT)
    assert r.allowed
    assert r.violations == []
    assert r.block_reason == ""


def test_result_blocked_has_violations() -> None:
    r = boundary.check_tool_call("Bash", {"command": "curl http://evil.com"}, ROOT)
    assert not r.allowed
    assert len(r.violations) >= 1
    assert r.block_reason != ""


def test_all_layers_always_returned() -> None:
    r = boundary.check_tool_call("Bash", {"command": "echo ok"}, ROOT)
    assert len(r.all_layers) == 4
    layer_names = {l.layer for l in r.all_layers}
    assert layer_names == {"L1_network", "L2_filesystem", "L3_secrets", "L4_config"}
