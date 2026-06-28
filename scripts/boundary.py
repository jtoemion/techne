#!/usr/bin/env python3
"""boundary.py — W1 Immutable Trust Boundary (GRAND-PLAN-FINAL).

The boundary is the load-bearing safety mechanism for zero-HITL operation.
It runs at the tool-call layer, BEFORE any write reaches the filesystem.
Four mandatory layers, all deny-by-default:

  L1  network_egress  Block tool calls that attempt network access (bash/commands)
  L2  filesystem      Block writes outside the allowed project scope
  L3  secrets         Block writes containing credential patterns
  L4  config          Block writes to boundary-critical config files

Design: fail-closed (fail = block). If state is unreadable, block.
Every violation is logged to .techne/audit/boundary.jsonl with SHA chain.

Usage (from hooks):
    from boundary import check_tool_call, BoundaryResult
    result = check_tool_call(tool_name, tool_input, project_root)
    if not result.allowed:
        sys.exit(2)  # block

CLI self-test:
    python boundary.py --self-test
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# ── Network egress patterns (L1) ─────────────────────────────────────────────
# Commands and code patterns that indicate outbound network access.
# Allowlist: none by default. Set TECHNE_NETWORK_ALLOWLIST in .techne/config.yaml.
_NET_PATTERNS = [
    (r"\bcurl\b",             "curl"),
    (r"\bwget\b",             "wget"),
    (r"\bnc\b",               "netcat"),
    (r"requests\.(get|post|put|delete|patch|head)",  "requests.*"),
    (r"urllib\.request\.",    "urllib.request"),
    (r"\bfetch\s*\(",         "fetch()"),
    (r"\bhttp\.get\s*\(",     "http.get()"),
    (r"\baxios\.",            "axios"),
    (r"socket\.(connect|create_connection)", "socket.connect"),
    (r"subprocess.*\bcurl\b", "subprocess curl"),
    (r"subprocess.*\bwget\b", "subprocess wget"),
]

# ── Filesystem scope (L2) ────────────────────────────────────────────────────
# Paths outside the project root are always blocked.
# Internal deny-by-default paths: system dirs, other repos, etc.
_SCOPE_DENY_PREFIXES = [
    "/etc/", "/usr/", "/bin/", "/sbin/", "/lib/",
    "/proc/", "/sys/", "/dev/", "/boot/", "/root/",
    "C:\\Windows\\", "C:\\Program Files",
    "~/.ssh/", "~/.gnupg/", "~/.aws/", "~/.kube/",
]

# ── Secret patterns (L3) ────────────────────────────────────────────────────
_SECRET_PATTERNS = [
    (r'(?i)(api[_-]?key|apikey)\s*[:=]\s*["\']?[A-Za-z0-9_\-]{16,}', "API key"),
    (r'(?i)(password|passwd|pwd)\s*[:=]\s*["\']?[^\s"\']{6,}',        "password"),
    (r'(?i)(secret|token)\s*[:=]\s*["\']?[A-Za-z0-9_\-\.]{16,}',     "secret/token"),
    (r'(?i)(private[_-]?key)\s*[:=]',                                  "private key"),
    (r'-----BEGIN\s+(RSA|EC|DSA|OPENSSH)\s+PRIVATE KEY',               "PEM private key"),
    (r'(?i)(aws_access_key_id|aws_secret)\s*[:=]\s*\S{16,}',          "AWS credential"),
    (r'(?i)ghp_[A-Za-z0-9]{36}',                                       "GitHub token"),
    (r'(?i)sk-[A-Za-z0-9]{20,}',                                       "OpenAI key"),
    (r'(?i)xox[bpoa]-[A-Za-z0-9\-]{10,}',                             "Slack token"),
]

# ── Config file protection (L4) ──────────────────────────────────────────────
# Boundary-critical files the agent must not modify.
_PROTECTED_CONFIG = [
    ".claude/settings.json",        # Claude Code hook config — modifying disables boundary
    ".claude/settings.local.json",
    ".techne/audit/chain.jsonl",    # Audit trail — append-only, no overwrites
    ".techne/audit/boundary.jsonl",
    ".techne/gates/registry.json",  # Gate registry — only techne CLI may update
    "hooks/phase_guard_hook.py",    # The hook itself
    "scripts/boundary.py",          # This file
]

# Extensions that are always protected regardless of path
_PROTECTED_EXTENSIONS = {".pem", ".key", ".p12", ".pfx", ".cer", ".crt", ".ppk"}


@dataclass
class LayerResult:
    layer: str   # "L1_network" | "L2_filesystem" | "L3_secrets" | "L4_config"
    passed: bool
    reason: str = ""


@dataclass
class BoundaryResult:
    allowed: bool
    violations: list[LayerResult] = field(default_factory=list)
    all_layers: list[LayerResult] = field(default_factory=list)

    @property
    def block_reason(self) -> str:
        reasons = [v.reason for v in self.violations]
        return "; ".join(reasons) if reasons else ""


# ── Layer implementations ────────────────────────────────────────────────────

def _check_network_egress(tool_name: str, tool_input: dict) -> LayerResult:
    """L1: Block Bash commands that attempt outbound network access."""
    if tool_name != "Bash":
        return LayerResult("L1_network", True)
    cmd = tool_input.get("command", "")
    if not cmd:
        return LayerResult("L1_network", True)
    for pattern, label in _NET_PATTERNS:
        if re.search(pattern, cmd):
            return LayerResult(
                "L1_network", False,
                f"network egress blocked: '{label}' detected in bash command. "
                f"Add to TECHNE_NETWORK_ALLOWLIST to permit."
            )
    return LayerResult("L1_network", True)


def _check_filesystem_scope(tool_name: str, tool_input: dict,
                             project_root: Path) -> LayerResult:
    """L2: Block writes outside the project root or to system directories."""
    write_tools = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
    if tool_name not in write_tools:
        return LayerResult("L2_filesystem", True)

    path_str = (tool_input.get("file_path") or
                tool_input.get("notebook_path") or "")
    if not path_str:
        return LayerResult("L2_filesystem", True)

    # Check system prefixes first (platform-independent substring check)
    for prefix in _SCOPE_DENY_PREFIXES:
        if path_str.startswith(prefix) or path_str.startswith(
                prefix.replace("/", "\\")
        ):
            return LayerResult(
                "L2_filesystem", False,
                f"filesystem boundary: write to system path blocked: {path_str}"
            )

    # Resolve and check the path is within project root
    try:
        resolved = Path(path_str).resolve()
        resolved.relative_to(project_root.resolve())
    except ValueError:
        return LayerResult(
            "L2_filesystem", False,
            f"filesystem boundary: write outside project root blocked: {path_str}"
        )

    return LayerResult("L2_filesystem", True)


def _check_secrets(tool_name: str, tool_input: dict) -> LayerResult:
    """L3: Block writes that contain hardcoded credential patterns."""
    write_tools = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
    if tool_name not in write_tools:
        return LayerResult("L3_secrets", True)

    # Collect all content fields
    content_parts = []
    for key in ("content", "new_string", "edits"):
        v = tool_input.get(key)
        if isinstance(v, str):
            content_parts.append(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    content_parts.append(item.get("new_string", ""))

    content = "\n".join(content_parts)
    if not content:
        return LayerResult("L3_secrets", True)

    for pattern, label in _SECRET_PATTERNS:
        m = re.search(pattern, content)
        if m:
            # Allow test fixtures and example placeholders
            ctx = content[max(0, m.start()-40):m.end()+40]
            if re.search(r"(test|example|placeholder|dummy|fake|mock|YOUR_)", ctx, re.I):
                continue
            return LayerResult(
                "L3_secrets", False,
                f"secret scan: possible {label} detected in written content. "
                f"Use environment variables or a secrets manager."
            )
    return LayerResult("L3_secrets", True)


def _check_config_protection(tool_name: str, tool_input: dict,
                              project_root: Path) -> LayerResult:
    """L4: Block writes to boundary-critical config files."""
    write_tools = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
    if tool_name not in write_tools:
        return LayerResult("L4_config", True)

    path_str = (tool_input.get("file_path") or
                tool_input.get("notebook_path") or "")
    if not path_str:
        return LayerResult("L4_config", True)

    # Check protected extension
    if Path(path_str).suffix.lower() in _PROTECTED_EXTENSIONS:
        return LayerResult(
            "L4_config", False,
            f"config protection: write to credential file blocked: {path_str}"
        )

    # Normalize to forward slashes for comparison
    norm = path_str.replace("\\", "/").lstrip("/")
    for protected in _PROTECTED_CONFIG:
        if norm == protected or norm.endswith("/" + protected):
            return LayerResult(
                "L4_config", False,
                f"config protection: write to boundary-critical file blocked: {path_str}. "
                f"Only techne CLI may update this file."
            )

    return LayerResult("L4_config", True)


# ── Main entry point ─────────────────────────────────────────────────────────

def check_tool_call(
    tool_name: str,
    tool_input: dict,
    project_root: Path | None = None,
) -> BoundaryResult:
    """Run all four boundary layers. Fail-closed: any violation blocks."""
    root = project_root or Path.cwd()
    layers = [
        _check_network_egress(tool_name, tool_input),
        _check_filesystem_scope(tool_name, tool_input, root),
        _check_secrets(tool_name, tool_input),
        _check_config_protection(tool_name, tool_input, root),
    ]
    violations = [l for l in layers if not l.passed]
    return BoundaryResult(
        allowed=len(violations) == 0,
        violations=violations,
        all_layers=layers,
    )


# ── Audit logging ─────────────────────────────────────────────────────────────

def log_violation(
    tool_name: str,
    layer: str,
    reason: str,
    project_root: Path | None = None,
) -> None:
    """Append a SHA-chained violation record to .techne/audit/boundary.jsonl."""
    root = project_root or Path.cwd()
    log_path = root / ".techne" / "audit" / "boundary.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    prev_hash = ""
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        if lines:
            try:
                prev_hash = json.loads(lines[-1]).get("hash", "")
            except Exception:
                pass

    entry = {
        "ts": time.time(),
        "tool": tool_name,
        "layer": layer,
        "reason": reason,
    }
    payload = json.dumps(entry, sort_keys=True)
    entry["hash"] = hashlib.sha256(f"{prev_hash}{payload}".encode()).hexdigest()

    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── Self-test ─────────────────────────────────────────────────────────────────

def _self_test() -> int:
    """Probe each layer to verify it's functioning. Prints pass/fail per check."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    root = Path.cwd()
    ok = True
    checks: list[tuple[str, bool, str]] = []

    def _check(label: str, result: BoundaryResult, expect_allowed: bool) -> None:
        nonlocal ok
        passed = result.allowed == expect_allowed
        if not passed:
            ok = False
        status = "PASS" if passed else "FAIL"
        detail = result.block_reason if not result.allowed else "allowed"
        checks.append((label, passed, f"[{status}] {detail}"))

    # L1 — network egress
    _check("L1 curl blocked",
           check_tool_call("Bash", {"command": "curl https://example.com"}, root),
           expect_allowed=False)
    _check("L1 safe bash allowed",
           check_tool_call("Bash", {"command": "pytest -q tests/"}, root),
           expect_allowed=True)
    _check("L1 non-bash tool exempt",
           check_tool_call("Read", {"file_path": "foo.py"}, root),
           expect_allowed=True)

    # L2 — filesystem scope
    _check("L2 system path blocked",
           check_tool_call("Write", {"file_path": "/etc/passwd"}, root),
           expect_allowed=False)
    _check("L2 project path allowed",
           check_tool_call("Write", {"file_path": str(root / "src" / "foo.py")}, root),
           expect_allowed=True)

    # L3 — secrets
    _check("L3 API key blocked",
           check_tool_call("Write", {
               "file_path": "config.py",
               "content": 'api_key = "sk-abcdefghijklmnopqrstuvwxyz1234"'
           }, root),
           expect_allowed=False)
    _check("L3 test fixture allowed",
           check_tool_call("Write", {
               "file_path": "tests/test_auth.py",
               "content": 'api_key = "test_fake_placeholder_key_1234567890"'
           }, root),
           expect_allowed=True)

    # L4 — config protection
    _check("L4 settings.json blocked",
           check_tool_call("Write", {"file_path": ".claude/settings.json"}, root),
           expect_allowed=False)
    _check("L4 .pem file blocked",
           check_tool_call("Write", {"file_path": "deploy/server.pem"}, root),
           expect_allowed=False)
    _check("L4 normal source allowed",
           check_tool_call("Write", {"file_path": "src/app.py"}, root),
           expect_allowed=True)

    print("=== Boundary Self-Test ===")
    for label, passed, detail in checks:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {label}: {detail}")
    print()
    overall = "ALL PASS" if ok else f"FAILED ({sum(1 for _, p, _ in checks if not p)} failures)"
    print(f"  Result: {overall}")
    return 0 if ok else 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import argparse
    p = argparse.ArgumentParser(description="W1 Immutable Trust Boundary")
    p.add_argument("--self-test", action="store_true",
                   help="Probe each boundary layer and report pass/fail")
    p.add_argument("--tool", help="Tool name (for manual check)")
    p.add_argument("--input", help="Tool input JSON string (for manual check)")
    args = p.parse_args()

    if args.self_test:
        return _self_test()

    if args.tool and args.input:
        try:
            inp = json.loads(args.input)
        except json.JSONDecodeError as e:
            print(f"Bad JSON input: {e}")
            return 1
        result = check_tool_call(args.tool, inp, Path.cwd())
        print(json.dumps({
            "allowed": result.allowed,
            "violations": [{"layer": v.layer, "reason": v.reason}
                           for v in result.violations],
        }, indent=2))
        return 0 if result.allowed else 1

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
