# Orchestrator Pipeline Modification Patterns

## Adding a New Phase

When adding a new phase to the orchestrator pipeline, coordinate changes across these files:

### 1. `harness/pipeline_enforcer.py`
- Add phase to `PHASES` list (order matters — determines phase sequence)
- Add transitions in `TRANSITIONS` dict:
  - `None` and `"PENDING"` → first phase (usually `"RECALL"`)
  - Previous phase → new phase
  - New phase → next phase
- Add description to `PHASE_DESCRIPTIONS`
- Add handler in `mark_complete()`:
  ```python
  elif phase == "NEW_PHASE":
      self.db._log_event(
          task_id, agent, "NEW_PHASE", summary[:200],
          findings=findings, verdict=verdict,
      )
  ```

### 2. `harness/orchestrator_loop.py`
- Update `next_phase()` to return new phase as first phase (if it's the first phase)
- Add routing in `submit()`:
  ```python
  elif phase == "NEW_PHASE":
      return self._submit_new_phase(task_id, result)
  ```
- Add `_submit_new_phase()` handler that:
  1. Validates the result
  2. Calls `self.enforcer.mark_complete()`
  3. Returns `LoopOutcome` with next phase

### 3. `harness/task_db.py` (if new field needed)
- Add field to `Task` dataclass
- Add parameter to `create_task()`
- Update `INSERT` statement
- Update `_row_to_task()` with fallback for missing column:
  ```python
  field=row["field"] if "field" in row.keys() else "default"
  ```
- Update `CREATE TABLE` schema

### 4. `harness/sha_gate.py` / `harness/enforcement.py` (if gate changes needed)
- Add feature flag parameter (e.g., `review_only: bool = False`)
- Conditionally skip checks based on flag
- Pass flag through `verify_tests()` → `gate_test_output()`

### 5. `tests/test_orchestrator_driver.py`
- Update `FakeModel.__call__()` to handle new phase
- Update assertions to check new phase in `model.phases`
- Update history assertions for phase ordering

## Critical Pitfalls

### PENDING Status Resets Phase Tracking

**Problem:** When a task status is `PENDING`, `can_enter()` resets `current` to `None`, which breaks phase progression after the first phase is completed.

**Symptom:** `Pipeline violation: Cannot go from start to IMPLEMENT. Expected: RECALL`

**Fix:** In `can_enter()`, check if the phase is already completed before resetting:
```python
# Before (broken):
if task.status == "PENDING":
    current = None

# After (fixed):
if task.status == "PENDING" and current != "RECALL":
    current = None
```

**Why it happens:** After RECALL is submitted, the task status is still `PENDING` (status changes happen in `start_task()`, not `mark_complete()`). The enforcer thinks it's a fresh task and resets the phase tracker.

### Schema Migration for New Fields

**Problem:** Adding a new field to `Task` breaks existing databases that don't have the column.

**Fix:** Use conditional access in `_row_to_task()`:
```python
new_field=row["new_field"] if "new_field" in row.keys() else "default_value"
```

### Review-Only Tasks and SHA-Gate

**Problem:** Review-only tasks produce no real test output, so the SHA-gate's pass-indicator check fails.

**Fix:** 
1. Add `review_only` parameter to `gate_test_output()` and `verify_tests()`
2. Skip pass-indicator check when `review_only=True`
3. Detect review-only via task tags: `"review-only" in (task.tags or [])`

## Phase Mode Pattern

For tasks that don't need the full pipeline (e.g., review-only):

```python
task = db.create_task(
    "review PR",
    tags=["review-only"],
    phase_mode="fast",  # skips RECALL and CONCLUDE
)
```

The `next_phase()` method checks `task.phase_mode` and skips phases accordingly.
