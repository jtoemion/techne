# GRPO/RL Production Plan — Closing the RL Loop

Date: 2026-06-23
Author: Megumi Kato
Status: DRAFT
Depends on: enforcement stack (finalized in e37f930)

## Current State

```
                ┌──────────────────────┐
                │ Pipeline task runs    │
                │ through submit()      │
                │ phases → DONE         │
                └──────────┬───────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │ reward_log.record()  │──→ rewards.db (SQLite)
                │ called in submit()   │
                └──────────┬───────────┘
                           │
                           ▼  (NEVER HAPPENS in normal pipeline)
                ┌──────────────────────┐
                │ post_run_evolve()    │──→ compute_batch_advantages()
                │ Only from driver.py  │──→ propose_grpo_edits()
                └──────────────────────┘
```

The RL loop is broken at the integration point: data flows **in** to `rewards.db` but no code path flows **back out** to compute advantages or generate proposals. Everything below `post_run_evolve()` is dead code on the normal pipeline path.

## Target Architecture

```
Pipeline task DONE
  │
  ├── submit() records reward (as today)
  │
  └── OrchestratorLoop.on_task_done(tid)
        │
        ├── 1. Identify task type from task tags/discipline
        ├── 2. Compute batch advantages across all tasks grouped by type
        ├── 3. Generate GRPO proposals (prompt variants)
        ├── 4. Generate skill proposals (P4 — currently missing)
        ├── 5. Award reward.md wins (merge reward.py path)
        └── 6. Log rl_dashboard to .techne/events/ for visibility
```

---

## Reward Function (Explicit)

This is the existing `_composite_score()` in `harness/reward_log.py:544`.
It's well-designed but undocumented. Making it explicit here so the plan
is complete.

### Formula

