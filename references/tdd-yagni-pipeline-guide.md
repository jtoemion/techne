# TDD + YAGNI + Pipeline Guide

When the user asks for TDD and YAGNI within the pipeline, this is the combined discipline.

## The Pattern

```
1. Update test first (assert CORRECT behavior)  → test FAILS (RED)
2. Fix source with minimal change               → test PASSES (GREEN)
3. Drive fix through pipeline phases            → DONE
```

## Step-by-step

### 1. Update the test first (RED)
If the test asserts the BUGGY behavior (it was written against the broken code), update the assertion to the correct expected value first. Run the test to confirm it fails — proof that the test detects the bug.

### 2. Fix source with minimal change (YAGNI)
Touch only the lines directly causing the bug. Count the lines changed and report the count.

**YAGNI rules:**
- Exactly N lines changed. 4-line fix > 20-line refactor.
- No new files created unless the bug demands it.
- No refactoring of adjacent code — the bug fix is the only change.
- No adding tests for uncovered paths you noticed — that's a separate task.
- If you spot a second bug while fixing one, note it but do not fix in this task.

### 3. Drive through pipeline (IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → ...)
Submit each phase with the diff, test results (RED→GREEN), and line-count as evidence. The VERIFY phase runs all tests, not just the changed one.

## When both test and source encode the bug

Both the test and the source can be wrong simultaneously (the test was written against the broken contract). The fix sequence:

```
Test:   '/api/scribe/rewrite'   →  '/scribe/rewrite'     (fix assertion)
Source: '/api/scribe/rewrite'   →  '/scribe/rewrite'     (fix endpoint)
         ^^^^ both were wrong   ^^^^ both now correct
```

1. Update the test assertion → test FAILS (RED) ✓
2. Fix the source → test PASSES (GREEN) ✓
3. The test now guards against regression

## Pipeline phase submission

After the TDD cycle completes, submit to the pipeline:

```
IMPLEMENT   → diff + RED→GREEN evidence
CONTEXT_GUARD → scope audit (files changed, no .techne/context drift)
CRITIQUE    → risk assessment of the fix
REVIEW      → structural review, no HARD_FAIL
VERIFY      → all tests pass
...
```

## Exact RECALL gate format

The RECALL gate requires a `WORKSHOP_CONTEXT:` line at the start citing actual context files used.

**Correct format:**
```
WORKSHOP_CONTEXT: .techne/context/project_digest.md, .techne/context/context_packs/frontend.md
```

Without this line, the gate loops with `RECALL missing WORKSHOP_CONTEXT line`.

Full RECALL content should include:
1. `WORKSHOP_CONTEXT:` line with paths to the context files read
2. `FINDINGS:` — description of the bug, affected files, and bug report reference
3. `LAYER:` — which of the 5 layers this bug belongs to (UI / hooks / service / DAL / database)
4. `DONE_WHEN:` — concrete pass criteria (test assertions, test count)

## Exact CONCLUDE gate format

The CONCLUDE gate requires specific formatting for the CONTEXT line:

**Correct format:**
```
CONTEXT: .techne/context/context_hash.txt refreshed sha:a9cb51ec823999a213e5447e48c806e44021f718
```

**Common mistakes:**
- Omitting the `sha:` prefix → rejected with "no SHA found on that line"
- Not committing the context file change before submitting CONCLUDE → rejected because uncommitted file has no SHA
- Writing just the filename without the `refreshed sha:` format → rejected

Always commit the context file update first, then include the exact commit SHA in the CONCLUDE submission.

## Plain language in pipeline submissions

This user prefers **plain English explanations** over technical jargon in pipeline phase submissions. When submitting to any phase:
- Say what the bug means for the user in one sentence (e.g., "Rewrite button always returns 404")
- Then give the technical details
- Avoid gate error messages as user-facing communication — never just say "BLOCK_HITL" or "SHA gate rejected"

## Common pitfalls

- **Do not skip RED.** If you updated the test but didn't run it to confirm failure, you don't know the test detects the bug.
- **Do not skip existing tests.** After fixing, run the full test suite, not just the one changed test.
- **Do not refactor.** YAGNI means the fix is the only change. Resist the urge to clean up adjacent code.
- **Do not add coverage tests.** Adding tests for other uncovered paths creates scope creep. Note it as a follow-up task.

## YAGNI Discipline Checklist (attach to subagent prompts)

When dispatching IMPLEMENT via `delegate_task`, include this EXACT block in the `context` parameter to prevent scope creep:

```
YAGNI RULES:
- Change ONLY the minimum to fix the bug
- Do NOT add new endpoints unless the bug requires it
- Do NOT add new tests beyond what's needed for the fix
- Do NOT refactor nearby code that isn't part of the bug
- Do NOT add error handling beyond the minimal fix
- If a server endpoint doesn't exist, check if a simpler approach exists first
- Count the lines you changed before submitting — if >10 source lines, reconsider
```

Without this explicit list, subagents default to "build a complete solution" mode — they add extra server tests, refactor adjacent code, and create endpoints the bug didn't require. The user's mid-turn correction "YAGNI dont forget this" happened specifically because the subagent over-built.

**Real overbuild example — phantom import fix (2026-06-21):**

The `SettingsScreen.tsx` had an import `{ MODEL_REGISTRY } from 'shared'` that might not resolve at build time. A subagent was dispatched to fix it with TDD. It produced:

- Replaced the import with `DEFAULT_MODELS` hardcoded array
- Added `useState<readonly string[]>([])` for `modelRegistry`
- Added `useEffect` to set defaults on mount
- Used `modelRegistry` state in JSX with ternary fallback
- Added a 129-line test file with MSW server setup
- Total: ~90 lines changed

**What the YAGNI fix should have been (what was reverted to):**
- One line changed in the import statement
- The hardcoded model array with no state wrapper
- JSX iterates the const directly, no fallback needed (always non-empty)
- Total: **3 lines changed** (1 source + 2 comment cleanup)

**Lesson:** When a subagent returns a fix that adds state management, lifecycle hooks, and a full test suite for what should be a one-line import change, REVERT and redo. The signal is: "does this fix add more infrastructure than the bug had inherent complexity?" If yes, throw the subagent's work away and fix it yourself.

## Honcho discipline: even fast-mode tasks need an Honcho conclusion

When using `phase_mode=fast` (skips RECALL and CONCLUDE), the pipeline does not enforce Honcho checkpointing. But the **parent agent** still must call `honcho_conclude()` after the task reaches DONE, because:

- `phase_mode=fast` is a pipeline convenience, not a Honcho exemption
- The user's session spec says "honcho in every submit, recall and conclude" — applies to all tasks
- Without it, subsequent tasks lose the context of what was fixed

Pattern for fast-mode tasks:
```python
# Create task with fast mode
task = db.create_task(title='fix-trivial-thing', phase_mode='fast')
# Drive pipeline...
# After DONE, record checkpoint:
honcho_conclude(conclusion='Fixed X. Tests: N passed.', peer='user')
```

## Session discipline: P0-first workflow ordering

When triaging a batch of bugs from an audit, use this order:

1. **Fix all P0/HIGH bugs first** — data loss, crashes, guaranteed 404s. Drive each through the full pipeline (TDD + YAGNI). Do NOT critique or review the fixes yet — just fix.
2. **Then do critique and review** of all P0 fixes together — assess quality, find issues in the fixes themselves.
3. **Fix the critique findings** — rollback on optimistic updates, error state display, route convention audit, etc.
4. **Then move to P1/MEDIUM bugs**, same pipeline discipline.
5. **Finally P2/LOW bugs**, fastest first.

This ordering was established by user direction mid-session: "fix all P0 first, use the pipelines. after all p0 fixed then go critiques and review." Skipping ahead to critique before all P0s are done wastes the critique because the priority ordering may change as new bugs are discovered.

## Parallel batch dispatching

When fixing multiple independent bugs that don't share files, dispatch 2-3 delegate_tasks in parallel:

```python
# Task 1 and Task 2 are independent — run simultaneously
t1 = db.create_task(title='fix-bug-A', ...)
t2 = db.create_task(title='fix-bug-B', ...)
# Dispatch both delegate_tasks in one batch
```

Rules:
- Only dispatch in parallel when bugs are in **different files** and **different layers** (e.g. SERVICE + DAL)
- Never parallelize fixes that touch the same file — merge conflicts
- Never parallelize more than 3 at a time — rate limits and context budget
- After all return, commit them together in one batch commit
- Record one Honcho conclusion for the batch, not per-task

The user explicitly corrected: "you forgot the session spec. pipeline and honcho every submit." When techne is loaded:

1. `honcho_context(peer='user')` — FIRST action of each turn, before creating a task
2. Create task, drive phases through pipeline
3. `honcho_conclude(conclusion='...', peer='user')` — after every phase submit
4. For fast-mode tasks: still honcho_conclude after DONE (parent does it)

