# Gate Plugin System + Four Hardening Fixes

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make gates stack-agnostic and extensible via a plugin registry, close the four flagged architecture gaps, and let hosts inject gates without touching core files.

**Architecture:** A `GateRegistry` replaces the hardcoded `ALL_GATES` list. Gates are registered from three sources (in priority order): (1) built-in gates, (2) plugins discovered from `harness/plugins/`, (3) host-injected gates via `register_gate()` API. A YAML config (`harness/gate-config.yaml`) declares which gate sets are active per stack. The conductor's retro loop is closed by auto-applying proposals after the retro phase.

**Tech Stack:** Python 3.10+, stdlib only (PyYAML optional). No new dependencies.

---

## Task 1: Create the Gate Registry

**Objective:** Replace the hardcoded `ALL_GATES` list with a registry that supports dynamic gate registration, naming, ordering, and enable/disable.

**Files:**
- Create: `harness/gate_registry.py`
- Test: `tests/test_gate_registry.py`

**Step 1: Write the GateRegistry class**

```python
# harness/gate_registry.py
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
        from gates import GateViolation  # circular-safe: gates.py imports nothing from us

        for meta in self._gates.values():
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
                    # Post-hooks see the exception, then we re-raise
                    for hook in self._post_hooks:
                        hook(diff, meta, exc)
                    raise
            except Exception as e:
                exc = e
                # Non-gate exceptions are logged but don't halt unless it's a hard gate
                if meta.category == "hard":
                    for hook in self._post_hooks:
                        hook(diff, meta, exc)
                    raise

            # Post-hooks (success or soft-gate violation)
            for hook in self._post_hooks:
                hook(diff, meta, exc)

        return True

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
            spec = importlib.util.spec_from_file_location(f"techne.plugins.{py_file.stem}", py_file)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                try:
                    spec.loader.exec_module(mod)
                except Exception:
                    continue  # skip broken plugins silently
                if hasattr(mod, "register") and callable(mod.register):
                    mod.register(self)

        return len(self._gates) - count_before
```

**Step 2: Write tests**

```python
# tests/test_gate_registry.py
"""Tests for the gate registry system."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'harness'))

from gate_registry import GateRegistry, GateMeta
from gates import GateViolation


def test_register_and_run():
    """Registered gate runs when run_all() is called."""
    r = GateRegistry()
    calls = []
    def my_gate(diff):
        calls.append(diff)
    r.register("test/call-tracker", my_gate, stack="test")
    r.run_all("some diff")
    assert calls == ["some diff"], f"Gate should have been called, got {calls}"


def test_disable_skips_gate():
    """Disabled gates are skipped."""
    r = GateRegistry()
    calls = []
    r.register("test/disabled", lambda d: calls.append(1), enabled=False)
    r.run_all("diff")
    assert calls == [], "Disabled gate should not run"


def test_stack_filter():
    """stacks= param filters which gates run."""
    r = GateRegistry()
    ran = []
    r.register("a", lambda d: ran.append("a"), stack="nextjs")
    r.register("b", lambda d: ran.append("b"), stack="general")
    r.run_all("diff", stacks=["general"])
    assert ran == ["b"], f"Only general stack should run, got {ran}"


def test_hard_gate_raises():
    """Hard gate raises GateViolation, halting the run."""
    r = GateRegistry()
    def bad_gate(diff):
        raise GateViolation("test violation")
    r.register("test/fail", bad_gate, category="hard")
    try:
        r.run_all("diff")
        assert False, "Should have raised"
    except GateViolation as e:
        assert "test violation" in str(e)


def test_soft_gate_does_not_raise():
    """Soft gate catches violation but does not halt."""
    r = GateRegistry()
    ran = []
    def soft_fail(diff):
        raise GateViolation("soft")
    def second(diff):
        ran.append("second")
    r.register("test/soft", soft_fail, category="soft")
    r.register("test/after", second)
    r.run_all("diff")
    assert ran == ["second"], "Soft gate should not halt execution"


def test_pre_post_hooks():
    """Pre and post hooks fire around each gate."""
    r = GateRegistry()
    events = []
    def pre(diff, meta):
        events.append(f"pre:{meta.name}")
    def post(diff, meta, exc):
        events.append(f"post:{meta.name}:{'ok' if exc is None else 'fail'}")
    r.add_pre_hook(pre)
    r.add_post_hook(post)
    r.register("test/g1", lambda d: None)
    r.run_all("diff")
    assert events == ["pre:test/g1", "post:test/g1:ok"], f"Hook events: {events}"


def test_post_hook_sees_exception():
    """Post hook receives the exception from a failing hard gate."""
    r = GateRegistry()
    seen_exc = []
    def post(diff, meta, exc):
        seen_exc.append(exc)
    r.add_post_hook(post)
    def fail(diff):
        raise GateViolation("boom")
    r.register("test/fail", fail, category="hard")
    try:
        r.run_all("diff")
    except GateViolation:
        pass
    assert len(seen_exc) == 1
    assert isinstance(seen_exc[0], GateViolation)


def test_unregister():
    """Unregister removes the gate."""
    r = GateRegistry()
    r.register("test/tmp", lambda d: None)
    assert r.get("test/tmp") is not None
    r.unregister("test/tmp")
    assert r.get("test/tmp") is None


def test_list_gates():
    """list_gates returns correct filters."""
    r = GateRegistry()
    r.register("a", lambda d: None, stack="nextjs")
    r.register("b", lambda d: None, stack="general", enabled=False)
    r.register("c", lambda d: None, stack="general")
    assert len(r.list_gates()) == 2  # excludes disabled
    assert len(r.list_gates(stack="general")) == 1
    assert len(r.list_gates(enabled_only=False)) == 3


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("All tests passed.")
```

