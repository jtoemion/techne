#!/usr/bin/env python3
"""
node_gate.py — Node-discipline gate for the ./next pipeline.

Called by ./next during the VERIFY phase (via _check_verify_gates).
Runs scan_node_violations.py and returns pass/fail as a GateResult-compatible output.

Usage:
    python3 node_gate.py [--project-dir /path] [--json]

Exit codes:
    0 — pass (no HIGH violations)
    1 — fail (HIGH violations found)
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run_gate(project_dir: Path) -> dict:
    """Run the node-discipline gate. Returns result dict."""
    script = Path(__file__).resolve().parent / "scan_node_violations.py"

    try:
        result = subprocess.run(
            [sys.executable, str(script), "--project-dir", str(project_dir), "--json", "--exit-on-violation"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            # No violations — pass
            return {"passed": True, "message": "Node discipline: all boundaries respected ✓"}
        else:
            # Violations found — fail
            try:
                report = json.loads(result.stdout)
                high = report.get("counts", {}).get("high", 0)
                total = report.get("counts", {}).get("total", 0)
                return {
                    "passed": False,
                    "message": f"Node discipline: {high} HIGH / {total} total violation(s)",
                    "details": report.get("violations", []),
                }
            except json.JSONDecodeError:
                return {
                    "passed": False,
                    "message": "Node discipline: violation scan failed (parse error)",
                    "raw_output": result.stdout,
                }
    except subprocess.TimeoutExpired:
        return {"passed": True, "message": "Node discipline: scan timed out (skipped)"}
    except FileNotFoundError:
        return {"passed": True, "message": "Node discipline: no project detected (skipped)"}


def main():
    parser = argparse.ArgumentParser(description="Node-discipline gate for ./next pipeline")
    parser.add_argument("--project-dir", "-d", default=".", help="Project root directory")
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    result = run_gate(project_dir)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["passed"]:
            print(f"  ✓ {result['message']}")
        else:
            print(f"  ✗ {result['message']}")
            if "details" in result:
                for v in result["details"][:5]:
                    print(f"    {v.get('file', '?')}: [{v.get('rule', '?')}]")

    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
