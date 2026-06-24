# Techne for Claude Code — VPS Handoff

> **Who this is for:** A fresh Claude Code session on a VPS with no prior context.
> Everything needed to execute without gaps is in this file.
>
> **Written:** 2026-06-25 by Claude Sonnet 4.6 (worktree `vigorous-noyce-522718`)
> **Goal:** Build *Techne for Claude Code v0* — CLI + PreToolUse enforcement hook + doctor

---

## 1. Fast Context — What Techne Is

Techne is a **project-attached engineering harness** with a hard enforcement spine:

- **`./next` loop** — 5 phases: `RECALL → IMPLEMENT → VERIFY → CONCLUDE → DONE`. Every code change goes through every phase. No exceptions.
- **`phase_guard`** — pre-write enforcement that blocks writes violating the active phase. Currently implemented as a **Hermes plugin** (`plugins/techne/` + `harness/plugins/phase_guard.py`). It does nothing in Claude Code.
- **SHA-256 audit chain** — tamper-evident append-only log, one entry per phase.
- **Watchdog** — cron process detecting stalls/tampering/skips/orphans.
- **GRPO engine** — group relative policy optimization; scores pipeline runs, proposes skill edits for human ratification.
- **Context amortization** — deterministic context packs rebuilt from repo state, zero model calls.

Techne never calls a model. Your agent reasons. Techne supplies the deterministic spine.

---

## 2. The Mission

### Core Finding (from a 2-hour scouting session comparing OMO/OMH against Techne)

**Techne is a raw engine. OMO (oh-my-openagent) is a product.**

- Techne's enforcement spine is **categorically stronger** than OMO (hard gate at tool-call layer vs. soft prompt discipline)
- Techne has **no user surface** — every interaction is a hand-assembled filesystem ritual (`echo '{"task_id":...}' > .techne/loop/state.json`, hand-write artifact files, memorize gate-string formats)
- SKILL.md's "Pitfalls" section documents that this ritual has been corrected **4+ times**

### What to Build: Techne for Claude Code, v0

Three pieces, in order:

**Piece 1 — `techne` CLI** (`pip install -e .`)
A real console entry point wrapping existing `scripts/` internals. Deletes the filesystem ritual.

**Piece 2 — `PreToolUse` enforcement hook** (the load-bearing piece)
The existing `phase_guard` is a Hermes `pre_tool_call` plugin — it does nothing in Claude Code. Claude Code has a native equivalent: `PreToolUse` hooks in `.claude/settings.json` that can exit code 2 to **deny a tool call**. This is how enforcement becomes real for Claude Code.

**Piece 3 — `techne doctor` + `.claude/commands/techne.md`**
Human-readable health check + native CC slash command entry point.

---

## 3. Repo State

### Clone and branch
```bash
git clone https://github.com/jtoemion/techne.git
cd techne
git checkout claude/vigorous-noyce-522718
```

### Current HEAD
```
b5356c9  feat: node-discipline skill — full capability bundle with sub-skills, 4 enforcement scripts, and ./next VERIFY gate
```

### Untracked work (commit this first)
```bash
git add ref/
git commit -m "docs: add OMO/OMH/oh-my-models scouting reference + SCOUTING-REPORT"
```

The `ref/` folder contains `SCOUTING-REPORT.md` (the 7-item backlog), plus reference notes on OMO, OMH, and oh-my-models.

---

## 4. Internal APIs — Already Exist, Already Importable

**No new logic needed for pieces 1 and 2. The hard parts already exist.**

### `scripts/next_state.py`
```python
from next_state import (
    LoopState,           # dataclass: task_id, phase, created_at, updated_at, summary, phase_timeout_min
    read_state,          # (cwd=None) -> LoopState | None
    write_state,         # (state, cwd=None) -> Path
    create_initial_state,# (task_id, cwd=None) -> LoopState  — writes state.json with phase=RECALL
    artifact_path_for,   # (phase, cwd=None) -> Path  — e.g. "RECALL" -> ".techne/loop/recall.txt"
    PHASE_SEQUENCE,      # ["RECALL", "IMPLEMENT", "VERIFY", "CONCLUDE", "DONE"]
    state_path,          # (cwd=None) -> Path
    loop_dir,            # (cwd=None) -> Path
)
```

