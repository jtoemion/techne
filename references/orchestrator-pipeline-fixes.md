# Orchestrator Pipeline Fixes — 2026-06-19

## 1. Full 10-Phase Pipeline

Pipeline shape: `RECALL → IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → EVAL → RETRO → CONCLUDE → DONE`

### Phase Descriptions
- **RECALL** — host runs `honcho_search`/`honcho_context` with task title + tags. Gate: length > 20 chars.
- **CONCLUDE** — host runs `honcho_conclude` with durable facts, returns conclusion IDs, and closes docs/context punch list. Gate: requires Honcho proof + DOCS closure + CONTEXT closure + git-state check. When CONTEXT is updated (not NOT_NEEDED), proof must include `sha:<commit-sha>` — gate rejects without it.

### Key Files
- `harness/pipeline_enforcer.py` — PHASES, TRANSITIONS, PHASE_DESCRIPTIONS, mark_complete()
- `harness/orchestrator_loop.py` — _submit_recall(), _submit_conclude(), next_phase()
- `harness/task_db.py` — phase_mode field (full/fast)

## 2. Phase Mode (full/fast)

Tasks can be created with `phase_mode="fast"` to skip RECALL and CONCLUDE phases. Useful for review-only tasks.

```python
db.create_task("review PR", phase_mode="fast")
```

## 3. SHA-Gate Review-Only Bypass

Review-only tasks (tagged `review-only`) skip the pass-indicator check in `sha_gate.py`. The `review_only` flag propagates from task tags through `verify_tests()` to `gate_test_output()`.

## 4. HITL Re-Entry Deadlock Fix

In `pipeline_enforcer.py` `can_enter()`:
```python
if task.status == "PENDING" and current != "RECALL":
    current = None
```
Without the RECALL exception, a task that completed RECALL but got BLOCKED would reset to None and lose the RECALL completion.

## 5. Honcho Recall Contract

`_submit_implement()` checks history for a RECALL phase event before allowing IMPLEMENT:
```python
history = self.db.get_task_history(task_id)
has_recall = any(e.action == "RECALL" for e in history)
if not has_recall:
    return LoopOutcome(action=LoopAction.RETRY, ...)
```

## 6. implementer_output.txt Path Collision

**Bug**: Fixed path `implementer_output.txt` meant task N+1 overwrote task N's diff.
**Fix**: `conductor.py` now writes to `implementer_output_{run_number}.txt`.
**Also**: Removed misleading "write to implementer_output.txt" from `agents/implementer.md` — the conductor writes it, not the agent.

## 7. RETRO Gate — Reject Checkbox Retros

`_submit_retro()` now enforces:
1. **Length >= 100 chars** — rejects one-liners like "Clean. Fix is minimal."
2. **Must reference at least one completed phase** — shows it actually looked at the run history

The model retries until it produces something substantive or hits max_steps and halts.

## 8. RETRO Context Injection

`_build_user_context()` now injects phase-specific context:
- **RECALL**: task title + tags + search instructions
- **RETRO**: mistakes.md content, per-skill recurrence counts (from `count_by_skill()`), routed skill's current content

Previously RETRO got only the generic phase description. Now it gets the same context the conductor builds.

## 9. CONCLUDE Hard Gate — `.techne/context` Must Be Committed

The CONCLUDE proof gate now **enforces git-state** rather than just checking text. If `.techne/context` has uncommitted changes, CONCLUDE RETRYs with a list of affected files.

**Implementation** (`orchestrator_loop._get_uncommitted_context_files()`):

```python
def _get_uncommitted_context_files(self) -> list[str]:
    def find_repo_root(start: Path) -> Path | None:
        cursor = start
        while cursor != cursor.parent:
            if (cursor / ".git").is_dir():
                return cursor
            cursor = cursor.parent
        return None

    # Walk up from CWD first (scripts always cd to project root)
    repo_root = find_repo_root(Path.cwd())
    if repo_root is None:
        repo_root = find_repo_root(Path(self.db.db_path).parent)
    if repo_root is None:
        return []  # non-git — skip gate

    # Full status + filter — glob misses nested paths
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", "."],
        capture_output=True, text=True, cwd=str(repo_root),
    )
    uncommitted = [l.split(None, 1)[1] for l in result.stdout.strip().split("\n") if l.strip()]
    return [f for f in uncommitted if ".techne/context" in f]
```