**Step 3: Run tests**

Run: `cd /c/Users/jtoem/Repo/techne && python -X utf8 tests/test_gate_registry.py`
Expected: All tests passed.

**Step 4: Commit**

```bash
git add harness/gate_registry.py tests/test_gate_registry.py
git commit -m "feat: add GateRegistry — extensible gate system with hooks"
```

---

## Task 2: Create Plugin Directory + Migrate Built-in Gates

**Objective:** Move the five hardcoded gates into `harness/plugins/builtin_gates.py` as a plugin, and create `harness/plugins/__init__.py`.

**Files:**
- Create: `harness/plugins/__init__.py`
- Create: `harness/plugins/builtin_gates.py`
- Modify: `harness/gates.py` (keep `GateViolation`, `_strip_diff_marker`, `_is_comment` as shared utilities; remove gate functions and `ALL_GATES`)

**Step 1: Create plugins directory**

Create `harness/plugins/__init__.py`:
```python
# Techne gate plugins directory.
# Each .py file should define register(registry: GateRegistry) and register its gates.
```

**Step 2: Create builtin_gates.py plugin**

```python
# harness/plugins/builtin_gates.py
"""
Built-in gates: the original five Techne gates (Next.js + TypeScript + general).

These were previously hardcoded in gates.py. As a plugin, they are registered
with the same names and behavior, but can now be individually disabled or
replaced by other plugins.

To disable the Next.js gates for a non-Next.js project, either:
  - Set gate-config.yaml stacks: ["general", "typescript"]
  - Or: registry.disable("nextjs/redirect") etc.
"""
import re
from gates import GateViolation, _strip_diff_marker, _is_comment


def _gate_no_redirect_outside_middleware(diff: str):
    """Rule: redirect() only allowed in middleware.ts"""
    current_file = ""
    for i, line in enumerate(diff.splitlines()):
        if line.startswith("+++ b/") or line.startswith("+++ a/"):
            current_file = line[6:].strip()
            continue
        if line.startswith(("--- ", "+++", "diff ", "@@")):
            continue
        code = _strip_diff_marker(line)
        if _is_comment(code):
            continue
        if "redirect(" not in code:
            continue
        if "middleware.ts" not in current_file:
            raise GateViolation(
                f"GATE FAIL [nextjs/redirect]: redirect() on diff line {i+1} "
                f"is outside middleware.ts (current file: '{current_file or 'unknown'}')\n"
                f"  → {line.strip()}"
            )


def _gate_no_router_import(diff: str):
    """Rule: import from next/navigation, never next/router"""
    for i, line in enumerate(diff.splitlines()):
        code = _strip_diff_marker(line)
        if _is_comment(code):
            continue
        if re.search(r"from\s+['\"]next/router['\"]", code):
            raise GateViolation(
                f"GATE FAIL [nextjs/router-import]: found 'next/router' import on line {i+1}. "
                f"Use 'next/navigation' in App Router.\n"
                f"  → {line.strip()}"
            )


def _gate_no_gSSP(diff: str):
    """Rule: getServerSideProps removed in App Router"""
    for i, line in enumerate(diff.splitlines()):
        if line.startswith(("+++", "---", "@@", "diff ")):
            continue
        code = _strip_diff_marker(line)
        if _is_comment(code):
            continue
        if "getServerSideProps" in code:
            raise GateViolation(
                f"GATE FAIL [nextjs/gSSP]: getServerSideProps on line {i+1}. "
                f"Use async server components instead.\n"
                f"  → {line.strip()}"
            )


def _gate_no_ts_ignore(diff: str):
    """Rule: no @ts-ignore or @ts-nocheck suppressions"""
    for i, line in enumerate(diff.splitlines()):
        if re.search(r"@ts-(ignore|nocheck)", line):
            raise GateViolation(
                f"GATE FAIL [ts/suppress]: @ts-ignore or @ts-nocheck on line {i+1}. "
                f"Fix the type error instead.\n"
                f"  → {line.strip()}"
            )


def _gate_no_console_log(diff: str):
    """Rule: no console.log in production code paths"""
    for i, line in enumerate(diff.splitlines()):
        if not line.startswith("+") or line.startswith("+++"):
            continue
        code = _strip_diff_marker(line)
        if _is_comment(code):
            continue
        if "console.log" in code:
            raise GateViolation(
                f"GATE FAIL [general/console-log]: console.log added on line {i+1}. "
                f"Remove before merge.\n"
                f"  → {line.strip()}"
            )


def register(registry):
    """Register the five built-in gates."""
    registry.register("nextjs/redirect", _gate_no_redirect_outside_middleware,
                      stack="nextjs", description="redirect() only in middleware.ts")
    registry.register("nextjs/router-import", _gate_no_router_import,
                      stack="nextjs", description="use next/navigation, not next/router")
    registry.register("nextjs/gSSP", _gate_no_gSSP,
                      stack="nextjs", description="no getServerSideProps in App Router")
    registry.register("ts/suppress", _gate_no_ts_ignore,
                      stack="typescript", description="no @ts-ignore or @ts-nocheck")
    registry.register("general/console-log", _gate_no_console_log,
                      stack="general", description="no console.log in production")
```

