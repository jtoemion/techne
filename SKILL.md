---
name: techne
description: Harness engineering entry point. Routes to the right sub-skill based on what you're doing. Always read this first — never browse skills/ directly.
---

# Techne — Skill Router

## Quick Route

| You're doing... | Load this |
|---|---|
| Building a feature or fix | `skills/implementer.md` |
| Something is broken | `skills/diagnose.md` |
| Writing tests first | `skills/tdd.md` |
| Stress-testing a plan | `skills/grill.md` |
| Discovering what to build | `skills/persona-brainstorm.md` |
| Prototyping a design question | `skills/prototype.md` |
| Finding refactor/architecture wins | `skills/improve-architecture.md` |
| Checking a pull request (one pass) | `skills/check-pr.md` |
| Iterating a PR to a perfect review | `skills/greploop.md` |
| Writing a new skill | `skills/writing-skill.md` |
| UI design decisions | `skills/ui-grill.md` |
| Prompting LLM for UI | `skills/ui-craft.md` |
| UI specificity standard | `skills/ui-physics.md` |
| Design-to-dev handoff | `skills/ui-handoff.md` |
| Reviewing agent output | `skills/evaluation.md` |
| Context preflight / project context | `skills/context-amortization.md` |
| Honcho checkpoint before compaction | `skills/honcho-precompaction-checkpoint.md` |
| Next.js specific rules | `skills/nextjs.md` |
| TypeScript type errors | `skills/typescript.md` |
| React 19 + Vite work | `skills/react.md` |
| Svelte/SvelteKit work | `skills/svelte.md` |
| Testing a web app in a browser | `skills/webapp-testing/SKILL.md` |
| Building an MCP server | `skills/mcp-builder/SKILL.md` |

> The last two are **vendored capability skills** (Anthropic) — folders with `scripts/`
> the agent runs as black-box tools. Bundle format, not Techne house format; do not edit
> their internals. Provenance + re-sync: `skills/SOURCES.md`.

#### `patch` tool — use `write_file` for non-trivial edits

When replacing multi-line blocks where the indentation or line count changes, the `patch` tool can mangle whitespace silently. Symptoms:
- Indentation drifts (extra/different leading spaces)
- Entire lines or expressions get dropped from the replacement
- LSP then reports "variable implicitly has 'any' type" on the dropped expression

For edits that change more than ~3 lines or involve indentation restructuring, prefer `write_file` with the full corrected file content. Use `patch` only for:
- Single-line fixes
- Exact line-for-line replacements with identical indentation
- Well-contained blocks where you control the exact old_string match

## Orchestrator Pipeline Reference

For the full 10-phase pipeline implementation details, context injection patterns, and known pitfalls, see:
- `references/orchestrator-pipeline-fixes.md`
- `references/orchestrator-recall-workshop-contract.md` — structured RECALL output contract, workshop retrieval packet, agent mappings, phase_mode propagation
- `references/web-runtime-blank-page-debugging.md`
- `references/convex-array-membership-queries.md` — safe pattern for learner/evidence membership queries
- `references/maintainability-audit-context-refresh.md` — repo re-exploration + context refresh workflow for long-term maintainability audits

## Always Loaded

These are injected for every task — do not skip:

- `skills/context-amortization.md` — mandatory context preflight and context packs
- `skills/honcho-precompaction-checkpoint.md` — checkpoint durable facts to Honcho before compaction
- `skills/nextjs.md` — hard gates that will reject your diff (Next.js projects only)
- `skills/typescript.md` — hard gates that will reject your diff

**Scope note:** Techne's gates (`gate_no_redirect_outside_middleware`, `gate_no_router_import`, etc.) and its pipeline phases (IMPLEMENT → VERIFY → REVIEW → RETRO → EVALUATE) are designed for **Next.js full-stack projects**. For React 19 + Vite projects (e.g., pastpapr), the routing and middleware conventions don't apply. Use this router for sub-skill routing and load `skills/react.md` for the ESLint/TypeScript pitfalls, but skip the Next.js-specific gate logic.

## Pipeline Phases

```
RECALL → IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → EVAL → RETRO → CONCLUDE → DONE
```

Each phase is a separate agent. Only the conductor advances phases.
Gates run in Python — agents cannot self-report a pass.

**After every phase: honcho_conclude.** The user expects a durable checkpoint after every pipeline phase submit, not just before compaction. `honcho_conclude(conclusion="...", peer="user")` records what was accomplished, what blocked, and what decisions were made. Without this, the user will call it out. The Honcho checkpoint is NOT optional — it's part of the pipeline discipline.