```
composite_score = violation_penalty × Σ(W_i × C_i)

violation_penalty = max(0.0, 1.0 - gate_violations × 0.15)

Components C_i:
  gate_pass         = 1.0 if passed, 0.0 if failed
  test_pass         = 1.0 if passed, 0.0 if failed
  review_clean      = 1.0 if no findings, else max(0.0, 1.0 - N × 0.2)
  critique_accuracy = 0.0-1.0 (fuzzy match: % of review findings predicted)
  scope_clean       = 1.0 if focused, 0.0 if scope creep
  attempt_efficiency = max(0.0, 1.0 - (attempts - 1) × 0.25)

Weights W_i (sum = 1.0):
  test_pass         0.25  — strongest signal. Tests are ground truth.
  review_clean      0.20  — peer review catches logic issues.
  gate_pass         0.20  — hard gates catch format/scope violations.
  critique_accuracy 0.15  — cross-agent prediction accuracy.
  scope_clean       0.05  — scope creep is a minor signal.
  attempt_efficiency 0.05 — retries reduce score slightly.
  gate_violations   0.10  — multiplicative penalty, not additive.

### Why these weights

  test_pass         Highest because test outcome is the closest thing to
                    ground truth in code generation. If tests pass, the
                    implementation is probably correct.

  review_clean      Second only to tests. A review finding means a human
                    (or reviewer agent) found something the implementation
                    missed. Zero findings = clean implementation.

  gate_pass         Hard gates are deterministic (diff format, no console.log,
                    no TODO). A gate failure means sloppy work regardless of
                    test outcome. Gates caught 4/5 bugs in the real session.

  critique_accuracy Cross-agent score: if critique predicted what reviewer
                    found, the critique agent did its job. If critique misses
                    everything, findings that should have been caught early
                    slipped through. This rewards good upstream work.

  scope_clean       Low weight. Scope creep is a process concern, not a
                    correctness concern. But it matters enough to nudge.

  attempt_efficiency Low weight. First-attempt success is ideal, but retries
                    are normal. The penalty is gentle (0.25 per retry).

  gate_violations   Multiplicative, not additive. A task with 2 gate violations
                    (penalty 0.70) and perfect signals (weighted_sum = 0.65)
                    scores 0.455 — still above zero because the implementation
                    may be correct despite process failures. Not a hard kill.

### Advantage calculation (GRPO)

After composite scores are computed for all tasks in the same group
(where group = task_type by default), each task's advantage is:

  advantage = composite_score - mean(composite_scores_in_group)

A prompt variant or skill that consistently achieves positive advantage
(avg_advantage > threshold, default 0.2) triggers a propose_grpo_edits()
or propose_skill_edits() proposal.

---

## Repetition Handling (Explicit)

### Minimum runs requirement

No proposal is generated from a single task run. Both
`high_advantage_variants()` and `high_advantage_skills()` require
`cnt >= 2` in the SQL query — two or more task runs with the same
prompt_variant or (task_type, skill) pair.

This prevents noise: a single lucky run with a new variant doesn't
trigger a permanent skill edit.

### Dedup — already proposed entries

Both `propose_grpo_edits()` and `propose_skill_edits()` check existing
proposals before writing new ones. They load `retro_proposals.md` and
skip variants/skills that already have an un-applied proposal.

This means: if variant `v4_experimental` scored high advantage after 3 runs,
a proposal is generated. If run 4 and 5 also score well, no duplicate
proposal. Only when the first proposal is applied (or rejected) does
a new one become eligible.

### Dedup — same task_id

The `has_task()` check in `RewardLog.record()` prevents recording the
same task_id twice. If `submit()` is called with the same task_id for
the same phase, the second attempt is a retry — it doesn't double-count.

### What about the same task_type repeated 50 times?

The `high_advantage_variants()` query groups by (task_type, prompt_variant)
and averages the composite score. Running 50 tasks with variant `v2_pragmatic`
produces one average score — the variant is evaluated as a whole, not
per-task. If the average drifts over time, that's captured by the mean
recalculation on every `compute_batch_advantages()` call.

No sliding window yet. If a variant performs well for 10 runs then degrades,
it takes 10 more runs to pull the average down. Future improvement:
add a recency-weighted average (γ = 0.9, last N runs weighted higher).

### The batch-size question (Phase 6 — optional)

The `compute_batch_advantages()` function groups by task_type. It's not
a true "batch" in the RL sense — it recomputes advantages across ALL
existing rewards in each group, not just the most recent N.

This means: 
- First task of a new type: no group mean yet, advantage = 0.0
- Second task of same type: group has 2 members, mean is computed,
  advantages are meaningful (but min_runs=2 required for proposals)
- After 5 tasks of the same type: mean stabilizes, advantages reflect
  genuine performance differences

The TrajectoryQueue (Phase 6) adds an alternative: collect N tasks and
score them together as one batch before releasing proposals. This is a
config option for advanced users. The default path (compute over all
existing rewards) is simpler and works for most cases.

### Multi-agent repetition (same task, different agents)

When multiple agents (implementer + critique + reviewer) all feed into
the same reward record, each agent's prompt variant is tracked separately
in the reward. The `prompt_variant` field refers to which agent prompt
variant was used. The `skill` field (P4) tracks which skill file the
edit targets.

This means: a task that uses `implementer_v2` and `critique_v1` records
two rewards — one per agent prompt variant. Each is evaluated against
the same test/gate/review outcome. This lets the system compare:
"did implementer_v2 produce better code than implementer_v1?" independent
of which critique variant was selected.

---

## Build Order

### Phase 1 — Wire post_run_evolve() into the pipeline

**Files:**
- `harness/orchestrator_loop.py` — modify `submit()` to call
  `post_run_evolve()` when phase transitions to DONE

**Change:**
In the DONE branch of `submit()`, after marking the task complete:

```python
# After task reaches DONE, trigger RL/GRPO computation
try:
    evo = self.post_run_evolve()
    if evo.get("grpo_proposed"):
        logger.info("[rl] GRPO proposed %d variant edits",
                     len(evo["grpo_proposed"]))
except Exception:
    logger.warning("[rl] post_run_evolve failed (non-blocking)", exc_info=True)
```

**Before/after:**
- Before: `submit()` returns `LoopOutcome(action=DONE)` — no RL trigger
- After: `submit()` returns same `LoopOutcome(action=DONE)` — RL trigger is
  fire-and-forget inside the method, doesn't change the return contract

**Tests:** `tests/test_orchestrator_driver.py` — verify `post_run_evolve`
is called when a task reaches DONE (mock the reward_log, assert
`compute_batch_advantages` was called)

---

### Phase 2 — Wire propose_skill_edits() into post_run_evolve()

**Files:**
- `harness/_orchestrator_context.py` — add `propose_skill_edits()` call

**Change:**
In the try block of `post_run_evolve()`, after `propose_grpo_edits()`:

```python
# Also propose skill-based edits (P4 — one line fix)
skill_proposals = propose_skill_edits(self.reward_log)
if skill_proposals:
    result["grpo_proposed"].extend(
        {"type": "skill", **p} for p in skill_proposals
    )
```

**Before/after:**
- Before: `post_run_evolve()` only calls `propose_grpo_edits()`
- After: calls both, result includes skill + variant proposals

**Tests:** `tests/test_grpo_proposals.py` — existing P4 tests verify
`propose_skill_edits()` works in isolation. Add integration test:
`test_post_run_evolve_calls_both` — mock reward_log, assert both
proposal functions are called.

---

### Phase 3 — RL Dashboard in /techne status

**Files:**
- `~/.hermes/plugins/techne/__init__.py` — add RL section to status
- `harness/orchestrator_loop.py` — add `rl_summary()` method

**Change:**
Add a lightweight RL summary that the plugin can call. Not the full
`rl_dashboard()` (which is expensive — it reads the entire reward DB).
Instead, a quick file-based check:

```python
# Quick RL health: count of rewards, count of proposals pending
def rl_health(self) -> dict:
    reward_count = self.reward_log.count()
    pending = len(grpo._load_existing_proposals(...))
    return {"rewards": reward_count, "pending_proposals": pending,
            "last_advantage_run": "...", "rl_alive": advantage_ever_computed}
