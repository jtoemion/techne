#!/usr/bin/env python3
"""no_telemetry.py — W9 no-telemetry posture (GRAND-PLAN-FINAL §9.13).

Techne's default posture is zero external data exfiltration. This module:

1. Reads the posture flag from .techne/config.yaml (`no_telemetry: true`, the default).
2. Provides a gate function `check_no_telemetry(artifact)` that scans IMPLEMENT
   artifacts for patterns that would phone home — analytics SDKs, HTTP calls to
   external hosts, tracking pixels, etc.
3. Exposes `get_posture()` for the pipeline to verify the flag at startup.

The gate is conservative: it blocks on *import* of known telemetry libraries, not
just on calls, because the harness can't prove the import is unused.

Allowed patterns (internal logging only):
  - File I/O to .techne/
  - subprocess calls with no network flag
  - logging.getLogger / print / sys.stderr

Blocked patterns (external exfiltration risk):
  - requests / httpx / aiohttp / urllib calls to external hosts
  - Known analytics SDKs: sentry_sdk, segment, mixpanel, amplitude, posthog,
    datadog, opentelemetry, honeybadger, rollbar, bugsnag, newrelic, logrocket
  - boto3 / google.cloud / azure (cloud storage uploads)
  - socket.connect / asyncio open_connection to non-localhost
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _ROOT / ".techne" / "config.yaml"

# ── telemetry pattern catalogue ───────────────────────────────────────────────

_TELEMETRY_PATTERNS: list[tuple[str, str]] = [
    # Analytics / error-tracking SDKs
    (r"\bimport\s+sentry_sdk\b",              "sentry_sdk import"),
    (r"\bfrom\s+sentry_sdk\b",               "sentry_sdk import"),
    (r"\bimport\s+segment\b",                "segment import"),
    (r"\bimport\s+mixpanel\b",               "mixpanel import"),
    (r"\bimport\s+amplitude\b",              "amplitude import"),
    (r"\bimport\s+posthog\b",               "posthog import"),
    (r"\bimport\s+datadog\b",               "datadog import"),
    (r"\bfrom\s+datadog\b",                 "datadog import"),
    (r"\bimport\s+opentelemetry\b",         "opentelemetry import"),
    (r"\bfrom\s+opentelemetry\b",           "opentelemetry import"),
    (r"\bimport\s+honeybadger\b",           "honeybadger import"),
    (r"\bimport\s+rollbar\b",               "rollbar import"),
    (r"\bimport\s+bugsnag\b",               "bugsnag import"),
    (r"\bimport\s+newrelic\b",              "newrelic import"),
    (r"\bimport\s+logrocket\b",             "logrocket import"),
    # Cloud upload SDKs (could exfiltrate data)
    (r"\bimport\s+boto3\b",                 "boto3 (AWS SDK) import"),
    (r"\bfrom\s+boto3\b",                   "boto3 (AWS SDK) import"),
    (r"\bfrom\s+google\.cloud\b",           "google.cloud import"),
    (r"\bfrom\s+azure\b",                   "azure SDK import"),
    # Raw HTTP to non-localhost
    (r"requests\.(get|post|put|delete|patch|head)\s*\(",    "outbound HTTP call (requests)"),
    (r"httpx\.(get|post|put|delete|patch|head)\s*\(",       "outbound HTTP call (httpx)"),
    (r"aiohttp\.ClientSession\s*\(",                        "outbound HTTP (aiohttp)"),
    (r"urllib\.request\.urlopen\s*\(",                      "outbound HTTP (urllib)"),
    (r"http\.client\.HTTPConnection\s*\(",                  "outbound HTTP (http.client)"),
    # Socket egress
    (r"socket\.connect\s*\(",               "raw socket connect"),
    (r"asyncio\.open_connection\s*\(",      "asyncio outbound connection"),
]

_COMPILED = [(re.compile(pat), label) for pat, label in _TELEMETRY_PATTERNS]


# ── posture flag ──────────────────────────────────────────────────────────────

def get_posture(config_path: Optional[Path] = None) -> bool:
    """Return True if no-telemetry posture is active (default: True).

    Reads `no_telemetry:` from .techne/config.yaml, then checks
    TECHNE_NO_TELEMETRY env var (1/true/yes = active, 0/false/no = inactive).
    The env var takes precedence over config.
    """
    env_val = os.environ.get("TECHNE_NO_TELEMETRY", "").lower()
    if env_val in ("1", "true", "yes"):
        return True
    if env_val in ("0", "false", "no"):
        return False

    cfg = config_path or _CONFIG_PATH
    if cfg.exists():
        try:
            import yaml
            data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            return bool(data.get("no_telemetry", True))   # default True
        except Exception:
            pass

    return True   # fail-safe: default to no-telemetry


# ── gate function ─────────────────────────────────────────────────────────────

def check_no_telemetry(text: str) -> tuple[bool, list[str]]:
    """Scan *text* for telemetry patterns.

    Returns (clean, violations) where:
      clean      — True if no violations found
      violations — list of human-readable violation strings
    """
    violations = []
    for pattern, label in _COMPILED:
        if pattern.search(text):
            violations.append(label)
    return (len(violations) == 0), violations


def gate_check(artifact: str, *, config_path: Optional[Path] = None) -> dict:
    """Run the no-telemetry gate on an IMPLEMENT artifact.

    Returns a gate-result dict: {"passed": bool, "reason": str, "violations": list}.
    """
    if not get_posture(config_path):
        return {"passed": True, "reason": "no-telemetry posture disabled", "violations": []}

    clean, violations = check_no_telemetry(artifact)
    if clean:
        return {"passed": True, "reason": "no telemetry patterns detected", "violations": []}
    return {
        "passed": False,
        "reason": f"telemetry gate blocked: {', '.join(violations)}",
        "violations": violations,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import argparse
    p = argparse.ArgumentParser(description="No-telemetry posture check — W9")
    p.add_argument("--posture", action="store_true", help="Show current posture flag")
    p.add_argument("--check", metavar="FILE", help="Check a file for telemetry patterns")
    p.add_argument("--list-patterns", action="store_true", help="List all blocked patterns")
    args = p.parse_args()

    if args.posture:
        active = get_posture()
        print(f"  no_telemetry posture: {'ACTIVE' if active else 'inactive'}")
        return 0

    if args.list_patterns:
        print("  Blocked telemetry patterns:")
        for _, label in _TELEMETRY_PATTERNS:
            print(f"    - {label}")
        return 0

    if args.check:
        text = Path(args.check).read_text(encoding="utf-8", errors="replace")
        result = gate_check(text)
        if result["passed"]:
            print(f"  CLEAN — {result['reason']}")
        else:
            print(f"  BLOCKED — {result['reason']}")
            for v in result["violations"]:
                print(f"    * {v}")
        return 0 if result["passed"] else 1

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
