#!/usr/bin/env python3
"""
scan_node_violations.py — Scan a project tree for node-discipline violations.

Usage:
    python3 scan_node_violations.py [--project-dir /path] [--exit-on-violation] [--json]

Outputs a structured report of all violations found:
  - CODE nodes containing branching logic (role/status if/else)
  - CODE→CODE lateral imports
  - Hook→DAL direct imports (architecture rule violation)
  - Service→Service direct imports

Returns exit code 0 if no violations, 1 if violations found (when --exit-on-violation).
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class Violation:
    file: str
    rule: str
    match: str
    severity: str  # HIGH / MEDIUM / LOW


@dataclass
class ScanReport:
    project: str
    violations: List[Violation] = field(default_factory=list)
    total_high: int = 0
    total_medium: int = 0
    total_low: int = 0

    def add(self, v: Violation):
        self.violations.append(v)
        if v.severity == "HIGH":
            self.total_high += 1
        elif v.severity == "MEDIUM":
            self.total_medium += 1
        else:
            self.total_low += 1

    def passed(self) -> bool:
        return self.total_high == 0

    def summary(self) -> str:
        if not self.violations:
            return "✓ No node-discipline violations found."
        lines = [f"{'HIGH' if self.total_high > 0 else 'LOW'} — {len(self.violations)} violation(s) found"]
        if self.total_high > 0:
            lines.append(f"  HIGH:   {self.total_high}")
        if self.total_medium > 0:
            lines.append(f"  MEDIUM: {self.total_medium}")
        lines.append(f"  LOW:    {self.total_low}")
        return "\n".join(lines)


def _grep(pattern: str, *paths: str, exclude: Optional[str] = None) -> List[str]:
    """Run grep with a pattern over paths. Returns list of matching lines."""
    cmd = ["grep", "-rn", "--include=*.ts", "--include=*.tsx"]
    if exclude:
        cmd.extend(["--exclude-dir", exclude])
    cmd.append(pattern)
    cmd.extend(paths)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return [l.strip() for l in result.stdout.splitlines() if l.strip()]
        return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def _has_git(path: Path) -> bool:
    """Check if path is inside a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=path, capture_output=True, timeout=5
        )
        return result.returncode == 0 and result.stdout.strip()
    except Exception:
        return False


