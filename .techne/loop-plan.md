# Loop Enforcement Plan — `./next` & One-Loop System

## Problem Statement

The current pipeline relies on the agent's self-report to advance phases.
Agents lie: they claim they "ran the pipeline" when they didn't, they skip
phases, they output fake gate results. The pre_tool_call plugin blocked
writes without a task, but it couldn't force phase progression or produce
auditable proof that a phase was actually completed.

## Design: One Loop, Disk-Proven Phases

### Core Principle

**The proof comes from disk, not from the agent.**
Every phase produces a filesystem artifact. A script reads the artifact,
runs deterministic gates on it, and prints a plain-language summary that
the agent cannot fabricate.

### Phase Sequence (single loop, every task)

```
TASK_CREATE → RECALL → IMPLEMENT → VERIFY → CONCLUDE → DONE
```

Five phases, no exceptions. No "fast / micro / full" modes.
But the gates *inside* each phase self-select based on the diff:

| Gate | Always runs | Self-select condition |
|------|-------------|----------------------|
| artifact exists | yes | — |
| no TODO/console.log | yes | — |
| CONTEXT_GUARD (scope check) | — | diff > 3 files or touches sensitive paths |
| CRITIQUE (emergent bugs) | — | diff > 10 lines or adds new dependency |
| REVIEW (security) | — | diff touches auth, data, or network |
| APPROVAL (HITL) | — | diff touches prod config, schema, or permissions |
| SHA gate | — | test runner exists in project |
| RETRO markers | — | diff > 5 lines |
| EVAL scoring | — | user explicitly requests it |

The agent never chooses which gates fire. The system reads the diff and
decides.

### `./next` — The Central Script

The agent's only interface to the loop is `./next` (aliased to
`python3 ~/repos/techne/scripts/next.py` from any project root).

**What `./next` does:**

1. Read `.techne/loop/state.json` (current task ID + phase)
2. Check that the **expected artifact** for this phase exists on disk
   - RECALL  → `.techne/loop/recall.txt` exists, non-empty
   - IMPLEMENT → git diff is non-empty OR `.techne/loop/diff` exists
   - VERIFY  → `.techne/loop/test_output.txt` exists, non-empty
   - CONCLUDE → `.techne/loop/conclude.txt` exists
   - DONE    → terminal — no artifact needed
3. If artifact missing → print exactly what's needed, exit 1
4. If artifact exists → run deterministic gates on it
5. Print **plain-language summary** in a format the agent can't manipulate:

   ```
   ◇ PHASE: IMPLEMENT
     ✓ diff on disk  (43 lines, 2 files)
     ✓ no console.log
     ✓ no TODO markers
     ✓ scope: focused (touches only auth/)
     ◇ Next: VERIFY

   ◆ VERIFY requirements:
     • Run test suite: python3 -m pytest > .techne/loop/test_output.txt
     • Then call ./next again
   ```

6. Write `.techne/loop/state.json` with the next phase
7. Exit 0

### Artifact Proof Chain

Every phase writes a file BEFORE `./next` is called. The agent can't
call `./next` twice without producing the artifact for the current phase.

```
Phase        | Artifact produced by agent       | Gate checks
-------------|----------------------------------|----------------------------
TASK_CREATE  | .techne/loop/task.json           | valid JSON, has title
RECALL       | .techne/loop/recall.txt          | non-empty, has HONCHO_*
IMPLEMENT    | git diff (auto-detected)         | non-empty, no red flags
VERIFY       | .techne/loop/test_output.txt     | non-empty, SHA gate
CONCLUDE     | .techne/loop/conclude.txt        | honcho confirmation
DONE         | —                                | all prior phases complete
```

The agent produces the artifact as part of doing the phase. Then
`./next` validates it. The validation output (plain-language summary)
is what the user sees — not the agent's self-report.

### Plugin Enforcement (pre_tool_call)

The existing Hermes plugin at `~/.hermes/plugins/techne/` is enhanced to:

1. **Read `.techne/loop/state.json`** to know the current phase
2. **Block writes to artifact paths** that don't match the current phase
   - RECALL active → only `.techne/loop/recall.txt` can be written
   - IMPLEMENT active → code files can be modified (normal dev work)
   - VERIFY active → only `.techne/loop/test_output.txt` allowed
   - CONCLUDE active → only `.techne/loop/conclude.txt` allowed
3. **Force `./next` call** after N tool calls in the same phase
   - After 15 tool calls in RECALL → warn "call ./next to proceed"
   - After 25 tool calls in IMPLEMENT → warn "call ./next to proceed"
   - After 8 tool calls in VERIFY → warn "call ./next to proceed"
4. **Block `./next`** if artifact is missing or phase state is inconsistent
5. **Log every `./next` call** with timestamp, phase, gate results to `.techne/loop/log.json`

## Implementation Plan

### Phase 1: `./next` script (scripts/next.py)

The core script. Standalone Python, no external deps beyond stdlib.

Files to create:
- `scripts/next.py` — the main script
- `scripts/next_state.py` — state.json read/write helpers

Changes to existing:
- `.gitignore` — add `.techne/loop/` entries

### Phase 2: Phase artifacts (define the contract)

Each phase defines:
- What artifact file is expected
- What gates to run
- What the summary format is

### Phase 3: Plugin enhancements (pre_tool_call hook)

Enhance `~/.hermes/plugins/techne/__init__.py`:
- Track `.techne/loop/state.json` on every turn
- Enforce artifact-path write restrictions
- Force `./next` after tool-count threshold

### Phase 4: Remove phase_mode (fast/micro/full)

- Remove `phase_mode` from TaskDB
- Remove `classify_phase_mode`, `validate_mode_fit` from pipeline_enforcer
- Update driver.py to use the new `./next` loop
- Delete old phase_mode tests
- Update all tests

### Phase 5: Test the full loop

- Create a task
- Walk through RECALL → IMPLEMENT → VERIFY → CONCLUDE → DONE
- Verify `./next` rejects missing artifacts
- Verify `./next` prints correct summaries
- Verify plugin blocks wrong-phase writes
- Verify plugin forces `./next` after tool-count threshold

## Files to Create

| File | Purpose |
|------|---------|
| `scripts/next.py` | Main `./next` script — artifact check, gate run, summary print, state advance |
| `scripts/next_state.py` | `LoopState` dataclass, read/write `.techne/loop/state.json` |
| `.techne/loop/` | Directory for loop state (gitignored except state.json schema) |

## Files to Modify

| File | Change |
|------|--------|
| `~/.hermes/plugins/techne/__init__.py` | Add phase-aware write enforcement, force `./next`, tool-count tracking |
| `.gitignore` | Add `.techne/loop/` entries |
| `harness/pipeline_enforcer.py` | Remove phase_mode, simplify to one loop |
| `harness/_loop_types.py` | Remove phase_mode enums, update constants |
| `harness/driver.py` | Update to use `./next` flow |
| `tests/` | Update tests to match single-loop system |