**YAGNI applies to delegate_task too.** When a subagent creates a fix, it may over-build — adding endpoint tests, refactoring adjacent code, or creating new infrastructure the bug didn't demand. Review the subagent's diff for scope creep before submitting to the pipeline. A fix that requires no new server endpoint should not create one. "YAGNI don't forget this" was a mid-turn user correction on this exact pattern.
- **REVIEW HITL — user expects test evidence.** When the pipeline blocks at REVIEW (BLOCK_HITL), the user's first question is "test need to be green." Before asking them to proceed, have the test output ready — run the full suite, confirm all green, and present the results inline. The unblock message should read: "All N tests pass across all workspaces. Here's the diff. Proceed?" rather than just a summary.
- **Commit context updates before CONCLUDE.** The CONCLUDE gate requires a SHA for context file updates. If your fix changes .techne/context/, commit it BEFORE submitting CONCLUDE. The SHA must be in the CONTEXT line of the CONCLUDE submission.
- **Commit gas — pipeline artifacts bloat commits.** Each pipeline run creates `.techne/tasks/<id>/refresh_context.json` and `.techne/memory/wikilinks.*`. These accumulate in commits. Add `.techne/tasks/`, `.techne/memory/`, `memory/`, and `techne/tasks.db` to `.gitignore` early in the project lifecycle to prevent commit bloat from pipeline-generated artifacts.

## Subagent timeout recovery

Subagents have a configurable timeout (default 600s, set via `delegation.task_timeout` in config.yaml). When a subagent times out:

1. **Check what was already done** — the subagent may have applied partial patches before timing out. `git diff` shows what's staged.
2. **Partial work assessment** — if the patches look correct and the rest of the fix is simple, finish it yourself. Submit the completed fix to the pipeline.
3. **Revert and redo** — if the subagent was stuck (e.g., trying to fix a non-existent bug as in the stale closure case), revert all changes with `git checkout -- <files>` and either re-dispatch with tighter constraints or mark the bug as a false positive.
4. **Prevention** — keep individual subagent tasks small enough to complete within timeout. A task that requires 50+ tool calls (reading many files, making many patches, running tests repeatedly) will likely time out. Break it into smaller tasks.

## Context hash tracking across batches

After each batch of fixes, update `.techne/context/context_hash.txt`:

```
commit: <new-commit-sha>
tests: <new-test-count> passed, <same-skipped>, <same-files>
generated: <timestamp>
N bugs fixed: <brief-description>
stale_if_commit_differs: true
```

The context hash is checked by the REFRESH_CONTEXT phase's `sha_gate`. Without an accurate test count, the gate can't verify that context is fresh after commits. Update this file after EVERY batch commit, before submitting to CONCLUDE/REFRESH_CONTEXT.

**Context:** ScribeToolbar called `apiClient.post('/api/scribe/rewrite')` but `apiClient` already prepends `/api` (API_BASE = '/api'). Result: URL `/api/api/scribe/rewrite` → 404.

**Files:** InkForge monorepo (`client/src/features/canvas/components/ScribeToolbar.tsx`)

### Step 1 — Update test first (RED)

The test file asserted the buggy URL pattern:
```
- expect(apiClient.post).toHaveBeenCalledWith('/api/scribe/rewrite', { ... })
+ expect(apiClient.post).toHaveBeenCalledWith('/scribe/rewrite', { ... })
```

Ran tests: **2/13 ScribeToolbar tests FAILED** — RED confirmed.

### Step 2 — Fix source with minimal change (YAGNI)

Changed exactly 2 lines in the source file:
```
- const result = await apiClient.post<{ content: string }>('/api/scribe/rewrite', { ... })
+ const result = await apiClient.post<{ content: string }>('/scribe/rewrite', { ... })
```

Same fix for the `/api/scribe/dialogue` endpoint. **4 lines total** (2 test + 2 source).

### Step 3 — Verify all tests (GREEN)

```
npm test → 41 files, 286 tests passed
```

### Step 4 — Drive through pipeline

All 10 phases: RECALL → IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW (HITL unblock) → VERIFY → EVAL → RETRO → CONCLUDE → REFRESH_CONTEXT → DONE

**Key pipeline transactions:**
- RECALL: submitted context with WORKSHOP_CONTEXT line pointing to context amortization files
- CONTEXT_GUARD: emitted CONCLUDE PUNCH LIST with DOCS/CONTEXT/HONCHO lines
- REVIEW: hit BLOCK_HITL — user confirmed "test need to be green" → showed test output → unblocked
- REFRESH_CONTEXT: required `.techne/config.yaml` (name/type/framework) in project root
- CONCLUDE: required SHA proof for context files — committed context_hash.txt update first