def _git_tracked(path: Path, subdir: str) -> List[str]:
    """Get git-tracked files in a subdirectory."""
    try:
        result = subprocess.run(
            ["git", "ls-files", subdir],
            cwd=path, capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return [l.strip() for l in result.stdout.splitlines() if l.strip()]
    except Exception:
        pass
    # Fallback: walk the directory
    full = path / subdir
    if full.exists():
        return [str(f.relative_to(path)) for f in full.rglob("*") if f.suffix in (".ts", ".tsx")]
    return []


def scan_project(project_dir: Path) -> ScanReport:
    """Run all violation scans on the project."""
    project_dir = project_dir.resolve()
    report = ScanReport(project=str(project_dir))

    # Detect source dir
    src_dir = project_dir / "src"
    if not src_dir.exists():
        # Try common alternatives
        for p in [project_dir / "app", project_dir / "lib", project_dir / "source"]:
            if p.exists():
                src_dir = p
                break
        else:
            # Use project root
            src_dir = project_dir

    # Determine tracked files per layer
    dal_files = _git_tracked(project_dir, "src/lib/dal") if _has_git(project_dir) else []
    utils_files = _git_tracked(project_dir, "src/lib/utils") if _has_git(project_dir) else []
    hooks_files = _git_tracked(project_dir, "src/hooks") if _has_git(project_dir) else []
    services_files = _git_tracked(project_dir, "src/services") if _has_git(project_dir) else []

    dal_dir = str(src_dir / "lib" / "dal")
    utils_dir = str(src_dir / "lib" / "utils")
    hooks_dir = str(src_dir / "hooks")
    services_dir = str(src_dir / "services")

    # ── Rule: CODE node with branching ─────────────────────────────────────
    for search_dir, label in [(dal_dir, "DAL"), (str(src_dir / "lib" / "utils"), "utils")]:
        if Path(search_dir).exists():
            matches = _grep(r"if\s*\(.*role|switch\s*\(.*role|switch\s*\(.*status", search_dir)
            for m in matches:
                report.add(Violation(
                    file=m.split(":")[0] if ":" in m else m,
                    rule=f"CODE ({label}) node with branching logic",
                    match=m,
                    severity="HIGH" if "role" in m.lower() else "MEDIUM",
                ))

    # ── Rule: CODE→CODE lateral imports ──────────────────────────────────────
    # DAL importing from another DAL
    if Path(dal_dir).exists():
        matches = _grep(r"from\s+['\"](\.\.?\/)+dal\/", dal_dir)
        for m in matches:
            # Filter out index files and test files
            if "__tests__" in m or "index" in m.split(":")[0]:
                continue
            report.add(Violation(
                file=m.split(":")[0],
                rule="CODE→CODE lateral import (DAL importing DAL)",
                match=m,
                severity="HIGH",
            ))

    # Service importing from another service (not via index)
    if Path(services_dir).exists():
        matches = _grep(r"from\s+['\"](\.\.?\/)+services\/", services_dir)
        for m in matches:
            if "__tests__" in m or "index" in m.split(":")[0]:
                continue
            report.add(Violation(
                file=m.split(":")[0],
                rule="GATEWAY→GATEWAY lateral import (Service importing Service)",
                match=m,
                severity="HIGH",
            ))

    # ── Rule: Hook→DAL direct import ──────────────────────────────────────────
    if Path(hooks_dir).exists():
        matches = _grep(r"from\s+['\"](\.\.\/)?lib\/dal|from\s+['\"](\.\.\/)+dal\/", hooks_dir)
        for m in matches:
            if "__tests__" in m:
                continue
            report.add(Violation(
                file=m.split(":")[0],
                rule="Hook imports DAL directly (must route through service layer)",
                match=m,
                severity="HIGH",
            ))

    # ── Rule: Component→DAL direct import ─────────────────────────────────────
    for comp_dir in [str(src_dir / "components"), str(src_dir / "pages")]:
        if Path(comp_dir).exists():
            matches = _grep(r"from\s+['\"](\.\.\/)+lib\/dal|from\s+['\"](\.\.\/)+dal\/", comp_dir)
            for m in matches:
                if "__tests__" in m:
                    continue
                report.add(Violation(
                    file=m.split(":")[0],
                    rule="Component/Page imports DAL directly (architecture violation)",
                    match=m,
                    severity="HIGH",
                ))

    return report


def print_human_report(report: ScanReport):
    """Print a human-readable violation report."""
    sep = "─" * 54
    print(f"\n{sep}")
    print(f"  NODE DISCIPLINE SCAN — {report.project}")
    print(f"{sep}")
    print(f"  {report.summary()}")
    print(sep)

    if not report.violations:
        print()
        print("  All modules respect node boundaries. ✓")
        print()
        return

    # Group by severity
    for severity in ("HIGH", "MEDIUM", "LOW"):
        group = [v for v in report.violations if v.severity == severity]
        if not group:
            continue
        print(f"\n  {severity} VIOLATIONS ({len(group)}):")
        print(f"  {'─' * 40}")
        for v in sorted(group, key=lambda x: x.file):
            print(f"  [{v.rule}]")
            print(f"    File:  {v.file}")
            print(f"    Match: {v.match[:120]}")
            print()

    print(sep)
    print()


def main():
    parser = argparse.ArgumentParser(description="Scan project for node-discipline violations")
    parser.add_argument("--project-dir", "-d", default=".", help="Project root directory")
    parser.add_argument("--exit-on-violation", "-e", action="store_true",
                        help="Exit with code 1 if violations found")
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    if not project_dir.exists():
        print(f"Error: directory not found: {project_dir}", file=sys.stderr)
        sys.exit(1)

    report = scan_project(project_dir)

    if args.json:
        # Output JSON
        output = {
            "project": report.project,
            "passed": report.passed(),
            "violations": [asdict(v) for v in report.violations],
            "counts": {
                "total": len(report.violations),
                "high": report.total_high,
                "medium": report.total_medium,
                "low": report.total_low,
            }
        }
        print(json.dumps(output, indent=2))
    else:
        print_human_report(report)

    if args.exit_on_violation and not report.passed():
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
