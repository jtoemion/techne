"""
Example plugin: security-focused gates.

Demonstrates how to write a Techne gate plugin.
Drop a .py file in harness/plugins/, define register(registry), done.

To enable: add "security" to active_stacks in gate-config.yaml.
"""
import re

from harness.gates import GateViolation, _strip_diff_marker, _is_comment


def _gate_no_hardcoded_secrets(diff: str):
    """Reject diffs that add hardcoded API keys, tokens, or passwords."""
    patterns = [
        (r'api[_-]?key\s*[:=]\s*["\'][^"\']{8,}', "API key"),
        (r'password\s*[:=]\s*["\'][^"\']{4,}', "password"),
        (r'token\s*[:=]\s*["\'][^"\']{8,}', "token"),
        (r'secret\s*[:=]\s*["\'][^"\']{8,}', "secret"),
    ]
    for i, line in enumerate(diff.splitlines()):
        if not line.startswith("+") or line.startswith("+++"):
            continue
        code = _strip_diff_marker(line)
        if _is_comment(code):
            continue
        for pattern, label in patterns:
            if re.search(pattern, code, re.IGNORECASE):
                raise GateViolation(
                    f"GATE FAIL [security/hardcoded-secret]: possible hardcoded {label} on line {i+1}.\n"
                    f"Use environment variables or a secrets manager.\n"
                    f"  → {line.strip()}"
                )


def _gate_no_eval_usage(diff: str):
    """Reject eval() usage — common XSS/code injection vector."""
    for i, line in enumerate(diff.splitlines()):
        if not line.startswith("+") or line.startswith("+++"):
            continue
        code = _strip_diff_marker(line)
        if _is_comment(code):
            continue
        if re.search(r'\beval\s*\(', code):
            raise GateViolation(
                f"GATE FAIL [security/eval]: eval() found on line {i+1}.\n"
                f"eval() is a code injection risk. Use a safe alternative.\n"
                f"  → {line.strip()}"
            )


def register(registry):
    """Register security gates."""
    registry.register(
        "security/hardcoded-secret", _gate_no_hardcoded_secrets,
        stack="security", category="hard",
        description="reject hardcoded API keys, tokens, passwords",
    )
    registry.register(
        "security/eval", _gate_no_eval_usage,
        stack="security", category="hard",
        description="reject eval() usage",
    )