```

Show in `/techne status`:
```
RL Health:
  Rewards logged: 47
  Pending proposals: 3
  Last advantage computed: 2026-06-23T14:32:00
  RL loop: ACTIVE (last batch: 12 tasks, 2 proposals generated)
```

---

### Phase 4 — Consolidate reward.py into reward_log.py

**Files:**
- `harness/reward_log.py` — add `log_win()` method
- `harness/reward.py` — deprecate, keep as thin compat wrapper
- Update all callers of `reward.log_clean()` / `reward.log_solved()`

**Change:**
`reward_log.py` already has a SQLite DB with rich reward data. `reward.py`
writes human-readable wins to `reward.md` from the same signals. Move the
human-readable win logging into `RewardLog.record()` so there's one call
for the caller:

```python
class RewardLog:
    def record(self, ...) -> str:
        # existing SQLite insert
        # NEW: also log human-readable win to reward.md
        from reward import log_clean, log_solved
        if all_gates_passed:
            log_clean(what=task.title, skill=skill)
```

This eliminates the dual-system problem. `reward.py` becomes a library
module (no one calls it directly anymore — `RewardLog.record()` handles it).

---

### Phase 5 — RL Event Log for Visibility

**Files:**
- `harness/_orchestrator_context.py` — add event logging
- `.techne/events/rl.jsonl` — new event log (gitignored)

**Change:**
After `post_run_evolve()` completes, write a summary line to
`.techne/events/rl.jsonl`:

```
{"ts":"2026-06-23T14:32:00","event":"grpo_proposals","task_count":12,"prompts_proposed":1,"skills_proposed":2}
{"ts":"2026-06-23T15:00:00","event":"advantage_computed","groups":3,"rewards":47,"pending_proposals":4}
```

This is the RL counterpart to the enforcement audit trail — machine-readable,
hash-chainable later if needed, human-grepable now.

---

### Phase 6 — TrajectoryQueue Integration

**Files:**
- `harness/trajectory_queue.py` (exists, 416 lines, tested)
- `harness/orchestrator_loop.py` — route tasks through queue

**Change:**
This is the most invasive change. `TrajectoryQueue` collects N task runs
before computing a batch advantage — it's designed for the batch RL path.
The normal pipeline sends tasks one at a time through `submit()`.

Low-risk approach: add a config flag `rl_batch_size: int = 1` on
`OrchestratorLoop`. When > 1, tasks go into the queue instead of
immediately triggering `post_run_evolve()`. When the queue reaches
`rl_batch_size`, flush it.

Default stays 1 (process tasks immediately). Advanced users can set > 1.

---

## Build Order Table

| Phase | Files | Tests | Risk | Depends on |
|-------|-------|-------|------|------------|
| P1 — Wire post_run_evolve | orchestrator_loop.py | test_orchestrator_driver.py | Low | — |
| P2 — Wire propose_skill_edits | _orchestrator_context.py | test_grpo_proposals.py | Low | P1 |
| P3 — RL Dashboard | hermes plugin, orchestrator_loop.py | manual verify | Low | P1 |
| P4 — Reward consolidation | reward_log.py, reward.py | test_reward.py | Medium | — |
| P5 — RL event log | _orchestrator_context.py, .gitignore | test_event_log.py | Low | P1 |
| P6 — TrajectoryQueue | orchestrator_loop.py, trajectory_queue.py | test_trajectory_queue.py | High | P1 |

Total: 6 phases, ~800 net new lines.

## Verification

After all phases:
```bash
cd ~/repos/techne
python3 -m pytest tests/test_grpo_proposals.py tests/test_group_scoring.py \
  tests/test_reward.py tests/test_trajectory_queue.py \
  tests/test_orchestrator_driver.py -v
```

Expected: all existing tests pass + new integration tests.

## What This Unlocks

Once the loop is closed:

- Every task completion triggers RL analysis automatically
- High-advantage prompt variants get proposed to retro_proposals.md
- High-advantage skill edits get proposed (P4)
- `/techne status` shows RL health
- `rl.jsonl` provides an audit trail for RL activity
- TrajectoryQueue available for batch-mode RL when needed

The system goes from "data in, nothing out" to "data in → proposals out"
on every task completion, with no manual steps.
