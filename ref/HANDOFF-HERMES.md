# Techne Plugin — Hermes Agent Handoff

> For a Hermes agent building Techne enforcement for their project.
> Equivalent to the Claude Code `PreToolUse` hook + `techne gate` CLI.
> Date: 2026-06-26

---

## What Techne Enforcement Does

Techne is a two-layer system:

| Layer | What it does | Who owns it |
|---|---|---|
| **Enforcement plugin** | Blocks bad writes at tool-call layer; runs gate checks; writes audit events | Techne (runtime adapter) |
| **Orchestrator** | Drives RECALL → IMPLEMENT → VERIFY → CONCLUDE; selects skills; tracks phase state | The agent (skill-driven) |

The plugin is runtime-specific. This document describes the **Hermes adapter**.

---

## Gate Utilities (Runtime-Agnostic)

All gates are callable as a CLI regardless of runtime:

```bash
techne gate hashline <diff_file>   # exit 0 = pass, exit 1 = fail + reason on stdout
techne gate forbidden <diff_file>  # exit 0 = pass, exit 1 = forbidden pattern found
techne gate audit <event_json>     # append event to .techne/audit/chain.jsonl
techne doctor                      # 6-category health check
```

These are the same Python scripts used by the CC adapter. The Hermes plugin calls them via subprocess.

---

## Hermes Plugin Spec

### Requirements

- Hermes Agent v0.7.0+
- Python 3.10+, `pyyaml`
- OMH plugin system enabled

### File layout

```
.hermes/
  plugins/
    techne_plugin.py          ← enforcement plugin (build this)
  skills/
    techne.md                 ← /techne slash command (copy from below)
```

### `techne_plugin.py`

The OMH plugin uses hook-based role injection. Wire Techne gates into the `pre_tool_use` hook:

```python
"""Techne enforcement plugin for Hermes Agent."""
import subprocess, json
from pathlib import Path

WRITE_TOOLS = {"write_file", "edit_file", "multi_edit", "notebook_edit"}
GATE_SCRIPT = Path(__file__).parent.parent.parent / "scripts"  # adjust to techne install

def pre_tool_use(tool_name: str, tool_input: dict, state: dict) -> dict | None:
    """
    Return None to allow, or {"blocked": True, "reason": str} to deny.
    Fires before every tool call.
    """
    if tool_name not in WRITE_TOOLS:
        return None

    phase = _read_phase()

    # Audit every write attempt
    _audit(tool_name, tool_input, phase)

    # IMPLEMENT phase: validate diff context before applying
    if tool_name in {"edit_file", "multi_edit"} and phase == "IMPLEMENT":
        diff_path = Path(".techne/loop/diff.txt")
        if diff_path.exists():
            result = subprocess.run(
                ["python3", str(GATE_SCRIPT / "hash_gate.py"), str(diff_path)],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                return {
                    "blocked": True,
                    "reason": f"Hashline gate: {result.stdout.strip()} — re-read the file"
                }

    # Forbidden patterns check on any write
    if tool_name in WRITE_TOOLS:
        content = tool_input.get("content", "") or tool_input.get("new_content", "")
        forbidden = _check_forbidden(content)
        if forbidden:
            return {"blocked": True, "reason": f"Forbidden pattern: {forbidden}"}

    return None


def _read_phase() -> str:
    state_file = Path(".techne/loop/state.json")
    if not state_file.exists():
        return "UNKNOWN"
    try:
        return json.loads(state_file.read_text()).get("phase", "UNKNOWN")
    except Exception:
        return "UNKNOWN"


def _audit(tool_name: str, tool_input: dict, phase: str):
    import hashlib, time
    chain_path = Path(".techne/audit/chain.jsonl")
    chain_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "ts": time.time(),
        "tool": tool_name,
        "phase": phase,
        "path": tool_input.get("path", tool_input.get("file_path", "")),
    }
    # Append with SHA chain
    prev_hash = ""
    if chain_path.exists():
        lines = chain_path.read_text().strip().splitlines()
        if lines:
            prev_hash = json.loads(lines[-1]).get("hash", "")
    payload = json.dumps(event)
    event["hash"] = hashlib.sha256(f"{prev_hash}{payload}".encode()).hexdigest()
    with chain_path.open("a") as f:
        f.write(json.dumps(event) + "\n")


FORBIDDEN_PATTERNS = [
    "rm -rf", "DROP TABLE", "os.system", "__import__('os').system",
    "subprocess.call(['rm'", "shutil.rmtree",
]

def _check_forbidden(content: str) -> str | None:
    for pat in FORBIDDEN_PATTERNS:
        if pat in content:
            return pat
    return None


# OMH plugin registration
PLUGIN_MANIFEST = {
    "name": "techne",
    "version": "0.1.0",
    "description": "Techne enforcement gates for Hermes Agent",
    "hooks": {
        "pre_tool_use": pre_tool_use,
    },
}
```

