"""
gate_registry.py — extensible gate registry for Techne.

Replaces the hardcoded ALL_GATES list. Gates are registered with a name,
a callable, and optional metadata (stack, category, severity). The registry
supports:
  - Dynamic registration via register()
  - Discovery from harness/plugins/ directory
  - Enable/disable by name
  - Stack-based filtering (run only nextjs gates, only general gates, etc.)
  - Pre/post hooks around gate execution
"""
from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

HARNESS_DIR = Path(__file__).parent
PLUGINS_DIR = HARNESS_DIR / "plugins"


@dataclass
class GateMeta:
    """Metadata for a registered gate."""
    name: str                          # e.g. "nextjs/redirect"
    fn: Callable[[str], None]          # gate function: diff -> None | raise GateViolation
    stack: str = "general"             # "nextjs" | "typescript" | "general" | custom
    category: str = "hard"             # "hard" (raise) | "soft" (warn only)
    severity: str = "error"            # "error" | "warning" | "info"
    enabled: bool = True
    description: str = ""
    source: str = "builtin"            # "builtin" | "plugin" | "host"


class GateRegistry:
    """
    Central registry for all gates.

    Usage:
        registry = GateRegistry()
        registry.register("nextjs/redirect", gate_fn, stack="nextjs")
        registry.run_all(diff)  # runs all enabled gates
    """

    def __init__(self):
        self._gates: dict[str, GateMeta] = {}
        self._pre_hooks: list[Callable[[str, GateMeta], None]] = []
        self._post_hooks: list[Callable[[str, GateMeta, Exception | None], None]] = []
        self._active_stacks: list[str] | None = None
        self._disabled_names: list[str] = []

    # ── Registration ──────────────────────────────────────────────────────

    def register(
        self,
        name: str,
        fn: Callable[[str], None],
        *,
        stack: str = "general",
        category: str = "hard",
        severity: str = "error",
        enabled: bool = True,
        description: str = "",
        source: str = "builtin",
    ) -> None:
        """Register a gate. Overwrites if name already exists."""
        self._gates[name] = GateMeta(
            name=name, fn=fn, stack=stack, category=category,
            severity=severity, enabled=enabled, description=description,
            source=source,
        )
        # Apply any deferred config (stacks/disable) that was loaded before this gate
        if self._active_stacks is not None and stack not in self._active_stacks:
            self._gates[name].enabled = False
        if name in self._disabled_names:
            self._gates[name].enabled = False

    def unregister(self, name: str) -> bool:
        """Remove a gate by name. Returns True if it existed."""
        return self._gates.pop(name, None) is not None

    def enable(self, name: str) -> None:
        if name in self._gates:
            self._gates[name].enabled = True

    def disable(self, name: str) -> None:
        if name in self._gates:
            self._gates[name].enabled = False

    def get(self, name: str) -> GateMeta | None:
        return self._gates.get(name)

    def list_gates(self, *, stack: str | None = None, enabled_only: bool = True) -> list[GateMeta]:
        """List registered gates, optionally filtered by stack."""
        gates = list(self._gates.values())
        if enabled_only:
            gates = [g for g in gates if g.enabled]
        if stack is not None:
            gates = [g for g in gates if g.stack == stack]
        return gates

    # ── Hooks ─────────────────────────────────────────────────────────────

    def add_pre_hook(self, hook: Callable[[str, GateMeta], None]) -> None:
        """Hook called before each gate runs. Receives (diff, gate_meta)."""
        self._pre_hooks.append(hook)

    def add_post_hook(self, hook: Callable[[str, GateMeta, Exception | None], None]) -> None:
        """Hook called after each gate runs. Receives (diff, gate_meta, exception_or_None)."""
        self._post_hooks.append(hook)

    # ── Execution ─────────────────────────────────────────────────────────

    def run_all(
        self,
        diff: str,
        *,
        stacks: list[str] | None = None,
    ) -> bool:
        """
        Run all enabled gates against diff.

        Args:
            diff: unified diff string
            stacks: if set, only run gates matching these stacks.
                     None = run all enabled gates.

        Returns:
            True if all pass.

        Raises:
            GateViolation on first hard-gate failure.
        """
        # Import here to avoid circular dependency
        from gates import GateViolation

        for meta in list(self._gates.values()):
            if not meta.enabled:
                continue
            if stacks is not None and meta.stack not in stacks:
                continue

            # Pre-hooks
            for hook in self._pre_hooks:
                hook(diff, meta)

            exc = None
            try:
                meta.fn(diff)
            except GateViolation as e:
                exc = e
                if meta.category == "hard":
                    for hook in self._post_hooks:
                        hook(diff, meta, exc)
                    raise
            except Exception as e:
                exc = e
                if meta.category == "hard":
                    for hook in self._post_hooks:
                        hook(diff, meta, exc)
                    raise

            # Post-hooks (success or soft-gate violation)
            for hook in self._post_hooks:
                hook(diff, meta, exc)

        return True

    # ── Config loading ────────────────────────────────────────────────────

    def load_config(self, config_path: Path | None = None) -> None:
        """
        Load gate-config.yaml and apply stack/disable filters.

        Uses PyYAML if available, otherwise a minimal stdlib parser.
        If file doesn't exist, all stacks are active (default behavior).
        """
        p = config_path or HARNESS_DIR / "gate-config.yaml"
        if not p.exists():
            return

        try:
            config = _load_yaml(p)
        except Exception:
            return

        if not isinstance(config, dict):
            return

        active_stacks = config.get("active_stacks")
        if active_stacks is not None:
            self._active_stacks = active_stacks
            for meta in self._gates.values():
                if meta.stack not in active_stacks:
                    meta.enabled = False

        disabled = config.get("disabled_gates", [])
        if isinstance(disabled, list):
            self._disabled_names.extend(disabled)
            for name in disabled:
                self.disable(name)

    # ── Plugin discovery ──────────────────────────────────────────────────

    def discover_plugins(self, plugins_dir: Path | None = None) -> int:
        """
        Scan plugins/ for Python files that define gates.

        Each plugin file should define a `register(registry: GateRegistry)` function.
        Returns count of gates registered.
        """
        d = plugins_dir or PLUGINS_DIR
        if not d.exists():
            return 0

        count_before = len(self._gates)
        for py_file in sorted(d.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            spec = importlib.util.spec_from_file_location(
                f"techne.plugins.{py_file.stem}", py_file
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                try:
                    spec.loader.exec_module(mod)
                except Exception:
                    continue  # skip broken plugins silently
                if hasattr(mod, "register") and callable(mod.register):
                    mod.register(self)

        return len(self._gates) - count_before


# ─── YAML loading (stdlib fallback) ────────────────────────────────────────

def _load_yaml(path: Path) -> dict:
    """Load a YAML file. Tries PyYAML first, falls back to minimal parser."""
    text = path.read_text(encoding="utf-8")
    try:
        import yaml
        return yaml.safe_load(text) or {}
    except ImportError:
        return _parse_yaml_simple(text)


def _parse_yaml_simple(text: str) -> dict:
    """
    Minimal YAML parser for gate-config.yaml (stdlib only).
    Handles flat keys, lists of strings, and comments. Enough for our config.
    """
    result: dict = {}
    current_key: str | None = None
    for line in text.splitlines():
        stripped = line.split("#")[0].rstrip()  # strip comments
        if not stripped:
            continue
        if ":" in stripped and not stripped.startswith("- "):
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if val:
                if val.startswith("[") and val.endswith("]"):
                    result[key] = [
                        v.strip().strip('"').strip("'")
                        for v in val[1:-1].split(",") if v.strip()
                    ]
                else:
                    result[key] = val.strip('"').strip("'")
            else:
                current_key = key
                result[current_key] = []
        elif stripped.lstrip().startswith("- ") and current_key:
            result[current_key].append(stripped.lstrip()[2:].strip().strip('"').strip("'"))
    return result