**Step 3: Simplify gates.py**

Strip `gates.py` down to shared utilities + `GateViolation`:

```python
# harness/gates.py (revised — keep only shared utilities)
"""
gates.py — shared gate utilities and the GateViolation exception.

Gate functions live in plugins/builtin_gates.py and user-created plugins.
This module provides the building blocks they all use.
"""
import re


class GateViolation(Exception):
    pass


def _strip_diff_marker(line: str) -> str:
    """Remove a leading +/- diff marker and surrounding whitespace."""
    if line[:1] in ("+", "-"):
        line = line[1:]
    return line.strip()


def _is_comment(code: str) -> bool:
    """True if a stripped code line is a JS/TS or shell comment."""
    return code.startswith(("//", "#", "/*", "*"))


# ─── Legacy shim — keeps old callers working during migration ──────────────

def run_all_gates(diff: str) -> bool:
    """
    Legacy shim. Prefer GateRegistry.run_all() for new code.

    Creates a default registry, discovers plugins, and runs all gates.
    The conductor.py will be updated to use the registry directly.
    """
    from gate_registry import GateRegistry

    registry = GateRegistry()
    registry.discover_plugins()
    return registry.run_all(diff)
```

**Step 4: Run existing gate tests to verify backward compat**

Run: `cd /c/Users/jtoem/Repo/techne && python -X utf8 tests/test_harness.py`
Expected: All existing gate tests pass (the legacy shim calls through to the same code).