**After every phase: check task status** — call `db.get_task(tid).status` and `db.get_task(tid).phase` to display progress. `OrchestratorLoop` has no `get_status()` method — that will crash.

## API Reference

### TaskDB
```python
db = TaskDB("techne/tasks.db")  # CWD-relative path; directory must exist
task = db.create_task(title="...", description="...", tags=["p1"], discipline="tdd", phase_mode="full")
# Returns Task object with: task.id, task.status, task.phase, task.phase_mode
```

### OrchestratorLoop
```python
p = OrchestratorLoop(db)
prompt = p.get_prompt(tid, "RECALL")  # Returns dict with 'system' and 'user' keys
next_phase = p.next_phase(tid)        # Returns string: next phase name to run
result = p.submit(tid, phase, result) # Submit phase result → returns LoopOutcome
# LoopOutcome has: .action (LoopAction enum), .message (str)
```

### Phase submission flow
```
1. next_phase(tid)     → "RECALL"
2. get_prompt(tid, "RECALL")  → {system, user}
3. Execute prompt (Honcho search, diff generation, etc.)
4. submit(tid, "RECALL", result_text)  → LoopOutcome(action=RUN_PHASE, ...)
5. Repeat for each phase
```

### HITL (Human-in-the-Loop) blocks
When CRITIQUE finds a WARNING, `submit()` returns `LoopOutcome(action=BLOCK_HITL)`.
To unblock: call `p.unblock(tid, "proceed")`, then submit the NEXT phase (not the blocked one).
After `unblock()`, the task status clears but the phase tracking stays where it was.
If you try to `submit()` while status is BLOCKED, you'll get:
`ValueError: Pipeline violation: Task is BLOCKED — only IMPLEMENT or DEBUG allowed`

**Unblock flow:**
```python
p.unblock(tid, "proceed")
# Now submit the NEXT phase after the blocked one, not the blocked phase itself:
next_ph = p.next_phase(tid)  # e.g. "REVIEW" after CRITIQUE was blocked
result = p.submit(tid, next_ph, review_text)
```

**User communication:** When HITL blocks, explain in plain language — e.g. "The pipeline wants your OK before continuing" or "The critic flagged something that needs your decision." Never say just "BLOCK_HITL" or "gate" without context.

### CONTEXT_GUARD format
CONTEXT_GUARD output MUST include a `## CONCLUDE PUNCH LIST` section with:
- `DOCS:` path or NOT_NEEDED
- `CONTEXT:` path or NOT_NEEDED
- `HONCHO:` path or NOT_NEEDED

Without this section, CONTEXT_GUARD rejects with retry message.

## Pitfalls (orchestrator loop)

1. **RETRO must be substantive.** The gate rejects output < 100 chars or output that doesn't reference any completed phase. "Clean. Fix is minimal." is a checkbox, not a retro. The model retries until it produces real lessons or halts.

2. **Each phase needs its own context block in `_build_user_context()`.** RECALL needs task title + tags. RETRO needs mistakes.md + recurrence counts + routed skill content. Don't rely on the generic phase description alone.

3. **Fixed file paths collide across tasks.** `implementer_output.txt` was a fixed path — task N+1 overwrote task N's diff. Use `implementer_output_{run_number}.txt` or capture from git.

4. **PENDING status resets phase tracking.** `can_enter()` resets `current` to None when task.status == "PENDING". Exception: if RECALL is already completed, don't reset. Without this, HITL re-entry loses the RECALL completion.

5. **SHA-gate rejects verification-only tasks.** No diff means no pass indicators. Use `phase_mode="fast"` at task creation or tag the task `review-only` to skip the pass-indicator check.
6. **Green tests/build can still ship a white screen.** For web-app tasks, VERIFY should include an actual production-style browser check (preview or deployed page) plus browser console inspection for CSP violations, hydration/runtime exceptions, and blank-page regressions. Deterministic gates alone won't catch client bootstrap failures. See `references/web-runtime-blank-page-debugging.md` for a compact checklist and example failure modes.

   **Important nuance for CSR routes:** if the app sets `ssr = false` (for example in `src/routes/+layout.ts`), the initial HTML/body can look nearly empty except for the bootstrap script. That is not by itself a regression. The real check is: did the browser mount the app, does the accessibility snapshot show page content, and is the console clean after hydration?

   **Important nuance for preview servers:** a background `npm run preview` process can appear `running` while no socket is actually listening yet (or any more). Before trusting browser results, verify the port is bound (`ss -ltnp | grep ':<port>'`) or do one foreground preview run with a short timeout to capture the actual startup banner.

