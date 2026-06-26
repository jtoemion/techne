# Grand Plan — Techne Architectural Overhaul

> Executor: Hermes Agent  
> Date: 2026-06-26  
> Branch: cut from `master`

---

## What This Is

Techne is being redesigned from a heavy CLI harness into two clean layers:

| Layer | What | Where |
|---|---|---|
| **Enforcement** | Hermes plugin — fires at tool-call layer, writes audit + RL events | `.hermes/plugins/techne_plugin.py` |
| **Orchestrator** | Skill — drives RECALL → IMPLEMENT → VERIFY → CONCLUDE, routes to best skill | `.hermes/skills/techne/SKILL.md` |

Everything that was scattered across `harness/`, `scripts/`, `techne_cli/` collapses into this structure. The Hermes agent executing this plan works from `repos/techne` — the development repo that syncs to `.hermes/skills/techne/` in consuming projects.

**State directory:** `.techne/` stays relative (no path changes in code). In deployment it becomes `.hermes/skills/techne/.techne/`.

---

## Architecture After This Plan

```
.hermes/
  plugins/
    techne_plugin.py          ← Hermes enforcement adapter (Task 1)
  skills/
    techne/
      SKILL.md                ← /techne entry point + orchestrator (Task 5)
      skills/                 ← Techne skill library (existing, no change)
      scripts/
        next.py               ← updated: retro wiring + gate hardening (Tasks 2, 3, 4)
        next_state.py
        hash_gate.py
        audit_chain.py
        init_project.py
      hooks/
        phase_guard_hook.py   ← CC adapter (unchanged)
      harness/                ← existing (no change)
      .techne/                ← runtime state (created at task init)
        loop/
        audit/
        context/
        memory/
        events/               ← rl.jsonl lives here (Task 1 writes here)
```

Orchestrator discovers skills from:
1. `.hermes/skills/` — full Hermes ecosystem (omh-deep-research, omh-ralplan, etc.)
2. `skills/` — Techne skill library

---

## Tasks

### Task 1 — Hermes Enforcement Plugin (with GRPO wiring)

**File:** `.hermes/plugins/techne_plugin.py`  
**What:** Create the Hermes enforcement adapter. Mirrors what `.claude/settings.json` PreToolUse hook does for CC, but as an OMH plugin.

Gate fires on every write tool call (`write_file`, `edit_file`, `multi_edit`, `notebook_edit`):
1. Read current phase from `.techne/loop/state.json`
2. At IMPLEMENT: run Hashline gate (`scripts/hash_gate.py`) against `.techne/loop/diff.txt`
3. On any write: check forbidden patterns
4. Write audit event to `.techne/audit/chain.jsonl` (SHA-chained, same format as CC adapter)
5. **Write RL event to `.techne/events/rl.jsonl`** on every gate outcome:

```python
rl_event = {
    "ts": time.time(),
    "phase": phase,
    "gate": gate_name,           # "hashline" | "forbidden" | "audit"
    "reward": 1.0 if passed else -1.0,
    "advantage": 0.5 if passed else -0.5,  # initial; GRPO refines later
    "tool": tool_name,
    "path": file_path,
}
```

Return `None` to allow, `{"blocked": True, "reason": str}` to deny.

**Register in:** `.hermes/config.yaml` (document the line to add, don't create the file — it's project-specific)

**Verify:** Unit test — construct synthetic tool payloads, assert gate fires correctly and rl.jsonl is written.

---

### Task 2 — Wire `_persist_retro` into `./next` CONCLUDE Transition

**File:** `scripts/next.py`  
**What:** When `./next` advances CONCLUDE → DONE, extract DECISION/LESSON/DISCIPLINE markers and persist to ledger, mistakes store, and retros archive. Currently this only runs in the model-backed `OrchestratorLoop` — every CC task silently throws wisdom away.

**Where in next.py:** Find the `if old_phase == "CONCLUDE":` block (around line 735). After the wikilink rebuild block, add:

```python
# Wire wisdom extraction
try:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "harness"))
    from _retro_conclude import _persist_retro
    conclude_text = (cwd / ".techne" / "loop" / "conclude.txt").read_text()
    _persist_retro(state.task_id, conclude_text, state.task_id)
except Exception:
    pass  # best-effort — never block DONE on retro failure
```

**Verify:** Integration test — write a conclude.txt with DECISION/LESSON/DISCIPLINE markers, run `./next`, assert `.techne/memory/ledger.md` and `.techne/memory/retros/` are written.

---

### Task 3 — Harden CONCLUDE Gate

**File:** `scripts/next.py` → `_check_conclude_gates()`  
**What:** Current gate passes on `HONCHO: done ok this was fine` (trivially short, no structure). Add three checks:

**3a. Require retro markers** — at least one of DECISION/LESSON/DISCIPLINE:
```python
has_markers = bool(re.search(
    r"^\s*[-*]\s+(DECISION|LESSON|DISCIPLINE):", text, re.MULTILINE
))
results.append(GateResult(
    "retro markers",
    has_markers,
    "DECISION/LESSON/DISCIPLINE found" if has_markers
    else "missing retro markers — add: DECISION: / LESSON: / DISCIPLINE:",
))
```

