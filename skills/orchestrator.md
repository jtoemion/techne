---
name: orchestrator
description: Subagent dispatch protocol + loop runner. Parent agent reads this to decompose plans and drive the pipeline. Uses orchestrator_loop.py for deterministic phase transitions, HITL blocking, and debugger escalation.
---

# Orchestrator — Pipeline Loop Runner

## Who Reads This

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