`artifact_path_for` mapping:
```
RECALL   → .techne/loop/recall.txt
IMPLEMENT→ .techne/loop/diff.txt
VERIFY   → .techne/loop/test_output.txt
CONCLUDE → .techne/loop/conclude.txt
```

`loop_dir()` walks up from CWD to find `.techne/` — project-root-aware.

### `scripts/audit_chain.py`
```python
from audit_chain import (
    AuditEntry,    # dataclass: seq, timestamp, task_id, phase, gates, summary, prev_hash, entry_hash
    append_entry,  # (entry: AuditEntry) -> str  — seals + appends to chain.jsonl
    verify_chain,  # () -> tuple[bool, str]  — (True,"chain intact") or (False,"entry N: reason")
    read_entries,  # () -> list[AuditEntry]
)
```

### `scripts/next.py`
Has a usable `main() -> int` that handles `--init`, `--help-phases`, `--strict-nodes`, and the full gate-run-and-advance flow. The CLI's `techne next` command should call this `main()` directly.

### `harness/plugins/phase_guard.py`
```python
from phase_guard import check_write_allowed
# check_write_allowed(path_str: str, cwd: str | None = None) -> tuple[bool, str]
# Returns (True, '') if write allowed, (False, 'reason') if blocked
```

**ONE BUG TO FIX before wiring the CC hook:** When no `.techne/` is found, the function currently returns `(False, "No .techne directory found.")` — this would block all writes in non-Techne projects. Change it to `(True, "")`:

```python
# In harness/plugins/phase_guard.py, inside check_write_allowed():
root = _find_techne_root(Path(cwd) if cwd else None)
if root is None:
    return (True, "")   # ← CHANGE: was (False, "No .techne directory found.")
```

---

## 5. Python Environment

### Verify first
```bash
python3 --version   # must be 3.10+
pip3 --version
```

### Add scripts/ to path when running tests
The existing test pattern (from `tests/test_workshop_foundation.py`):
```python
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "harness"))
```

---

## 6. Build Order

### Step 0 — Commit ref/
```bash
git add ref/
git commit -m "docs: add OMO/OMH/oh-my-models scouting reference + SCOUTING-REPORT"
```

---

### Step 1 — `pyproject.toml` (at repo root)

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "techne"
version = "0.1.0"
description = "Disciplined engineering harness for AI coding agents"
requires-python = ">=3.10"
dependencies = []

[project.scripts]
techne = "techne_cli.main:cli"

[tool.setuptools.packages.find]
where = ["."]
include = ["techne_cli*"]
```

---

### Step 2 — `techne_cli/__init__.py`
Empty file.

---

### Step 3 — `techne_cli/core.py`

Import bridge that puts `scripts/` and `harness/` on `sys.path`.

```python
"""core.py — Import bridge between techne_cli and scripts/ internals."""
from __future__ import annotations
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "scripts"
_HARNESS = _REPO / "harness"