### Register the plugin

In your project's `.hermes/config.yaml`:

```yaml
plugins:
  - .hermes/plugins/techne_plugin.py
```

---

## `/techne` Slash Command for Hermes

Create `.hermes/skills/techne.md`:

```markdown
---
name: techne
description: Run a task through Techne's enforced pipeline (RECALL → IMPLEMENT → VERIFY → CONCLUDE → DONE).
---

You are running a Techne pipeline task under Hermes Agent.

## Before you start

1. Verify enforcement is active: `techne doctor`
2. Check skill inventory:
   - `ls .hermes/skills/`  — Hermes-native skills available
   - `ls skills/`          — Techne skill library
3. Check if a pipeline is active: `cat .techne/loop/state.json`
4. If no pipeline: `techne init <task-id>`

## Phase sequence

RECALL → IMPLEMENT → VERIFY → CONCLUDE → DONE

At each phase, select the best available skill from .hermes/skills/ or skills/.
You are not limited to Techne's library — use omh-deep-research, omh-ralplan,
omh-deep-interview, or any installed Hermes skill as needed.

## Phase artifacts

| Phase | Artifact | Required content |
|---|---|---|
| RECALL | `.techne/loop/recall.txt` | `WORKSHOP_CONTEXT:` header |
| IMPLEMENT | `.techne/loop/diff.txt` | `@@` and `--- ` diff markers |
| VERIFY | `.techne/loop/test_output.txt` | pass indicators |
| CONCLUDE | `.techne/loop/conclude.txt` | `HONCHO: <id>` line |

## Gate checkpoints

Before advancing each phase, run:
```bash
techne gate hashline .techne/loop/diff.txt    # IMPLEMENT only
techne gate forbidden .techne/loop/diff.txt   # IMPLEMENT only
techne next                                    # advance phase, prints report
```

## HITL blocking

Stop and surface to the user when:
- `techne next` exits non-zero — show full report, do NOT edit state.json
- Hashline gate rejects the diff — re-read the named files, regenerate diff
- VERIFY finds failing tests — fix, re-run, do not skip ahead
- Any decision requires human judgment

## Health commands

```bash
techne status    # current phase + stall check
techne doctor    # enforcement health check
techne handoff   # write session continuity doc
```

${{args}}
```

---

## Orchestrator Skill

The orchestrator (`skills/orchestrator/SKILL.md`) works in both runtimes.
Under Hermes, the loop is driven by the skill (prose-based), not by a Python driver.

Key difference from CC mode:
- **CC**: PreToolUse hook fires automatically via `.claude/settings.json`
- **Hermes**: OMH plugin's `pre_tool_use` hook fires via `.hermes/config.yaml`
- Gate utilities (`techne gate *`) are the same in both cases

The orchestrator discovers skills from `.hermes/skills/` first, then `skills/`.

---

## Verification

After installing the plugin, verify enforcement is live:

```bash
techne doctor
# Expected output:
# ✓ hook registered (.hermes/plugins/techne_plugin.py present)
# ✓ gate utilities callable (techne gate hashline --version)
# ✓ audit chain writable (.techne/audit/chain.jsonl)
# ✓ context pack present (.techne/context/)
```

Then do a smoke test: submit a diff with a known-stale context line and confirm
the Hashline gate blocks it before `techne next` is called.

---

## What NOT to port

- `techne_cli/` — the CLI is shared; install Techne as a package, don't rewrite it
- `scripts/` gate utilities — shared; call via subprocess
- `.claude/settings.json` — CC-only; Hermes uses `.hermes/config.yaml` instead
