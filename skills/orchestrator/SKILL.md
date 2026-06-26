---
name: orchestrator
description: Subagent dispatch protocol + loop runner. Parent agent reads this to decompose plans and drive the pipeline. Works in Claude Code (ultrawork / ulw) and Hermes Agent (/techne).
---

# Orchestrator — Pipeline Loop Runner

## Skill Discovery

Before selecting a skill for any phase, check available skills in this order:

```
1. .hermes/skills/     — Hermes-native skills (omh-deep-research, omh-ralplan, etc.)
2. skills/             — Techne skills (grill, persona-brainstorm, writing-skill, etc.)
3. .claude/commands/   — CC slash commands
```

List available skills at the start of a session:
```bash
ls .hermes/skills/ 2>/dev/null   # Hermes ecosystem
ls skills/                        # Techne library
```

Select the best skill for the task at each phase — you are not limited to Techne's library.
Techne enforces the pipeline. It does not decide which skill runs inside it.

---

## Entry Points

| Runtime | Command |
|---|---|
| Claude Code | `/techne` then `ultrawork <task>` |
| Hermes Agent | `/techne` (`.hermes/skills/techne.md`) |

---

## Claude Code Autonomous Mode (`ultrawork` / `ulw`)

> **Trigger words:** `ultrawork <task-description>` or `ulw <task-description>`
>
> When the user says this, run the full pipeline hands-free from RECALL to DONE,
> surfacing only phase reports and HITL blocks. Claude Code IS the model — no
> `run_plan()` call needed.

### Loop sequence

```
1. techne init <task-id>          # scaffolds .techne/loop/, sets phase=RECALL

2. RECALL
   • Read .techne/context/ (project digest, file roles)
   • Search codebase / memory for relevant prior work
   • Write .techne/loop/recall.txt  (must contain WORKSHOP_CONTEXT: line)
   • techne next  → IMPLEMENT

3. IMPLEMENT
   • Make all code changes (via Edit/Write tools — phase_guard enforces phase)
   • git diff > .techne/loop/diff.txt
   • techne next  → VERIFY    (Hashline gate validates diff context here)

4. VERIFY
   • pytest > .techne/loop/test_output.txt  (or project's test command)
   • techne next  → CONCLUDE

5. CONCLUDE
   • Write .techne/loop/conclude.txt  (summary + HONCHO: <id> line)
   • techne next  → DONE

6. Forward the phase report printed by techne next to the user after each transition.
```

### HITL blocking protocol