for _p in [str(_SCRIPTS), str(_HARNESS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from next_state import (          # noqa: E402
    LoopState, read_state, write_state,
    create_initial_state, artifact_path_for,
    PHASE_SEQUENCE, state_path, loop_dir,
)
from audit_chain import (         # noqa: E402
    AuditEntry, append_entry, verify_chain, read_entries,
)

__all__ = [
    "LoopState", "read_state", "write_state",
    "create_initial_state", "artifact_path_for",
    "PHASE_SEQUENCE", "state_path", "loop_dir",
    "AuditEntry", "append_entry", "verify_chain", "read_entries",
]
```

---

### Step 4 — `techne_cli/main.py`

Full CLI. Zero external dependencies — uses only stdlib `argparse`.

```python
"""main.py — Techne CLI entry point."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


# ── Colour helpers ────────────────────────────────────────────────────────────

def _ok(s):   return f"\033[92m✓\033[0m {s}"
def _warn(s): return f"\033[93m⚠\033[0m {s}"
def _fail(s): return f"\033[91m✗\033[0m {s}"
def _bold(s): return f"\033[1m{s}\033[0m"


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_init(args):
    """Initialize a new task in RECALL phase."""
    from techne_cli.core import create_initial_state, state_path, artifact_path_for

    cwd = Path.cwd()
    sp = state_path(cwd)
    if sp.exists() and not args.force:
        print(f"Error: active pipeline already exists at {sp}")
        print("Use --force to overwrite, or run `techne status` to inspect.")
        sys.exit(1)

    # Scaffold required directories
    techne_dir = cwd / ".techne"
    for sub in ["loop", "audit", "memory", "events", "context"]:
        (techne_dir / sub).mkdir(parents=True, exist_ok=True)

    state = create_initial_state(args.task_id, cwd=cwd)
    print(f"Task '{state.task_id}' initialized in RECALL phase")
    print()
    print("Next steps:")
    recall_artifact = artifact_path_for("RECALL", cwd)
    print(f"  1. Write your RECALL artifact:")
    print(f"       {recall_artifact}")
    print(f"     Must contain a 'WORKSHOP_CONTEXT:' header listing context files used.")
    print(f"  2. Run: techne next")


def cmd_next(args):
    """Advance the pipeline one phase."""
    repo = _repo_root()
    next_py = repo / "scripts" / "next.py"
    if not next_py.exists():
        print(f"Error: scripts/next.py not found at {next_py}")
        sys.exit(1)

    import importlib.util
    spec = importlib.util.spec_from_file_location("next_module", next_py)
    mod = importlib.util.module_from_spec(spec)
    # Propagate strict-nodes flag if present
    sys.argv = ["next.py"]
    if getattr(args, "strict_nodes", False):
        sys.argv.append("--strict-nodes")
    spec.loader.exec_module(mod)
    sys.exit(mod.main())


def cmd_status(args):
    """Show current pipeline state."""
    from techne_cli.core import read_state

    cwd = Path.cwd()
    state = read_state(cwd)
    if state is None:
        print("No active pipeline.")
        print("Run: techne init <task-id>")
        sys.exit(0)

    print(_bold("Techne Pipeline Status"))
    print("─" * 40)
    print(f"  Task:    {state.task_id}")
    print(f"  Phase:   {state.phase}")
    print(f"  Updated: {state.updated_at}")

    if state.is_terminal():
        print(_ok("Pipeline DONE"))
    else:
        stale_min = (datetime.now(timezone.utc).timestamp() -
                     datetime.fromisoformat(state.updated_at).timestamp()) / 60
        if stale_min > state.phase_timeout_min:
            print(_warn(f"STALLED — {stale_min:.0f}m in {state.phase} (limit {state.phase_timeout_min}m)"))
        else:
            print(_ok(f"Active — {stale_min:.0f}m in current phase"))

    # Blocked log summary
    blocked_log = cwd / ".techne" / "audit" / "blocked.log"
    if blocked_log.exists():
        lines = [l for l in blocked_log.read_text().splitlines() if l.strip()]
        if lines:
            print(f"\n  Blocked writes (last 3):")
            for l in lines[-3:]:
                print(f"    {l}")

    # RL health
    rl_log = cwd / ".techne" / "events" / "rl.jsonl"
    if rl_log.exists():
        entries = [json.loads(l) for l in rl_log.read_text().splitlines() if l.strip()]
        if entries:
            print(f"\n  RL events: {len(entries)} total")
            last = entries[-1]
            print(f"  Last: reward={last.get('reward','?')} advantage={last.get('advantage','?')}")


def cmd_doctor(args):
    """Run a 6-category health check."""
    from techne_cli.core import read_state, verify_chain

    cwd = Path.cwd()
    print(f"\n{_bold('Techne Doctor')}\n" + "─" * 40)

    # 1. .techne/ exists
    techne_dir = cwd / ".techne"
    if techne_dir.is_dir():
        print(_ok(".techne/ directory found"))
    else:
        print(_fail(".techne/ not found — run: techne init <task-id>"))

    # 2. state.json + stall check
    state = read_state(cwd)
    if state is None:
        print(_warn("No active pipeline (no state.json)"))
    elif state.is_terminal():
        print(_ok(f"Pipeline DONE — task: {state.task_id}"))
    else:
        stale_min = (datetime.now(timezone.utc).timestamp() -
                     datetime.fromisoformat(state.updated_at).timestamp()) / 60
        if stale_min > state.phase_timeout_min:
            print(_warn(f"Pipeline STALLED in {state.phase} for {stale_min:.0f}m"))
        else:
            print(_ok(f"Pipeline active — phase={state.phase}, task={state.task_id}"))

    # 3. Audit chain
    try:
        ok_chain, msg = verify_chain()
        print(_ok("Audit chain intact") if ok_chain else _fail(f"Audit chain BROKEN: {msg}"))
    except Exception as e:
        print(_warn(f"Audit chain unreadable: {e}"))

    # 4. Pending GRPO proposals
    proposals_dir = cwd / ".techne" / "proposals"
    if proposals_dir.exists():
        count = len(list(proposals_dir.glob("*.md")))
        if count:
            print(_warn(f"{count} pending GRPO proposal(s) — review with apply_retro.py"))
        else:
            print(_ok("No pending GRPO proposals"))
    else:
        print(_ok("No proposals directory"))

    # 5. Context pack freshness
    digest = cwd / ".techne" / "context" / "project_digest.md"
    if digest.exists():
        age_h = (datetime.now().timestamp() - os.path.getmtime(digest)) / 3600
        if age_h > 24:
            print(_warn(f"Context pack is {age_h:.0f}h old — run: python3 harness/context_build.py"))
        else:
            print(_ok(f"Context pack fresh ({age_h:.1f}h old)"))
    else:
        print(_warn("No context pack — run: python3 harness/context_build.py"))

    # 6. PreToolUse hook
    hook_found = False
    for settings_path in [cwd / ".claude" / "settings.json",
                           Path.home() / ".claude" / "settings.json"]:
        if settings_path.exists():
            try:
                s = json.loads(settings_path.read_text())
                hooks = s.get("hooks", {}).get("PreToolUse", [])
                if any("phase_guard" in str(h) for h in hooks):
                    hook_found = True
                    print(_ok(f"PreToolUse hook installed ({settings_path})"))
                    break
            except Exception:
                pass
    if not hook_found:
        print(_warn("PreToolUse hook not wired — see HANDOFF-CC-V0.md §7"))

    print()


# ── CLI root ──────────────────────────────────────────────────────────────────

def cli():
    parser = argparse.ArgumentParser(
        prog="techne",
        description="Techne — disciplined engineering harness for AI coding agents",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init", help="Initialize a new task pipeline")
    p_init.add_argument("task_id", help="Unique task identifier (e.g. feat-auth-01)")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing state.json")
    p_init.set_defaults(func=cmd_init)

    # next
    p_next = sub.add_parser("next", help="Advance the pipeline to the next phase")
    p_next.add_argument("--strict-nodes", action="store_true",
                        help="Block VERIFY if node-discipline violations found")
    p_next.set_defaults(func=cmd_next)

    # status
    p_status = sub.add_parser("status", help="Show current pipeline state and RL health")
    p_status.set_defaults(func=cmd_status)

    # doctor
    p_doctor = sub.add_parser("doctor", help="Run a 6-category health check")
    p_doctor.set_defaults(func=cmd_doctor)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    cli()
```

---

### Step 5 — `pip install -e .` and smoke test

```bash
pip install -e .
techne --help
techne init smoke-1
techne status
techne doctor
```

---

### Step 6 — `hooks/phase_guard_hook.py` (the PreToolUse hook)

Create a `hooks/` directory at the repo root.

```python
#!/usr/bin/env python3
"""phase_guard_hook.py — PreToolUse hook for Claude Code.

Claude Code calls this before any Write/Edit/MultiEdit tool call.
Reads the tool payload from stdin (JSON), checks if the write is allowed
given the current Techne pipeline phase, and exits:
  0 = allow
  2 = deny (block the tool call)

Fails open (exit 0) if:
  - stdin is not parseable JSON
  - the harness module can't be imported
  - the tool isn't a write-class tool
  - no .techne/ directory is found in the project tree
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Put harness/ and scripts/ on the path
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "harness"))
sys.path.insert(0, str(_REPO / "harness" / "plugins"))
sys.path.insert(0, str(_REPO / "scripts"))