**Step 5: Commit**

```bash
git add harness/plugins/ harness/gates.py
git commit -m "refactor: migrate gates to plugin architecture, gates.py keeps shared utils"
```

---

## Task 3: Create Gate Config (Stack-Based Gate Selection)

**Objective:** Add `harness/gate-config.yaml` so projects declare their stack and the registry only runs matching gates.

**Files:**
- Create: `harness/gate-config.yaml`
- Modify: `harness/gate_registry.py` (add `load_config()` method)

**Step 1: Create gate-config.yaml**

```yaml
# harness/gate-config.yaml
# Declare which stacks are active for this project.
# Gates tagged with a stack not in this list are skipped.
#
# Edit this when adapting Techne to your stack.
# See COMPONENTS.md "Adapting to your stack" for guidance.

version: "1.0"

# Active stacks — gates in these stacks will run
active_stacks:
  - general       # stack-agnostic rules (console.log, etc.)
  - nextjs        # Next.js App Router rules
  - typescript    # TypeScript suppression rules

# To disable Next.js gates for a React/Vite project:
# active_stacks:
#   - general
#   - typescript

# To disable TypeScript gates for a plain JS project:
# active_stacks:
#   - general
#   - nextjs

# Per-gate overrides (optional) — disable specific gates by name
disabled_gates: []
  # - "nextjs/redirect"     # example: allow redirect() anywhere
  # - "general/console-log" # example: allow console.log
```

**Step 2: Add load_config to GateRegistry**

Add this method to `GateRegistry`:

```python
def load_config(self, config_path: Path | None = None) -> None:
    """
    Load gate-config.yaml and apply stack/disable filters.

    If config_path is None, looks for harness/gate-config.yaml.
    If file doesn't exist, all stacks are active (default behavior).
    """
    import yaml  # optional — falls back to no-op if missing

    p = config_path or HARNESS_DIR / "gate-config.yaml"
    if not p.exists():
        return

    try:
        with open(p, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except Exception:
        return

    if not isinstance(config, dict):
        return

    active_stacks = config.get("active_stacks")
    if active_stacks is not None:
        for meta in self._gates.values():
            if meta.stack not in active_stacks:
                meta.enabled = False

    disabled = config.get("disabled_gates", [])
    for name in disabled:
        self.disable(name)
```

And add a stdlib fallback for projects without PyYAML:

```python
def _parse_yaml_simple(text: str) -> dict:
    """
    Minimal YAML parser for gate-config.yaml (stdlib only).
    Handles flat keys, lists of strings, and comments. Enough for our config.
    """
    result = {}
    current_key = None
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
                    result[key] = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",") if v.strip()]
                else:
                    result[key] = val.strip('"').strip("'")
            else:
                current_key = key
                result[current_key] = []
        elif stripped.startswith("- ") and current_key:
            result[current_key].append(stripped[2:].strip().strip('"').strip("'"))
    return result
```

**Step 3: Update the config loading to use stdlib fallback**

Revise `load_config` to try `_parse_yaml_simple` when PyYAML isn't available.

**Step 4: Commit**

```bash
git add harness/gate-config.yaml harness/gate_registry.py
git commit -m "feat: add gate-config.yaml for stack-based gate selection"
```

---

## Task 4: Update Conductor to Use GateRegistry

**Objective:** Replace the direct `run_all_gates()` call in `conductor.py` with the registry, and wire in config loading + plugin discovery.

**Files:**
- Modify: `harness/conductor.py`

**Step 1: Update imports in conductor.py**