**3b. Require VERIFY reference** — conclusion must acknowledge test results:
```python
has_verify_ref = bool(re.search(
    r"(?:tests?\s+pass|all\s+\d+\s+pass|pytest|test_output|✓)", text, re.I
))
results.append(GateResult(
    "verify reference",
    has_verify_ref,
    "test reference found" if has_verify_ref
    else "no test reference — mention test results in conclude.txt",
))
```

**3c. Raise minimum length** — from 20 chars to 150 chars:
Find the existing length check and update the threshold.

**Verify:** Unit tests — assert short/markerless conclude.txt is blocked; assert well-formed conclude.txt with markers passes.

---

### Task 4 — Harden RECALL Gate

**File:** `scripts/next.py` → `_check_recall_gates()`  
**What:** Current gate passes on `WORKSHOP_CONTEXT: none` — agent can skip reading the context pack. Require a reference to at least one file in `.techne/context/`:

```python
has_context_ref = bool(re.search(
    r"\.techne/context/|project_digest|file_roles|context_hash", text
))
results.append(GateResult(
    "context reference",
    has_context_ref,
    "context file referenced" if has_context_ref
    else "no .techne/context/ reference — read context pack before RECALL",
))
```

**Verify:** Unit test — assert recall.txt without context reference is blocked; assert recall.txt with `.techne/context/project_digest.md` reference passes.

---

### Task 5 — Promote Orchestrator to `/techne` Skill Entry Point

**Files:**  
- `.hermes/skills/techne.md` → convert to directory: `.hermes/skills/techne/SKILL.md`  
- `skills/orchestrator/SKILL.md` — merge orchestrator content into the new entry point

**What:** The `/techne` Hermes slash command and the orchestrator are the same thing. Merge them. The single `SKILL.md` at `.hermes/skills/techne/SKILL.md` should:

1. Open with doctor check + skill inventory (as in `.hermes/skills/techne.md`)
2. Include the full loop sequence (RECALL → IMPLEMENT → VERIFY → CONCLUDE)
3. Include skill routing table (when to call omh-deep-research, omh-ralplan, etc.)
4. Include HITL blocking protocol
5. Include health commands

Delete `.hermes/skills/techne.md` (flat file) once the directory-based version exists.

Keep `skills/orchestrator/SKILL.md` as a symlink or redirect to the canonical location for backward compatibility with existing CC sessions.

**Verify:** `hermes skills validate techne` (or equivalent) — confirm skill is loadable.

---

### Task 6 — `techne gate` CLI Subcommand

**File:** `techne_cli/main.py`  
**What:** Gates must be callable standalone so the Hermes plugin and any other runtime can invoke them without importing Python modules directly.

```bash
techne gate hashline <diff_file>    # exit 0 pass, exit 1 fail + reason on stdout
techne gate forbidden <diff_file>   # exit 0 pass, exit 1 + pattern on stdout
techne gate audit <json_event>      # append to .techne/audit/chain.jsonl, exit 0
```

Add `cmd_gate(args)` to `techne_cli/main.py` and wire into `cli()`:
```python
p_gate = sub.add_parser("gate", help="Run a named gate check")
p_gate.add_argument("name", choices=["hashline", "forbidden", "audit"])
p_gate.add_argument("target", help="diff file path or JSON event string")
p_gate.set_defaults(func=cmd_gate)
```

`cmd_gate` calls the existing scripts (`hash_gate.validate_diff_context`, `_check_no_forbidden_patterns`, `audit_chain.append_event`) and exits with the right code.

**Verify:** `techne gate hashline <clean_diff>` exits 0; `techne gate hashline <stale_diff>` exits 1 with reason on stdout.

---

## Execution Order

```
Task 6 first  — gate CLI needed by Task 1 (plugin calls techne gate)
Task 1        — Hermes plugin (depends on Task 6 for gate calls)
Task 2        — retro wiring (independent, low-risk)
Task 3        — CONCLUDE hardening (depends on Task 2 being wired)
Task 4        — RECALL hardening (independent)
Task 5        — orchestrator skill merge (independent, do last)
```

---

## What Does NOT Change

- Path constants — `.techne/` stays relative everywhere; no code changes needed
- `harness/` internals — model-backed driver unchanged
- CC PreToolUse hook (`hooks/phase_guard_hook.py`) — still works for CC sessions
- `scripts/hash_gate.py` — gate logic unchanged; just exposed via CLI in Task 6
- `harness/grpo.py` — GRPO proposal logic unchanged; Task 1 only adds RL event writes

---

## Done When

- [ ] `techne gate hashline` / `forbidden` / `audit` callable as CLI (Task 6)
- [ ] `.hermes/plugins/techne_plugin.py` blocks stale diffs and writes rl.jsonl (Task 1)
- [ ] CONCLUDE → DONE writes to `.techne/memory/` (Task 2)
- [ ] conclude.txt without retro markers is blocked (Task 3)
- [ ] recall.txt without context reference is blocked (Task 4)
- [ ] `/techne` loads as a Hermes skill from `.hermes/skills/techne/SKILL.md` (Task 5)
- [ ] All existing tests still pass