try:
    from phase_guard import check_write_allowed
except ImportError:
    sys.exit(0)  # Fail open if module not importable


_WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except Exception:
        sys.exit(0)  # Unparseable input — fail open

    tool = payload.get("tool_name", "")
    if tool not in _WRITE_TOOLS:
        sys.exit(0)  # Not a write tool — allow

    inp = payload.get("tool_input", {})
    path = inp.get("file_path") or inp.get("notebook_path") or ""
    if not path:
        sys.exit(0)  # No path — allow

    allowed, reason = check_write_allowed(path, cwd=str(Path.cwd()))
    if not allowed:
        print(f"[phase_guard] BLOCKED: {reason}", file=sys.stderr)
        sys.exit(2)  # Deny the tool call

    sys.exit(0)


if __name__ == "__main__":
    main()
```

Make it executable:
```bash
chmod +x hooks/phase_guard_hook.py
```

---

### Step 7 — Fix `harness/plugins/phase_guard.py` (fail-open patch)

Find this pattern in `check_write_allowed()`:
```python
root = _find_techne_root(Path(cwd) if cwd else None)
if root is None:
    return (False, "No .techne directory found.")
```

Change to:
```python
root = _find_techne_root(Path(cwd) if cwd else None)
if root is None:
    return (True, "")   # No Techne project — allow all writes