Replace:
```python
from gates import GateViolation, run_all_gates
```

With:
```python
from gates import GateViolation
from gate_registry import GateRegistry
```

**Step 2: Initialize registry in Pipeline.__init__**

Add to `Pipeline.__init__`:
```python
self.registry = GateRegistry()
self.registry.discover_plugins()
self.registry.load_config()
```

**Step 3: Replace run_all_gates call in submit_implementation**

Change:
```python
run_all_gates(diff)
```

To:
```python
self.registry.run_all(diff)
```

**Step 4: Add host gate injection API**

Add to `Pipeline`:
```python
def register_host_gate(self, name: str, fn: Callable[[str], None], **kwargs) -> None:
    """
    Let the host inject a gate at pipeline start.
    Example: p.register_host_gate("custom/no-any", my_no_any_gate, stack="typescript")
    """
    self.registry.register(name, fn, source="host", **kwargs)

def add_host_hook(self, hook_type: str, hook_fn: Callable) -> None:
    """
    Let the host add pre/post hooks.
    hook_type: "pre" or "post"
    """
    if hook_type == "pre":
        self.registry.add_pre_hook(hook_fn)
    elif hook_type == "post":
        self.registry.add_post_hook(hook_fn)
```

**Step 5: Commit**

```bash
git add harness/conductor.py
git commit -m "feat: conductor uses GateRegistry with host injection API"
```

---

## Task 5: Namespace Skill Router IDs (Fix #2 — Collision Prevention)

**Objective:** Prefix all skill IDs in `skill-router.yaml` with `techne/` to prevent host collisions.

**Files:**
- Modify: `harness/skill-router.yaml`
- Modify: `harness/router.py` (if it strips prefixes anywhere)
- Modify: `harness/conductor.py` (logging references)

**Step 1: Prefix all routing IDs**

Change every `id:` in the routing table from bare names to `techne/` prefixed:

```yaml
routing:
  - id: "techne/diagnose"
    condition: "bug, broken, throwing, failing, regression, not working, debug, diagnose"
    skill_path: "skills/diagnose.md"
    weight: 90

  - id: "techne/writing-skill"
    condition: "write a skill, create a skill, new skill, skill template, audit skill, refactor skill"
    skill_path: "skills/writing-skill.md"
    weight: 88

  # ... etc for all entries
```

**Step 2: Update disambiguation section to use new IDs**

Update the `confused:` lists to match the new prefixed IDs.

**Step 3: Verify router still resolves correctly**

Run: `cd /c/Users/jtoem/Repo/techne && python -X utf8 tests/test_adopted.py`
Expected: All router tests pass.

**Step 4: Commit**

```bash
git add harness/skill-router.yaml harness/router.py harness/conductor.py
git commit -m "refactor: namespace skill router IDs with techne/ prefix"
```

---

## Task 6: Smart Skill File Loading (Fix #3 — Context Window Efficiency)

**Objective:** Replace the fallback that dumps every skill file with a curated "common context" set.

**Files:**
- Modify: `harness/conductor.py` (`_read_skill_files`)
- Modify: `harness/skill-router.yaml` (add `common_loaded` section)

**Step 1: Add common_loaded section to skill-router.yaml**

```yaml
# COMMON-LOADED — injected when no specific skill matches (replaces full dump)
# Keep this minimal. Each file costs context window.
common_loaded:
  - "skills/implementer.md"     # base implementation discipline
  - "skills/typescript.md"      # type safety gates
```

**Step 2: Update _read_skill_files in conductor.py**

Replace the fallback loop (lines 110-114) with:

```python
# Fallback: common context only (not every skill file)
if task:
    for rel_path in get_common_loaded():
        full = ROOT / rel_path
        if full.exists() and full.name not in loaded:
            parts.append(f"=== {full.name} [common-loaded] ===\n{full.read_text(encoding='utf-8')}")
            loaded.add(full.name)
```

And add `get_common_loaded()` to `router.py`:

```python
def get_common_loaded() -> list[str]:
    """Return the list of common-loaded skill paths (used when no specific skill matches)."""
    config = _load_yaml()
    return config.get("common_loaded", [])
```

**Step 3: Commit**

```bash
git add harness/conductor.py harness/router.py harness/skill-router.yaml
git commit -m "fix: replace full skill dump with curated common_loaded set"
```

---

## Task 7: Close the Retro Loop (Fix #4 — Auto-Apply Proposals)

**Objective:** After the retro phase completes, auto-apply proposals (with a host approval gate).

**Files:**
- Modify: `harness/conductor.py` (add `apply_retro_step()`)
- Modify: `harness/apply_retro.py` (add non-interactive `auto_apply_pending()`)

**Step 1: Add auto_apply_pending to apply_retro.py**

```python
def auto_apply_pending() -> dict:
    """
    Apply all pending proposals without confirmation.
    Returns summary dict. Used by the conductor's retro phase.
    """
    return review_and_apply(auto=True)
```

**Step 2: Add apply_retro_step to Pipeline**

```python
def apply_retro_prompt(self) -> AgentPrompt:
    """
    Prompt for the host to review retro proposals before auto-apply.
    The host can approve (submit_retro_approve) or skip.
    """
    pending = has_pending_proposals()
    user = textwrap.dedent(f"""
        {pending} retro proposal(s) pending in memory/retro_proposals.md.

        Review the proposals. If they look correct, respond with "APPROVE".
        If any should be skipped, respond with "SKIP: <reason>".

        The proposals will be applied automatically after your approval.
    """).strip()
    return AgentPrompt(system=_read_agent_prompt("retro"), user=user)

def submit_retro_approve(self, approval: str = "APPROVE") -> PhaseResult:
    """Apply retro proposals if host approved."""
    if "APPROVE" in approval.upper():
        from apply_retro import auto_apply_pending
        result = auto_apply_pending()
        self.eval_metrics["retro_proposals_applied"] = result.get("applied", 0)
        print(f"[CONDUCTOR] Retro proposals applied: {result}")
        return PhaseResult("PASS", detail={"retro_apply": result})
    else:
        print("[CONDUCTOR] Retro proposals skipped by host")
        return PhaseResult("PASS", detail={"retro_apply": "skipped"})
```

**Step 3: Update the Pipeline flow**

After `submit_retro()`, the conductor can optionally run:
```python
p.apply_retro_prompt()   # host reviews proposals
p.submit_retro_approve()  # auto-applies if approved
```

This is opt-in — existing callers that don't call these methods are unaffected.

**Step 4: Commit**

```bash
git add harness/conductor.py harness/apply_retro.py
git commit -m "feat: close retro loop — host-approved auto-apply of proposals"
```

---

## Task 8: Example Plugin — Security Gate

**Objective:** Create an example plugin to demonstrate how hosts extend the gate system.

**Files:**
- Create: `harness/plugins/security_gates.py`

**Step 1: Write the plugin**

```python
# harness/plugins/security_gates.py
"""
Example plugin: security-focused gates.

Demonstrates how to write a Techne gate plugin.
Drop a .py file in harness/plugins/, define register(registry), done.
"""
from gates import GateViolation, _strip_diff_marker, _is_comment


def _gate_no_hardcoded_secrets(diff: str):
    """Reject diffs that add hardcoded API keys, tokens, or passwords."""
    import re
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
    registry.register("security/hardcoded-secret", _gate_no_hardcoded_secrets,
                      stack="security", category="hard",
                      description="reject hardcoded API keys, tokens, passwords")
    registry.register("security/eval", _gate_no_eval_usage,
                      stack="security", category="hard",
                      description="reject eval() usage")
```

**Step 2: Test it loads**

Run:
```python
cd /c/Users/jtoem/Repo/techne && python -c "
import sys; sys.path.insert(0, 'harness')
from gate_registry import GateRegistry
r = GateRegistry()
n = r.discover_plugins()
print(f'Discovered {n} gates from plugins')
for g in r.list_gates():
    print(f'  {g.name:30} [{g.stack}] {g.source}')
"
```

