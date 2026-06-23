# Techne Hardening Retro — 2026-06-23

## Scorecard

| # | Domain | Commit | Key Items | New Tests |
|---|--------|--------|-----------|-----------|
| 1 | Pipeline Core | `cadcc87` | HALT vs FAILED distinction, phase timeout (300s), retry leak fix (RETRO→CONCLUDE), conductor edge cases (`run_number=0`, empty `test_output` guard), eval metrics regex robustness | 21 |
| 2 | Phase Mode System | `2214c91` | Empty title/desc crash fix, `task_title`+`diff_line_count` in override telemetry, configurable learning threshold via env var `TECHNE_ANALYSIS_THRESHOLD`, whitespace-only diff handling (`real_changed_lines`) | 8 |
| 3 | Task Lifecycle | `7df0b55` | Schema migration v1→v2 (notes column), `prune_orphaned_events()`, `release_stuck_tasks()`, `get_tasks_by_column()` with SQL injection guard | 8 |
| 4 | Phase Tooling | `44efdfe` | DB path fixes, exit codes, 6 script test files | 25 |
| 5 | Skill System | `fd31cec` | 6 missing router entries added, 4 broken `skill_path:` refs fixed, router validation test suite | 10 |
| 6 | Agent Prompts | `e9ed78b` | Verifier output format added, debugger duplicate YAML key fixed, 101 frontmatter/reference validation tests | 101 |
| 7 | Knowledge Graph | `f77014f` | `type`→`kind` bug fix (321 nodes went from "unknown" to real types), 11 new tests | 11 |
| 8 | GRPO/Learning | `3313aa5` | 7 gap tests: empty log, concurrent write, dashboard edge cases | 7 |
| 9 | Plugin Integration | `fb5d8f7` | Plugin YAML validation, command file format check | — |
| 10 | Docs & Workshop | `fb5d8f7` | README test count fix, domains doc char count fix | — |
| — | pre_tool_call hook | `0444b97` | Hermes-level write enforcement plugin | — |

## Bugs Found During Hardening

| Bug | Domain | Found in | Impact |
|-----|--------|----------|--------|
| `type`→`kind` node field — all 321 graph nodes misclassified as "unknown" | 7 | ``cmd_status()`` | Graph queries returned no useful data |
| `debugger.md` duplicate YAML `skills:` key — inline list + block list | 6 | Frontmatter audit | Second `skills:` silently ignored by YAML parser |
| `verifier.md` no Output Format section | 6 | Format audit | Agents had no template for VERIFY phase output |
| 4 `skill_path:` refs pointing to `skills/foo.md` that don't exist | 5 | Router audit | `diagnose`, `writing-skill`, `tdd`, `persona-brainstorm` would 404 on route |
| 6 skill folders with no router entry | 5 | Router audit | `retro-learn`, `discipline`, `orchestrator`, `react-vite`, `receptionist`, `kanban` were unrouteable |

## Metrics

- **8 commits** pushed to master
- **191+ new tests** across all domains
- **632 tests passing** across the full suite (70 pre-existing failures — writing_skill template deps, conductor mistakes.md path, etc.)
- **0 regressions** from hardening changes
- **~4.3k new code lines** (+ insertions across all domains)

## What Didn't Work

**Self-harden loop deadlock (recurring).** Driving the pipeline to harden the pipeline itself hits the HITL re-entry deadlock every time. After `unblock()` sets status to PENDING, `next_phase()` returns IMPLEMENT instead of the real next phase (e.g. REVIEW). Recovery requires reading `enforcer.status(tid)` directly instead of `next_phase()`. Mitigated in Domain 1 by pitfall #33 in the techne SKILL.md and the `techne-hardening-pattern.md` reference, but the root cause (HITL→PENDING reset) is still open.

**Subagent timeout / max_iterations.** Two subagents (Domain 2 edge case tests, Domain 3 initial dispatch) hit `max_iterations` before completing — leaving partial work that needed manual finishing. The subagent free-tier model (MiniMax-M2.7 via opencode-zen) is significantly slower than the parent session model, and 50 iterations isn't enough for multi-file edits with TDD. Mitigation: dispatch smaller, more focused tickets.

**Pipeline phases are slow for self-hardening.** Each phase requires a round-trip through the orchestrator loop: skip RECALL gate (write checkpoint), submit, wait for gate verification. For simple items (doc fixes, test additions) this overhead is disproportionate. `phase_mode=fast` helps but the gate checks still run.

## What Worked

**Subagent pattern for IMPLEMENT.** The delegate_task subagent produced correct changes with TDD for Domains 1, 2, 5, 6, 7, 8. The pattern (numbered items, exact files, test commands, context about codebase) is reliable.

**Concurrent baseline.** Running all test suites before and after each domain prevented regressions. The 52/52 driver, 80/88 classifier baselines caught one potential regression early.

**per-script validation tests.** The 101 agent prompt tests, 10 router validation tests, and 25 script tests now act as a safety net. These wouldn't have been caught by the existing test suites.

**pre_tool_call hook.** The most impactful addition — Hermes-level write enforcement that blocks agents from writing files without a pipeline task. This closes the gap between "the skill says use the pipeline" and "the system enforces the pipeline." Needs a session reset to activate.

## Action Items

1. **Fix HITL re-entry deadlock root cause.** The `unblock()` → `PENDING` → `next_phase()` wrong result cycle costs time every time we self-harden. The fix: after unblock, preserve the phase list from `enforcer.status(tid)` rather than resetting to start.
2. **Increase subagent max_iterations.** 50 isn't enough for complex tickets. Consider 75-100 for multi-file TDD work.
3. **Test the pre_tool_call hook live.** The plugin compiles and logic is verified in isolation, but needs a `/reset` in an active session to confirm the block triggers correctly.
4. **Project-level tasks.db detection.** The hook currently checks `~/repos/techne/.techne/memory/tasks.db`. For agents working on other projects (ms-ellen-project, inkforge), it should walk up from CWD.
5. **Self-harden: Domain 6 tests.** The 101 agent prompt tests take 0.07s — fast and valuable. Consider adding similar validation for `commands/` and `docs/` files.