```

This is a one-line fix. Without it, the CC hook would block all writes in any directory that isn't a Techne project.

---

### Step 8 — `.claude/settings.json` (project-level CC settings)

Create `.claude/` at the repo root if it doesn't exist. This is the **project-level** settings file — it applies when Claude Code is opened from the techne repo directory.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /ABSOLUTE/PATH/TO/techne/hooks/phase_guard_hook.py"
          }
        ]
      }
    ]
  }
}
```

**Replace `/ABSOLUTE/PATH/TO/techne/` with the actual path on the VPS.** Get it with:
```bash
pwd   # from inside the techne repo
```

---

### Step 9 — `.claude/commands/techne.md` (CC slash command)

```markdown
---
description: "Run a task through Techne's enforced pipeline (RECALL → IMPLEMENT → VERIFY → CONCLUDE → DONE)."
---

You are running a Techne pipeline task. Follow these rules exactly.

## Before you start
- Check if a pipeline is active: run `techne status`
- If no pipeline: run `techne init <task-id>` first
- Read the current phase requirements before writing anything

## Phase artifact requirements
| Phase | Artifact | Required content |
|---|---|---|
| RECALL | `.techne/loop/recall.txt` | Must contain `WORKSHOP_CONTEXT:` header |
| IMPLEMENT | `.techne/loop/diff.txt` | Must contain `@@` and `--- ` diff markers |
| VERIFY | `.techne/loop/test_output.txt` | Must contain pass indicators (passed/0 errors/✓) |
| CONCLUDE | `.techne/loop/conclude.txt` | Must contain `CONTEXT: sha:<40-char-sha>` |

## The loop
```
techne init <task-id>
# write RECALL artifact
techne next
# write IMPLEMENT artifact (git diff output)
techne next
# run tests, write output to VERIFY artifact
techne next
# write CONCLUDE artifact
techne next
# pipeline reaches DONE
```

## Rules
1. Write the phase artifact BEFORE calling `techne next`
2. If `techne next` returns BLOCKED, fix the gate violation — never skip
3. Never write to `.techne/audit/` — audit trail is tamper-evident and off-limits
4. The PreToolUse hook enforces phase discipline — blocked writes mean fix the violation

${{args}}
```