Expected: Shows all 7 gates (5 builtin + 2 security).

**Step 3: Commit**

```bash
git add harness/plugins/security_gates.py
git commit -m "feat: example security gate plugin (hardcoded secrets, eval)"
```

---

## Task 9: Update COMPONENTS.md + INSTALL.md

**Objective:** Document the new plugin system, gate config, and all four fixes.

**Files:**
- Modify: `COMPONENTS.md`
- Modify: `INSTALL.md`
- Modify: `SKILL.md` (remove the stale `references/hook-gate-bridge.md` link)

**Step 1: Add plugin section to COMPONENTS.md**

Add after the Gates catalog:

```markdown
## Plugin System

Gates are extensible via the plugin architecture:

| Component | Path | Purpose |
|---|---|---|
| `gate_registry.py` | `harness/` | Central registry: register, enable/disable, hooks |
| `gate-config.yaml` | `harness/` | Stack-based gate selection |
| `plugins/` | `harness/plugins/` | Plugin directory — drop .py files here |
| `plugins/builtin_gates.py` | `harness/plugins/` | The original five gates, now as a plugin |
| `plugins/security_gates.py` | `harness/plugins/` | Example: hardcoded secrets, eval detection |

### Writing a gate plugin

1. Create `harness/plugins/my_gates.py`
2. Define `def register(registry):` that calls `registry.register(...)`
3. Done — discovered automatically on `registry.discover_plugins()`

### Host injection (no file needed)

```python
p = Pipeline.start("task")
p.register_host_gate("custom/no-any", my_gate_fn, stack="typescript")
p.add_host_hook("pre", my_pre_hook)   # runs before each gate
p.add_host_hook("post", my_post_hook) # runs after each gate
```
```

**Step 2: Update INSTALL.md**

Update the gate-related sections to mention the plugin system and config file.

**Step 3: Remove stale hook-gate-bridge reference from SKILL.md**

The link to `references/hook-gate-bridge.md` points to a file that doesn't exist. Replace with a reference to the actual plugin system.

**Step 4: Commit**

```bash
git add COMPONENTS.md INSTALL.md SKILL.md
git commit -m "docs: document plugin system, gate config, and host injection API"
```

---

## Task 10: Full Regression

**Objective:** Run all test suites and eval baselines to verify nothing broke.

**Step 1: Run all test suites**

```bash
cd /c/Users/jtoem/Repo/techne
python -X utf8 tests/test_gate_registry.py
python -X utf8 tests/test_harness.py
python -X utf8 tests/test_adopted.py
python -X utf8 tests/test_evaluator.py
python -X utf8 tests/test_conductor.py
python -X utf8 tests/test_synthetic.py
```

**Step 2: Run eval baselines**

```bash
cd /c/Users/jtoem/Repo/techne
python -X utf8 tests/evals/run_evals.py
```

**Step 3: Update baseline if intentional**

```bash
python -X utf8 tests/evals/run_evals.py --save-baseline
```

**Step 4: Commit**

```bash
git add tests/evals/results/
git commit -m "chore: update eval baseline after plugin migration"
```

---

## Summary

| Task | What it fixes | What it adds |
|---|---|---|
| 1 | — | GateRegistry with hooks, enable/disable, stack filtering |
| 2 | #1 Stack lock-in | Plugins directory, builtin gates as a plugin |
| 3 | #1 Stack lock-in | gate-config.yaml for per-project stack selection |
| 4 | — | Conductor wired to registry, host injection API |
| 5 | #2 Skill name collisions | `techne/` namespace prefix on all router IDs |
| 6 | #3 Context window waste | Curated `common_loaded` instead of full dump |
| 7 | #4 Retro loop gap | Host-approved auto-apply of retro proposals |
| 8 | — | Example security plugin (hardcoded secrets, eval) |
| 9 | — | Documentation for all changes |
| 10 | — | Full regression verification |