Stop and surface to the user when:
- `techne next` exits non-zero (gate failure) — show the full report, do NOT edit state.json
- Hashline gate rejects the diff (`stale read`) — re-read the file(s) named in the error, regenerate diff
- VERIFY finds failing tests — fix then re-run VERIFY phase (don't skip ahead)
- Any phase requires a decision only the user can make (design choice, external credential, etc.)

### Phase guard

Claude Code's writes are gated by the PreToolUse hook in `.claude/settings.json`.
Writing to the wrong artifact path will be **BLOCKED** — fix the phase, not the hook.

```
RECALL    → write .techne/loop/recall.txt only
IMPLEMENT → write source files + .techne/loop/diff.txt
VERIFY    → write .techne/loop/test_output.txt only
CONCLUDE  → write .techne/loop/conclude.txt only
```

### Health commands

```bash
techne status    # current phase + stall check
techne doctor    # 6-category check (hook wired, chain intact, context fresh)
techne handoff   # write handoff.md for session continuity / resume tomorrow
```

---

## Who Reads This (model-backed / Hermes mode)

The PARENT agent reads this to:
1. Decompose the plan into atomic tasks
2. Create tasks in task_db
3. Drive the loop (or hand off to orchestrator_loop.py)

Subagents read their own agent definition — they never see this.

## The Architecture

```
Parent Agent (you)
│
├─ decompose plan → task_db.create_task() × N
│
├─ LOOP per task:
│   │
│   ├─ loop.next_phase(task_id) → "IMPLEMENT"
│   ├─ loop.get_prompt(task_id, "IMPLEMENT") → {system, user}
│   ├─ delegate_task(prompt) → result
│   ├─ loop.submit(task_id, "IMPLEMENT", result) → LoopOutcome
│   │
│   │   LoopOutcome.action:
│   │     RUN_PHASE  → advance to next phase
│   │     RETRY      → same phase with feedback
│   │     BLOCK_HITL → present question to human, wait
│   │     ESCALATE   → dispatch debugger
│   │     DONE       → task complete
│   │     FAILED     → terminal failure
│   │
│   └─ repeat until DONE or FAILED
│
└─ loop.summary() → dashboard
```

## Step 0: Pre-Compaction Honcho Checkpoint

Before a long run that may hit session compaction, preserve durable facts FIRST —
raw context is discarded on compact, so checkpoint to Honcho before you lose it.

```python
# extract durable facts → honcho_conclude → verify recall → then proceed
honcho_conclude(conclusion="<one durable fact>", peer="user")
```

Checkpoint: user preferences, project conventions, architecture decisions, HITL
boundaries. Skip transient state (TODOs, command output, SHAs). Full rules +
fallback (Hermes memory if Honcho is down) → `skills/honcho-precompaction-checkpoint.md`.

## Step 1: Decompose

Break the plan into atomic tasks. Each task:
- Single responsibility
- TDD-natured (testable)
- Independent (unless parent_id links them)

```python
from task_db import TaskDB
db = TaskDB()

t1 = db.create_task("Create auth middleware", discipline="tdd")
t2 = db.create_task("Add login endpoint", discipline="tdd")
t3 = db.create_task("Protect routes", parent_id=t1.id, discipline="tdd")
```

## Step 2: Drive the Loop

```python
from orchestrator_loop import OrchestratorLoop

loop = OrchestratorLoop(db)

for task in db.get_tasks_by_status("PENDING"):
    while loop.has_work(task.id):
        phase = loop.next_phase(task.id)
        prompt = loop.get_prompt(task.id, phase)

        # Dispatch subagent
        result = delegate_task(
            goal=f"{phase}: {task.title}",
            context=prompt["user"],
            toolsets=phase_toolsets(phase),
        )

        # Submit result to loop
        outcome = loop.submit(task.id, phase, result)

        # Handle outcome
        if outcome.action == LoopAction.BLOCK_HITL:
            # Present to human, wait for decision
            decision = clarify(
                question=outcome.question,
                choices=outcome.options,
            )
            loop.unblock(task.id, decision=decision)
            # Loop continues from next valid phase

        elif outcome.action == LoopAction.ESCALATE:
            # Dispatch debugger
            debug_prompt = loop.get_prompt(task.id, "DEBUG")
            debugger_result = delegate_task(
                goal=f"Debug: {task.title}",
                context=debug_prompt["user"],
                toolsets=["terminal", "file"],
            )
            # After debugger, loop goes back to IMPLEMENT

        elif outcome.action == LoopAction.RETRY:
            # Loop auto-retries same phase
            pass
```

## Step 3: HITL Blocking

The loop automatically blocks for HITL when:
1. **Critique finds CRITICAL** → presents finding, asks human to decide
2. **Review fails HARD_FAIL** → asks human: retry, debug, or override
3. **Tests fail after max retries** → asks human: debug, manual fix, or abandon
4. **Debug exhaustion** → asks human: manual fix or abandon

The human's decision is recorded in task_db and the loop resumes.

## Toolsets Per Phase

```python
def phase_toolsets(phase: str) -> list[str]:
    return {
        "IMPLEMENT":    ["terminal", "file"],
        "CONTEXT_GUARD":["terminal", "file"],  # needs git diff
        "CRITIQUE":     ["file"],              # read-only
        "REVIEW":       ["file"],              # read-only
        "VERIFY":       ["terminal"],          # runs tests
        "DEBUG":        ["terminal", "file"],  # diagnostic + fix
    }.get(phase, ["terminal", "file"])
```

## What Each Subagent Gets

Minimal, self-contained:
- Task title + description
- Phase instructions (from their .md)
- Prior phase results (summary, not full output)
- Past mistakes for this task type

They do NOT get:
- The loop state machine
- Other tasks' information
- The enforcer internals

## Failure Escalation

```
Attempt 1 → retry with gate feedback
Attempt 2 → retry with critique context
Attempt 3 → BLOCK_HITL: "needs debugger"
Debugger   → retry from IMPLEMENT
Debugger fails → BLOCK_HITL: "manual fix or abandon"
```

## Dashboard

```python
print(loop.summary())
# Shows: task status, current phase, attempt counts, blocked tasks
```

## Anti-Patterns

- **Don't let subagents self-report completion.** The parent calls loop.submit().
- **Don't skip phases.** The enforcer rejects it deterministically.
- **Don't handle HITL yourself in a subagent.** Block, present to human, wait.
- **Don't forget to record the decision.** loop.unblock() does it automatically.

## Next Steps

- Tasks created? → start the loop
- All done? → dispatch retro-learn agent
- Want to see status? → `loop.summary()`