---

### Step 10 — `tests/test_cli.py`

```python
"""test_cli.py — Tests for the techne CLI."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(*args, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["techne", *args],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_help_exits_zero() -> None:
    r = _run("--help")
    assert r.returncode == 0
    assert "init" in r.stdout
    assert "next" in r.stdout
    assert "status" in r.stdout
    assert "doctor" in r.stdout


def test_init_creates_state_json() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write(tmp / ".techne" / "config.yaml", "project_name: test\n")
        r = _run("init", "my-task-1", cwd=tmp)
        assert r.returncode == 0, r.stderr
        state_file = tmp / ".techne" / "loop" / "state.json"
        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert state["task_id"] == "my-task-1"
        assert state["phase"] == "RECALL"


def test_init_fails_if_state_exists_without_force() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write(tmp / ".techne" / "config.yaml", "project_name: test\n")
        _run("init", "task-1", cwd=tmp)
        r = _run("init", "task-2", cwd=tmp)
        assert r.returncode != 0
        assert "force" in r.stdout.lower() or "force" in r.stderr.lower()


def test_init_force_overwrites() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write(tmp / ".techne" / "config.yaml", "project_name: test\n")
        _run("init", "task-1", cwd=tmp)
        r = _run("init", "--force", "task-2", cwd=tmp)
        assert r.returncode == 0
        state = json.loads((tmp / ".techne" / "loop" / "state.json").read_text())
        assert state["task_id"] == "task-2"


def test_next_blocked_when_no_artifact() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write(tmp / ".techne" / "config.yaml", "project_name: test\n")
        _run("init", "task-1", cwd=tmp)
        r = _run("next", cwd=tmp)
        assert r.returncode != 0  # No artifact written — gates should fail


def test_status_no_pipeline() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        r = _run("status", cwd=Path(tmp))
        assert r.returncode == 0
        assert "No active pipeline" in r.stdout


def test_status_shows_phase() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write(tmp / ".techne" / "config.yaml", "project_name: test\n")
        _run("init", "task-1", cwd=tmp)
        r = _run("status", cwd=tmp)
        assert r.returncode == 0
        assert "RECALL" in r.stdout
        assert "task-1" in r.stdout


def test_doctor_exits_zero() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        r = _run("doctor", cwd=Path(tmp))
        assert r.returncode == 0


def test_doctor_detects_no_techne_dir() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        r = _run("doctor", cwd=Path(tmp))
        assert "✗" in r.stdout or "not found" in r.stdout.lower()
```

---

## 7. Definition of Done

The PR is ready when ALL hold:

- [ ] `pip install -e .` succeeds
- [ ] `techne --help` prints init/next/status/doctor
- [ ] `techne init my-task` creates `.techne/loop/state.json` with `phase=RECALL`
- [ ] `techne next` (no artifact) returns exit 1 and prints RECALL requirements
- [ ] `techne next` (valid recall.txt present) advances to IMPLEMENT
- [ ] `techne status` shows phase and task ID
- [ ] `techne doctor` shows all 6 checks with ✅/⚠️/❌
- [ ] `hooks/phase_guard_hook.py` exits 0 when no `.techne/` found (fail-open)
- [ ] `hooks/phase_guard_hook.py` exits 2 when given a wrong-phase-artifact path
- [ ] `.claude/settings.json` wires the hook (absolute path to VPS location)
- [ ] `.claude/commands/techne.md` exists
- [ ] `tests/test_cli.py` — all tests pass
- [ ] All pre-existing tests still pass: `python3 -m pytest tests/`
- [ ] `ref/` committed
- [ ] PR opened against `master`

---

## 8. Files to Create (complete list)

```
pyproject.toml                     ← packaging + console_scripts entry point
techne_cli/__init__.py             ← empty
techne_cli/core.py                 ← import bridge to scripts/ and harness/
techne_cli/main.py                 ← CLI (init/next/status/doctor)
hooks/phase_guard_hook.py          ← PreToolUse hook script
.claude/settings.json              ← hook wiring (project-level CC settings)
.claude/commands/techne.md         ← CC slash command
tests/test_cli.py                  ← CLI tests
```