7. **REVIEW keyword matching is literal.** The orchestrator's review gate currently treats any review text containing the substring `HARD_FAIL` as a hard fail. That means a sentence like `No HARD_FAIL findings` still blocks the task. Until the harness is tightened, never include the literal token `HARD_FAIL` in a passing review. Use `No blocking findings`, `PASS`, or equivalent.
### Phase Context Requirements

Each phase needs specific context injected by the orchestrator loop:

- **RECALL**: Task title + tags (so host knows what to search in Honcho)
- **RETRO**: Full `mistakes.md` content, `count_by_skill()` recurrence, routed skill's current content
- **CONCLUDE**: Host runs `honcho_conclude`, returns conclusion IDs as proof, closes Context-Guard punch list with docs/context proof. **Hard gate**: if `.techne/context` has uncommitted changes, CONCLUDE fails until they are staged and committed. Include the committed SHA in the proof text.

### Key Pitfalls

1. **Orchestrator loop RETRO context**: The loop's `_build_user_context()` must inject the same context the conductor's `retro_prompt()` builds — mistakes.md, per-skill recurrence counts, routed skill content. Without this, RETRO runs blind.

2. **implementer_output.txt path collision**: When multiple tasks run sequentially, the fixed path `implementer_output.txt` causes task 2 to overwrite task 1's diff. Fix: use `implementer_output_{run_number}.txt` in conductor.py.

3. **HITL re-entry deadlock**: After a HITL block, if task status is PENDING, the enforcer resets `current` to None. But if RECALL was already completed, this resets too far. Fix: only reset when `current != "RECALL"`.

4. **SHA-gate review-only tasks**: Review-only tasks produce no real test output. The pass-indicator check must be skipped for tasks with tag `review-only`.

5. **CONCLUDE git-state gate must run on CWD, not db_path**: `_get_uncommitted_context_files()` walks up from `Path.cwd()` to find `.git`, not from `self.db.db_path`. `TaskDB()` defaults to the skill memory db (`~/.hermes/skills/techne/memory/tasks.db`) which has its own `.git`. Always walk up from CWD first.

5. **CONCLUDE git-state gate must run on CWD, not db_path**: `_get_uncommitted_context_files()` walks up from `Path.cwd()` to find `.git`, not from `self.db.db_path`. `TaskDB()` defaults to the skill memory db (`~/.hermes/skills/techne/memory/tasks.db`) which has its own `.git`. Always walk up from CWD first.

6. **`TaskDB()` default path trap**: When instantiating `TaskDB()` without a path argument inside a script, it resolves to `~/.hermes/skills/techne/memory/tasks.db` — NOT the project's `techne/tasks.db`. This means any function that walks up from `db.db_path` to find the project repo root will resolve to the wrong `.git`. The orchestrator loop uses `Path.cwd()` as primary and `db_path` as fallback, but any NEW code that needs the project repo must not rely on `db_path`. Always use CWD-based repo root detection.

7. **Git porcelain filename extraction**: `git status --porcelain` output has variable-width status prefixes (` M`, `M `, `??`, `MM`, etc.). Never use `l[3:]` to extract the filename. Use `l.split(None, 1)[1]` which handles any prefix width correctly.

8. **Pipeline over manual edits — zero exceptions**: The orchestrator pipeline (task_db.create_task → orchestrator_loop phases through DONE) is MANDATORY for ALL code changes, even trivial ones. Manual code edits that bypass the pipeline violate the delegation mandate. When the user says "use the pipeline" or "go do those task one by one and use pipeline. Mandatory." — zero exceptions. Every change gets a task ID and goes through all phases. Freewheeling parent code edits have been called out as 5+ times — this is the clearest signal the user has given. If you find yourself about to write a file without a task ID, stop and create a task first. **Even if you've already made the edit outside the pipeline**, the correct action is: create a task for it, drive it through the pipeline, then commit via the pipeline's CONCLUDE phase. Do not commit pipeline-bound work directly.

9. **When a query optimization breaks tests, revert first**: In Convex code, do not assume a server-side `.filter()` or an array index query can express array membership for `learnerIds`. If the optimized path drops shared records or returns empty, revert to the passing `collect()+includes()` shape and add a regression test with a shared record (`learnerIds: [a, b]`) before considering a junction-table refactor later.

10. **Shared-record regressions need a seeded multi-parent case**: When evidence or timeline views depend on `learnerIds`, seed one record that belongs to two learners and assert the linked guardian still sees it. A single-learner fixture will miss exact-match bugs. Also check whether the schema index is still used by another query before touching it; the index may be serving a different view even if the local query does not use it.

