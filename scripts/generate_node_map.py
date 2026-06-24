#!/usr/bin/env python3
"""
generate_node_map.py — Generate an ASCII node topology diagram from a project tree.

Walks the project's .ts/.tsx files, classifies each as TRIGGER/CODE/GATEWAY,
traces import dependencies, and outputs an ASCII data-flow diagram + inventory table.

Usage:
    python3 generate_node_map.py [--project-dir /path] [--output /path/to/map.md]
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple


def _classify_path(file_path: str) -> str:
    """Quick path-based classification (same logic as classify_module)."""
    if re.search(r"src/pages/|src/App\.tsx$|src/cloud-functions/|src/contexts/|src/scripts/", file_path):
        return "TRIGGER"
    if re.search(r"src/lib/dal/|src/lib/utils/|src/lib/auth/pin|src/lib/auth/token|src/lib/auth/userProfile|src/lib/llm/|src/lib/pdf/|src/lib/report-card/|src/lib/migrations/|src/lib/constants|src/lib/formatters|src/lib/dateUtils|src/lib/logger|src/lib/featureFlags|src/lib/scoreTier|src/lib/scheduleUtils|src/lib/tutorColors|src/lib/userDisplay|packages/", file_path):
        return "CODE"
    if re.search(r"src/services/|src/hooks/", file_path):
        return "GATEWAY"
    return "UNKNOWN"


def _extract_imports(content: str) -> List[str]:
    """Extract relative import paths from file content."""
    imports = []
    for m in re.finditer(r"""from\s+['"]([^'"]+)['"]""", content, re.MULTILINE):
        path = m.group(1)
        if path.startswith("."):
            imports.append(path)
    return imports


def _resolve_relative(base: Path, relative: str) -> Path | None:
    """Resolve a relative import path against a base file."""
    try:
        target = base.resolve().parent / relative
        # Try with extensions
        for ext in [".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx"]:
            candidate = target.with_suffix("") if ext.startswith("/") else target
            if ext.startswith("/"):
                candidate = Path(str(target) + ext)
            else:
                candidate = target.with_suffix(ext) if not target.suffix else target
            if candidate.exists():
                return candidate
        # Try directory index
        for ext in [".ts", ".tsx"]:
            candidate = target / f"index{ext}"
            if candidate.exists():
                return candidate
        return None
    except Exception:
        return None


def build_graph(project_dir: Path) -> Tuple[Dict[str, str], Dict[str, List[str]], Dict[str, List[str]]]:
    """
    Build node graph from project tree.

    Returns: (classifications, dependencies_by_role, reverse_deps)
    """
    classifications: Dict[str, str] = {}
    deps: Dict[str, List[str]] = defaultdict(list)
    rev_deps: Dict[str, List[str]] = defaultdict(list)

    src_dir = project_dir / "src"
    if not src_dir.exists():
        src_dir = project_dir

    files = list(src_dir.rglob("*.ts")) + list(src_dir.rglob("*.tsx")) + \
            list(src_dir.rglob("*.js")) + list(src_dir.rglob("*.jsx"))
    # Filter out tests, node_modules, build artifacts
    files = [f for f in files if "__tests__" not in str(f)
             and "node_modules" not in str(f)
             and f.name != "setup.ts"]

    for file in files:
        rel = str(file.relative_to(project_dir))
        role = _classify_path(rel)
        classifications[rel] = role

        try:
            content = file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        imports = _extract_imports(content)
        for imp in imports:
            resolved = _resolve_relative(file, imp)
            if resolved:
                try:
                    dep_rel = str(resolved.relative_to(project_dir))
                    deps[rel].append(dep_rel)
                    rev_deps[dep_rel].append(rel)
                except ValueError:
                    pass  # Outside project

    return classifications, dict(deps), dict(rev_deps)


def build_topology(classifications: Dict[str, str], deps: Dict[str, List[str]]) -> str:
    """Build ASCII topology diagram from graph data."""
    lines = []
    lines.append("```")
    lines.append("NODE TOPOLOGY (generated)")
    lines.append("")

    # Collect nodes by role
    triggers = sorted([f for f, r in classifications.items() if r == "TRIGGER"])
    gateways = sorted([f for f, r in classifications.items() if r == "GATEWAY"])
    codes = sorted([f for f, r in classifications.items() if r == "CODE"])

    # Draw TRIGGER → GATEWAY → CODE flow
    if triggers:
        lines.append("  TRIGGER NODES (entry points)")
        lines.append("  ─────────────────────────")
        for t in triggers[:10]:  # Limit to 10
            short = _short_name(t)
            lines.append(f"  [{short}]")
            # Show next hop
            deps_from = deps.get(t, [])
            targets = [d for d in deps_from if d in classifications]
            if targets:
                target_roles = [classifications.get(t, "?") for t in targets[:3]]
                lines.append(f"       ↓  → {', '.join(target_roles[:3])}")
        lines.append("")

    if gateways:
        lines.append("  GATEWAY NODES (routing / merging / branching)")
        lines.append("  ────────────────────────────────────────────")
        # Group gateways by layer
        services = [g for g in gateways if "services/" in g]
        hooks = [g for g in gateways if "hooks/" in g and g not in services]
        for group, label in [(services, "services"), (hooks, "hooks")]:
            if group:
                lines.append(f"    [{label}]")
                for g in group[:8]:
                    short = _short_name(g)
                    deps_from = deps.get(g, [])
                    targets = [d for d in deps_from if d in classifications]
                    target_roles = set(classifications.get(t, "?") for t in targets)
                    lines.append(f"      {short} → {', '.join(sorted(target_roles))}")
        lines.append("")

    if codes:
        lines.append("  CODE NODES (pure IO / computation)")
        lines.append("  ──────────────────────────────────")
        # Group by layer
        for layer, label in [("lib/dal", "DAL"), ("lib/utils", "utils"),
                              ("lib/llm", "LLM"), ("lib/pdf", "PDF"),
                              ("lib/report-card", "RPT"), ("lib/auth", "auth"),
                              ("packages/", "pkg")]:
            layer_nodes = [c for c in codes if layer in c]
            if layer_nodes:
                lines.append(f"    [{label}] {len(layer_nodes)} nodes")

        # Code nodes that have incoming edges (are consumed)
        lines.append("")
        lines.append("  DATA FLOW (depends-on arrows)")
        lines.append("  ─────────────────────────────")
        for g in gateways[:15]:
            short_g = _short_name(g)
            deps_from = deps.get(g, [])
            code_deps = [d for d in deps_from if classifications.get(d) == "CODE"]
            if code_deps:
                short_targets = [_short_name(d) for d in code_deps[:5]]
                lines.append(f"  {short_g}  →  {', '.join(short_targets)}")

    lines.append("")
    lines.append("```")
    return "\n".join(lines)


def build_inventory_table(classifications: Dict[str, str], deps: Dict[str, List[str]]) -> str:
    """Build markdown inventory table."""
    lines = []
    lines.append("| File | Role | Depends On |")
    lines.append("|------|------|-----------|")

    for file in sorted(classifications.keys()):
        role = classifications[file]
        deps_from = deps.get(file, [])
        internal_deps = [d for d in deps_from if d in classifications]
        # Shorten paths
        dep_str = ", ".join(_short_name(d) for d in internal_deps[:5])
        if len(internal_deps) > 5:
            dep_str += " ..."
        lines.append(f"| `{_short_name(file)}` | {role} | {dep_str} |")

    return "\n".join(lines)


def _short_name(path: str) -> str:
    """Shorten a path for display."""
    # Remove common prefixes
    for prefix in ["src/", "packages/"]:
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    # Remove extension
    path = re.sub(r"\.(ts|tsx|js|jsx)$", "", path)
    return path


def main():
    parser = argparse.ArgumentParser(description="Generate node topology map for a project")
    parser.add_argument("--project-dir", "-d", default=".", help="Project root directory")
    parser.add_argument("--output", "-o", help="Output markdown file (default: stdout)")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    if not project_dir.exists():
        print(f"Directory not found: {project_dir}", file=sys.stderr)
        sys.exit(1)

    classifications, deps, rev_deps = build_graph(project_dir)

    # Build output
    output_lines = []
    output_lines.append(f"# Node Topology: {project_dir.name}")
    output_lines.append(f"> Auto-generated by generate_node_map.py")
    output_lines.append("")

    # Summary stats
    roles = list(classifications.values())
    output_lines.append("## Summary")
    output_lines.append(f"- **TRIGGER:** {roles.count('TRIGGER')} nodes")
    output_lines.append(f"- **GATEWAY:** {roles.count('GATEWAY')} nodes")
    output_lines.append(f"- **CODE:** {roles.count('CODE')} nodes")
    output_lines.append(f"- **UNKNOWN:** {roles.count('UNKNOWN')} nodes")
    output_lines.append(f"- **Total:** {len(classifications)} nodes")
    output_lines.append("")

    # Topology diagram
    output_lines.append("## Topology")
    output_lines.append(build_topology(classifications, deps))
    output_lines.append("")

    # Inventory
    output_lines.append("## Inventory")
    output_lines.append(build_inventory_table(classifications, deps))
    output_lines.append("")

    # Violations section
    output_lines.append("## Detected Violations")
    output_lines.append("> Run `scan_node_violations.py` for a full violation report.")
    output_lines.append("")

    output = "\n".join(output_lines)

    if args.output:
        Path(args.output).write_text(output)
        print(f"Written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