One edit to an existing file:
```
harness/plugins/phase_guard.py     ← one-line fail-open fix (see §4)
```

---

## 9. How to Commit and Open the PR

```bash
# After all files created and tests pass:
git add pyproject.toml techne_cli/ hooks/ .claude/ tests/test_cli.py
git add harness/plugins/phase_guard.py   # the fail-open fix
git commit -m "feat: Techne for Claude Code v0 — CLI + PreToolUse enforcement hook"
git push origin claude/vigorous-noyce-522718

# Open PR
gh pr create \
  --base master \
  --title "feat: Techne for Claude Code v0 — CLI + PreToolUse enforcement hook" \
  --body "$(cat <<'EOF'
## Techne for Claude Code — v0

Adds a first-class Claude Code edition of Techne's enforcement surface.

### What changed
- **`techne` CLI** (`pip install -e .`) — `init`, `next`, `status`, `doctor` subcommands wrapping existing `scripts/` internals. Replaces the hand-assembled filesystem ritual documented in SKILL.md pitfalls #1-#30.
- **`hooks/phase_guard_hook.py`** — `PreToolUse` hook that calls the existing `harness/plugins/phase_guard.py` checker. Writes that violate phase discipline are **denied at the tool-call layer** in Claude Code. This is the load-bearing enforcement piece.
- **`.claude/settings.json`** — wires the hook project-locally.
- **`.claude/commands/techne.md`** — native CC slash command (complements existing Hermes `commands/techne.toml`).
- **`ref/`** — scouting reference docs (OMO/OMH/oh-my-models + SCOUTING-REPORT.md).
- **`harness/plugins/phase_guard.py`** — one-line fail-open fix: when no `.techne/` directory is found, allow writes instead of blocking everything.

### What wasn't changed
- Existing Hermes plugin (`plugins/techne/`) — untouched
- `scripts/next.py` gate logic — untouched
- All existing skills, tests, docs

### Test plan
- [ ] `pip install -e . && techne --help`
- [ ] `techne init smoke-1 && techne next` (expect: RECALL requirements, exit 1)
- [ ] Write valid `recall.txt`, run `techne next` (expect: advance to IMPLEMENT)
- [ ] `techne doctor` (all 6 checks render with ✅/⚠️/❌)
- [ ] `python3 -m pytest tests/` (all pre-existing tests pass)
EOF
)"
```

---

## 10. What Comes After v0 (don't build these now)

The scouting report in `ref/SCOUTING-REPORT.md` has a 7-item backlog. v0 covers items 1–3. The next priorities:

**Item 4 — Hashline gate (highest-confidence quality borrow from OMO)**
Add a pre-IMPLEMENT-gate hash check: when `diff.txt` is submitted, validate each hunk's context lines against a content hash of the current file. OMO documented 6.7% → 68.3% edit success improvement with this mechanism. Techne's SKILL.md lines 97–110 document the exact same whitespace-corruption pain. The CC hook infrastructure from v0 is the foundation.

**Item 5 — `techne plan` interview**
A Socratic intake skill that fills the ticket schema (OBJECTIVE/CONSTRAINTS/DONE_WHEN) until decision-complete, then hands to `techne init`. Reference design: OMH's `omh-deep-interview`.

**Items 6-7 — `ultrawork` trigger + `techne handoff`**
Natural-language "just do it" loop driver; session continuity doc. Build after the planning interview.

---

*This handoff was produced from a session that read: `scripts/next_state.py`, `scripts/audit_chain.py`, `scripts/next.py` (full), `harness/plugins/phase_guard.py` (80 lines), `commands/techne.toml`, `.techne/config.yaml`, `tests/test_workshop_foundation.py`, `~/.claude/settings.json`, `README.md`, `SKILL.md`. The scouting context is in `ref/SCOUTING-REPORT.md`.*