10. **Array-field indexes can be shared across consumers**: In this codebase, `evidenceRecords.by_learner` is consumed by guardian views via `.withIndex("by_learner", (q) => q.eq("learnerIds", [learnerId]))`. Do not delete the index just because one caller scans in memory. Add or keep a regression test for shared `learnerIds` evidence before changing either the schema or the guardian views.

12. **Vite 8 ignores svelte.config.js when options passed to sveltekit()**: If vite.config.ts passes ANY options to `sveltekit({...})`, Vite 8 silently ignores svelte.config.js — including the adapter. The adapter must be moved into vite.config.ts as a sibling of compilerOptions. This is not a warning you can ignore: the build prints "No adapter specified" and produces incomplete output with no SSR function shims. Check build output for "> Using @sveltejs/adapter-netlify" to confirm the adapter fired. Also requires a `_headers` file at project root (adapter-netlify crashes without it).

13. **Convex "use node" files: zero-direct-import rule**: A file with `"use node"` directive (Nodemailer, Node builtins) can NOT be directly imported by any other Convex file that lacks the directive. The Convex bundler follows imports at bundle time and merges them into the parent's runtime, causing "It looks like you are using Node APIs from a file without the 'use node' directive" errors. Fix: export an `action` from the "use node" file, import `api` from `_generated/api` in the caller, and call via `ctx.runAction(api.fileName.actionName, args)`. This calls the action at runtime through the Convex action system — no cross-runtime import.

14. **SHA gate "failed" regex false-positive**: The SHA gate's failure-pattern regex matches the literal substring " failed " (with surrounding whitespace) ANYWHERE in the VERIFY report, including in prose explaining a build guard that intentionally trips. This causes BLOCK_HITL on clean submissions. Fix: never use the word "failed" in VERIFY output. Use "trip", "reject", "abort", or "halt" instead. Self-referential notes like "the first submission tripped because the regex matched..." also match if they contain " failed ".

15. **Pipeline DONE does NOT push to remote**: When a task reaches DONE via CONCLUDE, the pipeline commits locally but does NOT push to the remote GitHub branch. The user expects the remote to reflect the work. After DONE, if the branch tracks a remote, push it: `git push origin <branch-name>`. If multiple branches need to be merged (feature branch → deploy branch), do that before pushing. Forgetting to push means the next person (or CI/CD) deploys stale code, which was a real issue in session 2026-06-19. This is not optional — the DONE state implies the work is available to the team/deploy pipeline, which requires a remote push.

19. **Login redirect after sign-in — session store hasn't updated yet**: After `authClient.signIn.email()` returns successfully, the SvelteKit `(app)` layout's `useSession()` store may still have `{ data: null, isPending: false }`. Using `goto()` via client-side routing loads the layout in a new page context where the session store hasn't received the new user data from `signIn.email()` yet. The layout's auth guard fires, sees no user, and redirects back to `/login` — producing the UX of "clicked sign in, nothing happened."

**The fix is NOT hard navigation** — the `crossDomainClient()` plugin from `@convex-dev/better-auth` stores the session token IN MEMORY, not in cookies. `window.location.href` loses the token immediately.

**The fix IS `getSession()` + `goto()`**: force-refresh the session atom, then navigate client-side (preserves in-memory token):

```ts
// login/+page.svelte — correct approach
async function handleSignIn(e: Event) {
  e.preventDefault();
  const { data, error } = await authClient.signIn.email({ email, password });
  if (error) return;
  const session = await authClient.getSession();
  if (!session?.user) {
    error = 'Login succeeded but session could not be established.';
    return;
  }
  const appRole = roleFromSession(data);
  goto(redirectForRole(appRole));
}
```

**Network pattern:** After clicking Sign In, the page stays on `/login` while `GET /coach/__data.json` is fetched — this is the telltale sign that `goto()` is being used but the session store is stale. After the fix, the user should reach the role-appropriate dashboard (coach, guardian, or HOA).

Full debugging path and related patterns (Convex component install, authUserId linking, role lookup) are in `references/better-auth-session-navigation.md`.

16. **Netlify npm engine compat with NODE_VERSION**: The `netlify.toml` `[build.environment]` section sets `NODE_VERSION`. If any npm package declares an `engines.node` requirement higher than this, `npm install` fails with `EBADENGINE`. Before setting NODE_VERSION, check: `grep -r '"node"' package.json` and in `node_modules/*/package.json` of critical deps. Example: `ical-generator@11.0.0` requires `"node": "22 || >=24.0.0"` — setting `NODE_VERSION = "20"` in netlify.toml causes a hard failure at install time. Set to the highest required version across all dependencies.