**Three bugs caught during implementation:**

- **Bug 1 — `l[3:]` slice is wrong**: Git porcelain is not fixed-width (staged=`M `, untracked=`??`). Use `l.split(None, 1)[1]` to get filename regardless of status chars.

- **Bug 2 — gitignore glob misses nested paths**: `git status --porcelain .gitignore/` only matches top-level. Subdirectory contexts (e.g., `stage/app/.techne/context/`) are invisible. Fix: `git status --porcelain -- .` over whole tree + substring filter.

- **Bug 3 — `db_path` defaults to skill memory db**: `TaskDB()` without a path resolves to `~/.hermes/skills/techne/memory/tasks.db`. That `.git` is the skills repo, not the project repo. Fix: walk up from CWD first.

## 10. `next_phase()` PENDING Short-Circuit Traps Loop After RECALL (Fixed 2026-06-19)

`orchestrator_loop.py:next_phase()` returned `"RECALL"` whenever `task.status == "PENDING"`, even after RECALL had completed. RECALL's `mark_complete()` only calls `_log_event` — it does NOT change `task.status` away from PENDING (unlike `complete_task()` which sets `IMPLEMENTED`). The result: after submitting RECALL, `next_phase()` kept returning RECALL forever, and the loop never advanced to IMPLEMENT.

**Symptom**: `loop.submit(tid, "RECALL", ...)` returns `RUN_PHASE - advancing to implement` but the next `loop.next_phase(tid)` call still returns `"RECALL"`.

**Fix** (`orchestrator_loop.py:next_phase()`):

```python
last = self.enforcer.get_phase(task_id)
if last is None and task and task.status == "PENDING":
    return "IMPLEMENT" if phase_mode == "fast" else "RECALL"
```

Only treat PENDING as "reset" if no phase has been completed for this run. Trust `enforcer.get_phase()` if it returns a non-None value, regardless of task status. Verified 2026-06-19 on BnB/Stage deploy-patch task `52bf17660b78`; all 49/49 existing orchestrator driver tests still pass.

## 11. `honcho_conclude` Does Not Return the Conclusion ID

The tool emits a confirmation message ("Conclusion saved for user: <text>") but does not give you a structured `conclusion_id` you can put in the CONCLUDE proof line. Workarounds:

- Confirm the write happened by `honcho_search`ing for a unique phrase from the conclusion text immediately after.
- Craft the HONCHO line manually with a description that includes the timestamp from the confirmation message ("written 2026-06-19 19:07:42").

The CONCLUDE gate accepts either format as long as the HONCHO line is present. Verified 2026-06-19 on deploy-patch task `52bf17660b78`.

## 12. SvelteKit Build-Time Env Guard Pattern (Added 2026-06-19)

For SvelteKit apps deploying to Netlify (or any environment where `$env/static/public` values get inlined at build time):

- Add a `validateBuildEnv()` function at the top of `vite.config.ts` that reads `process.env` directly.
- The guard fires only when `NETLIFY=true` OR `NODE_ENV=production` OR `CI=true` is set.
- Throws a multi-line, actionable error if any required var is missing — names the var, points at the deploy doc, shows the fix command.
- Pairs with a project `DEPLOY.md` that names the env vars and the exact `netlify env:set` command.

A reusable template is at `~/.hermes/skills/software-development/techne-orchestrator-pitfalls/templates/build-time-env-guard.md.template` and `templates/DEPLOY.md.template`. Verified 4-of-4 scenarios (build fails without env, succeeds with env, check 0/0, tests 428/428) on BnB/Stage deploy-patch task `52bf17660b78`.
