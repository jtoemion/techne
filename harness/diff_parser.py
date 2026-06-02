"""
diff_parser.py — structural parser for unified diffs.

Layer 2 of the intent reasoning system.
Extracts FACTS from a diff — not keywords, not pattern matches,
but concrete structural information: what exports were added,
what functions changed, what component names appeared, what the
dominant change type is.

This output feeds the semantic reasoning layer (intent_reasoner.py).
The small LLM gets structured facts, not diff noise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class FileSummary:
    path: str
    is_new: bool = False          # new file (--- /dev/null)
    is_deleted: bool = False      # deleted file (+++ /dev/null)
    lines_added: int = 0
    lines_removed: int = 0
    exports_added: list[str] = field(default_factory=list)
    exports_removed: list[str] = field(default_factory=list)
    functions_added: list[str] = field(default_factory=list)
    functions_removed: list[str] = field(default_factory=list)
    imports_added: list[str] = field(default_factory=list)
    types_added: list[str] = field(default_factory=list)
    jsx_components: list[str] = field(default_factory=list)
    file_type: str = "unknown"    # component | page | api | middleware | util | config | test | style

    def to_summary_str(self) -> str:
        parts = [f"  {self.path}"]
        if self.is_new:
            parts[0] += " (NEW FILE)"
        if self.is_deleted:
            parts[0] += " (DELETED)"
        parts[0] += f" [+{self.lines_added}/-{self.lines_removed}]"

        if self.exports_added:
            parts.append(f"    exports added:    {', '.join(self.exports_added[:6])}")
        if self.exports_removed:
            parts.append(f"    exports removed:  {', '.join(self.exports_removed[:4])}")
        if self.functions_added:
            parts.append(f"    functions added:  {', '.join(self.functions_added[:6])}")
        if self.functions_removed:
            parts.append(f"    functions removed:{', '.join(self.functions_removed[:4])}")
        if self.imports_added:
            parts.append(f"    imports added:    {', '.join(self.imports_added[:4])}")
        if self.types_added:
            parts.append(f"    types added:      {', '.join(self.types_added[:4])}")
        if self.jsx_components:
            parts.append(f"    JSX components:   {', '.join(self.jsx_components[:6])}")

        return "\n".join(parts)


@dataclass
class DiffSummary:
    """Structured facts extracted from a unified diff."""
    files: list[FileSummary] = field(default_factory=list)
    total_added: int = 0
    total_removed: int = 0
    dominant_type: str = "unknown"  # inferred from file types
    all_exports_added: list[str] = field(default_factory=list)
    all_imports_added: list[str] = field(default_factory=list)
    all_functions_added: list[str] = field(default_factory=list)
    is_empty: bool = True

    def to_structured_text(self) -> str:
        """
        Produce a compact, structured summary for the reasoning LLM.
        Small context, high information density.
        """
        if self.is_empty:
            return "Diff: empty — no changes detected"

        lines = [
            f"Files changed ({len(self.files)}):",
        ]
        for f in self.files:
            lines.append(f.to_summary_str())

        lines.append(f"\nDominant change type: {self.dominant_type}")
        lines.append(f"Total: +{self.total_added} lines added, -{self.total_removed} removed")

        if self.all_exports_added:
            lines.append(f"All exports added: {', '.join(self.all_exports_added[:8])}")
        if self.all_functions_added:
            lines.append(f"All functions added: {', '.join(self.all_functions_added[:8])}")
        if self.all_imports_added:
            lines.append(f"All imports added: {', '.join(self.all_imports_added[:6])}")

        return "\n".join(lines)


# ─── Extraction patterns ─────────────────────────────────────────────────────

_EXPORT_DEFAULT  = re.compile(r"^export\s+default\s+(?:function|class|async\s+function)\s+(\w+)")
_EXPORT_NAMED    = re.compile(r"^export\s+(?:async\s+)?(?:function|class|const|let|var)\s+(\w+)")
_EXPORT_BRACE    = re.compile(r"^export\s*\{([^}]+)\}")
_FUNCTION        = re.compile(r"^(?:async\s+)?function\s+(\w+)")
_CONST_FUNC      = re.compile(r"^const\s+(\w+)\s*=\s*(?:async\s+)?\(")
_ARROW_FUNC      = re.compile(r"^(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?\(?\s*\w*\s*\)?\s*=>")
_IMPORT_FROM     = re.compile(r"^import\s+.*?from\s+['\"]([^'\"]+)['\"]")
_IMPORT_BRACE    = re.compile(r"^import\s+\{([^}]+)\}")
_TYPE_DEF        = re.compile(r"^(?:export\s+)?(?:interface|type)\s+(\w+)")
_JSX_COMPONENT   = re.compile(r"<([A-Z]\w+)[\s/>]")


def _infer_file_type(path: str) -> str:
    p = path.lower()
    # normalise — ensure leading slash for consistent matching
    pp = "/" + p.lstrip("/")

    if "middleware" in p:                                return "middleware"
    if p.endswith(".test.ts") or p.endswith(".spec.ts") or "__tests__" in p:
        return "test"
    if "/api/" in pp or p.startswith("api/"):            return "api"
    if ("/app/" in pp or p.startswith("app/")) and "page.tsx" in p:
        return "page"
    if ("/app/" in pp or p.startswith("app/")) and "layout.tsx" in p:
        return "layout"
    if "/components/" in pp or p.startswith("components/"):
        return "component"
    if "/lib/" in pp or p.startswith("lib/") or "/utils/" in pp or p.startswith("utils/"):
        return "util"
    if p.endswith(".css") or p.endswith(".scss"):        return "style"
    if "config" in p or p.endswith(".json") or p.endswith(".yaml"): return "config"
    if "/hooks/" in pp or p.startswith("hooks/"):        return "hook"
    if "/types/" in pp or p.startswith("types/") or "types.ts" in p: return "types"
    return "unknown"


def _infer_dominant_type(files: list[FileSummary]) -> str:
    if not files:
        return "unknown"
    type_counts: dict[str, int] = {}
    for f in files:
        type_counts[f.file_type] = type_counts.get(f.file_type, 0) + 1
    # Special combos
    types = set(type_counts.keys())
    if "component" in types and "page" in types:
        return "component + page integration"
    if "middleware" in types:
        return "middleware"
    return max(type_counts, key=type_counts.get)


def _extract_from_line(line: str, file_summary: FileSummary, prefix: str) -> None:
    """Extract structural information from a single added or removed diff line."""
    strip = line.strip()
    if not strip:
        return

    exports = file_summary.exports_added if prefix == "+" else file_summary.exports_removed
    functions = file_summary.functions_added if prefix == "+" else file_summary.functions_removed

    # Export default
    m = _EXPORT_DEFAULT.match(strip)
    if m:
        exports.append(m.group(1))
        functions.append(m.group(1))
        return

    # Named export
    m = _EXPORT_NAMED.match(strip)
    if m:
        exports.append(m.group(1))
        return

    # Brace export: export { Foo, Bar }
    m = _EXPORT_BRACE.match(strip)
    if m:
        names = [n.strip().split(" as ")[0].strip() for n in m.group(1).split(",")]
        exports.extend([n for n in names if n])
        return

    # Plain function
    m = _FUNCTION.match(strip)
    if m and prefix == "+":
        functions.append(m.group(1))
        return

    # Arrow function
    m = _ARROW_FUNC.match(strip)
    if m and prefix == "+":
        functions.append(m.group(1))
        return

    # Type / interface
    m = _TYPE_DEF.match(strip)
    if m and prefix == "+":
        file_summary.types_added.append(m.group(1))
        return

    # Imports
    if prefix == "+" and strip.startswith("import"):
        m = _IMPORT_FROM.match(strip)
        if m:
            file_summary.imports_added.append(m.group(1))

    # JSX components (only from added lines)
    if prefix == "+" and "<" in strip:
        components = _JSX_COMPONENT.findall(strip)
        file_summary.jsx_components.extend(components)


# ─── Main parser ─────────────────────────────────────────────────────────────

def parse_diff(diff: str) -> DiffSummary:
    """
    Parse a unified diff into a structured DiffSummary.

    Works on any unified diff format (git diff, diff -u).
    Language: TypeScript / JavaScript / TSX / JSX focused.
    """
    if not diff or not diff.strip():
        return DiffSummary(is_empty=True)

    summary = DiffSummary(is_empty=False)
    current_file: FileSummary | None = None

    lines = diff.splitlines()
    i = 0
    _pending_new_file = False  # "new file mode" seen before +++ b/

    while i < len(lines):
        line = lines[i]

        # git diff header: new file mode comes before +++ b/
        if line.startswith("new file mode"):
            _pending_new_file = True

        elif line.startswith("deleted file mode"):
            if current_file:
                current_file.is_deleted = True

        # New file in diff
        elif line.startswith("+++ b/"):
            path = line[6:].strip()
            if path and path != "/dev/null":
                current_file = FileSummary(
                    path=path,
                    file_type=_infer_file_type(path),
                    is_new=_pending_new_file,
                )
                summary.files.append(current_file)
                _pending_new_file = False

        elif line.startswith("+++ /dev/null"):
            if current_file:
                current_file.is_deleted = True

        elif line.startswith("--- /dev/null") and current_file:
            current_file.is_new = True

        elif current_file is not None:
            if line.startswith("+") and not line.startswith("+++"):
                current_file.lines_added += 1
                _extract_from_line(line[1:], current_file, "+")

            elif line.startswith("-") and not line.startswith("---"):
                current_file.lines_removed += 1
                _extract_from_line(line[1:], current_file, "-")

        i += 1

    # Aggregate
    for f in summary.files:
        summary.total_added += f.lines_added
        summary.total_removed += f.lines_removed
        summary.all_exports_added.extend(f.exports_added)
        summary.all_imports_added.extend(f.imports_added)
        summary.all_functions_added.extend(f.functions_added)
        # Deduplicate JSX components
        f.jsx_components = list(dict.fromkeys(f.jsx_components))

    summary.all_exports_added = list(dict.fromkeys(summary.all_exports_added))
    summary.all_imports_added = list(dict.fromkeys(summary.all_imports_added))
    summary.all_functions_added = list(dict.fromkeys(summary.all_functions_added))
    summary.dominant_type = _infer_dominant_type(summary.files)

    return summary