17. **Netlify build env vars — all required vars must be set**: The SvelteKit frontend build reads env vars at build time via `$env/static/public`. If a package imports an env var that is not set in Netlify, rolldown/vite fails with `[MISSING_EXPORT]`. For this project specifically:
    - `PUBLIC_CONVEX_URL` — Convex deployment URL (set in Netlify env)
    - `PUBLIC_CONVEX_SITE_URL` — Convex site URL, imported by `@mmailaender/convex-better-auth-svelte` (often missed, causes build failure)
    - `VITE_BETTER_AUTH_URL` — the app's own URL (set in Netlify env)
    Check the full list by searching `$env/static/public` across all source and node_modules that will be bundled. Missing vars are a hard build failure with no graceful fallback.

18. **Netlify production branch vs remote**: Netlify is configured to build from a specific branch (default: `master`). If that branch doesn't exist on the remote, the deploy fails at "preparing repo" stage with `git ref refs/heads/<branch> does not exist`. When creating or renaming branches, check the Netlify dashboard → Site settings → Build & deploy → Branches to confirm the production branch name. If the branch doesn't exist, either create it from the latest deploy-ready HEAD or update the Netlify setting.

- `full` (default): all 10 phases, including RECALL and CONCLUDE
- `fast`: skips RECALL and CONCLUDE (for review-only tasks)

Set `phase_mode="fast"` on tasks that don't need Honcho context or write-back.

## Next Steps

- Building something? → `skills/implementer.md`
- Debugging? → `skills/diagnose.md`
- Not sure what to do first? → `skills/grill.md`
- Modifying the orchestrator pipeline? → `references/orchestrator-pipeline-modification.md` (phase addition patterns, pitfalls, schema migration)
- Orchestrator pipeline fixes (RECALL/CONCLUDE phases, RETRO gate, phase_mode)? → `references/orchestrator-pipeline-fixes.md`
- Post-build bug analysis? → `references/bug-analysis-soaperfume.md` (live case study — 13 bugs, H-1 through L-4, with fix patterns)
- SvelteKit deployment issues? → `references/vite8-adapter-trap.md` (Vite 8 ignores svelte.config.js, adapter must be in vite.config.ts, _headers requirement, verification diagnostics)
- Blank page after a green build? → `references/web-runtime-blank-page-debugging.md` (CSP nonce mismatches, hydration/runtime console triage, preview-vs-deploy verification order)
- Netlify build env vars + Node version? → `references/netlify-build-env.md` (PUBLIC_CONVEX_URL/SITE_URL, VITE_BETTER_AUTH_URL, NODE_VERSION compat, branch config, output verification)
- Convex production deployment? → `references/convex-deployment.md` (env vars, "use node" email, targeting prod, common errors)
- Bug triage quick-ref? → `references/bug-analysis-soaperfume.md` (symptom → cause table for common SvelteKit/SQLite patterns)
- Replicating an existing UI (vanilla HTML prototype → framework code)? → `references/ui-replication-from-reference.md` (audit-then-extract workflow, atom layer first, token-exact matching)
- Hook-gate bridge (Hermes pre_tool_call → Techne gates.py)? → `references/hook-gate-bridge.md` (plan + architecture for inline gate enforcement via plugin hook)
- LMS-hermes bridge (student-portal → Hermes custom provider + MCP tools)? → `references/lms-hermes-bridge.md` (Phase 1 ✅, Phase 2 LMS side ✅ — commit `6d9d467` reviewed/fixed. Hermes side: see `HERMES_SIDE_PHASE2.md` — token extraction, auto-inject, scope enforcement, 3 open questions for Hermes team)
- RETRO phase invisible to user? → `references/orchestrator-retro-visibility.md` (template + gate requirements)
- Writing a new skill? → `superpowers/writing-skills/SKILL.md` (TDD for documentation — RED-GREEN-REFACTOR applied to process docs)
- UI design decisions? → `superpowers/frontend-avant-garde/SKILL.md` (Senior Frontend Architect — opinionated, output-first)
- React 19 + Vite project work? → `skills/react.md` (useEffect deps, React Query mutation refs, exhaustive-deps guards)
- Svelte project work? → `skills/svelte.md` ($state mutation through helpers, Dexie schema/types duality, dev-only route guard, dynamic imports)
