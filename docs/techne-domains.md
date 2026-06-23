# Techne Domains — Architecture Parts

Techne is the pipeline orchestrator. It is not one thing — it is 10 domains
that connect through data (task DB), delegation (Hermes subagents), and
deterministic gates (Python). Each domain can be hardened independently.

```

  ┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
  │  2. Phase Mode  │     │  3. Task Life    │     │  4. Phase Tooling│
  │  System         │     │  Cycle (DB)      │     │  (scripts/)      │
  └───────┬─────────┘     └────────┬─────────┘     └────────┬─────────┘
          │                        │                        │
          ▼                        ▼                        ▼
  ┌───────────────────────────────────────────────────────────────────┐
  │                    1. Pipeline Core (harness/)                    │
  │  orchestral_loop.py ── conductor.py ── gates.py ── driver.py    │
  └───────────┬───────────────────────────────────────────┬───────────┘
              │                                           │
              ▼                                           ▼
  ┌──────────────────┐                          ┌──────────────────┐
  │  5. Skill System │                          │  6. Phase Agent  │
  │  (skills/)       │                          │  Prompts         │
  │  + router        │                          │  (agents/*.md)   │
  └──────────────────┘                          └──────────────────┘

  ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
  │  7. Knowledge    │     │  8. GRPO /       │     │  9. Plugin       │
  │  Graph           │     │  Learning Loop   │     │  Integration     │
  └──────────────────┘     └──────────────────┘     └──────────────────┘

  ┌───────────────────────────────────────────────────────────────────┐
  │                   10. Docs & Workshop                              │
  │  docs/ ── plans/ ── README ── retro/                              │
  └───────────────────────────────────────────────────────────────────┘

```

---

## Domain 1: Pipeline Core

**What it is.** The main loop — the thing that decides what phase runs next,
whether the phase passed or needs retry, and when the task is done. This is
the innermost heart of Techne.

**Key files.**

| File | Role |
|------|------|
| `harness/orchestrator_loop.py` | Main loop (1967 lines). Phase sequencing, retry gates, DONE/FAILED/HALT. |
| `harness/conductor.py` | Host-driven Pipeline class. Prompt assembly, `_read_skill_files()`, retro marker parsing, `_load_phase_skills()`. |
| `harness/gates.py` | Deterministic gate functions that validate phase output. |
| `harness/driver.py` | CLI entry point. Wires the loop to user input. Wires `summarize_incomplete()`. |

**What hardening means.**
- Per-phase retry budgets (no phase loops forever)
- Abort on unrecoverable errors (clear HALT vs INCOMPLETE distinction)
- Retry leak fix (CONCLUDE getting stuck behind failed RETRO)
- Phase timeout enforcement
- Conductor Pipeline class test coverage

**Tests.** `tests/test_orchestrator_driver.py` (52 tests), `tests/test_loop_hardening.py`

**Connects to.** Domain 2 (mode determines phase list), Domain 3 (reads/writes tasks),
Domain 4 (invokes phase scripts via subagent).

---

## Domain 2: Phase Mode System

**What it is.** The classifier that picks micro/fast/full/heavy mode based on
task keywords, diff size, and sensitivity. Controls how many phases a task
goes through.

**Key files.**

| File | Role |
|------|------|
| `harness/pipeline_enforcer.py` | `classify_phase_mode()`, `validate_mode_fit()`, `recommend_mode()`, `detect_sensitive_change()`. 1282 lines. |
| `harness/pipeline_enforcer.py` | `_MODE_COST_ESTIMATES`, `_log_mode_override()`, `analyze_override_patterns()`. |

**Modes.**

| Mode | Phases | Cost | Auto-select |
|------|--------|------|-------------|
| micro | IMPLEMENT → CONTEXT_GUARD → VERIFY → EVAL → DONE | 4 | ≤3 lines, 1 file, no logic |
| fast | 8 phases (skips RECALL/CONCLUDE/REFRESH_CONTEXT) | 7 | Reviews, minor fixes |
| full | All 11 phases | 11 | Default |
| heavy | Full + APPROVAL HITL | 12 | Auth/billing/migration/password keywords |

**What hardening means.**
- Auto-classification accuracy (reduce false heavy/fast picks)
- Edge cases: empty diffs, multi-file but tiny changes, config-only changes
- Override telemetry accuracy (what gets logged, when does learning loop fire)
- Mode mismatch → FAILED enforcement (no bypass)

**Tests.** `tests/test_mode_classifier.py` (80 tests)

**Connects to.** Domain 1 (mode determines which phases the loop runs),
Domain 3 (mode stored on task).

---

## Domain 3: Task Lifecycle

**What it is.** The data layer — tasks and events stored in SQLite. Every
pipeline action reads or writes through this. If the DB is corrupt, the
pipeline is blind.

**Key files.**

| File | Role |
|------|------|
| `harness/task_db.py` | `TaskDB` class. Task CRUD, event logging, status transitions. 612 lines. |
| `.techne/memory/tasks.db` | Live database (also at `techne/tasks.db`). |

**Schema.**

```
tasks (id, title, description, parent_id, discipline, status,
       assigned_agent, priority, tags, phase_mode, created_at,
       updated_at, attempt, max_attempts)

task_events (id, task_id, agent, action, summary, changed_files,
             diff_summary, findings, verdict, test_output_hash,
             mistakes_found, timestamp)
```

**What hardening means.**
- DB migration support (schema changes without data loss)
- Index optimization for high-volume queries
- Data integrity checks (orphaned events, stuck statuses)
- Concurrent access safety (WAL mode, connection pooling)
- Query performance at 1000+ tasks

**Tests.** Embedded in each phase's test suite via `TaskDB` instantiation.

**Connects to.** Every other domain — they all read/write tasks and events.

---

## Domain 4: Phase Tooling

**What it is.** One companion script per phase. Each script is a standalone
Python tool that does deterministic work so the LLM subagent focuses on
reasoning, not data assembly.

**Scripts.**

| Script | Phase | Job |
|--------|-------|-----|
| `scripts/recall_honcho.py` | RECALL | Fetch Honcho context, workshop files, lessons. |
| `scripts/diff_gate_checker.py` | IMPLEMENT, REVIEW | Validate diff format, SHA presence, changed file list. |
| `scripts/context_guard_check.py` | CONTEXT_GUARD | Validate punch list (DOCS/CONTEXT/HONCHO lines). |
| `scripts/critique_preflight.py` | CRITIQUE | Fetch task data, scan anti-patterns, YAGNI, TDD. |
| `scripts/pipeline_health.py` | VERIFY | Check test status, test count, SHA matches. |
| `scripts/session_reporter.py` | RETRO | Session summary, learnings extraction. |
| `scripts/mistakes_logger.py` | RETRO | Log mistakes to mistakes.md with phase attribution. |
| `scripts/conclude_proof_gen.py` | CONCLUDE | Generate Honcho proof block + close punch list. |
| `scripts/knowledge_graph.py` | EVAL | Query pipeline graph (321 nodes, 320 edges). |
| `scripts/project_graph_build.py` | REFRESH_CONTEXT | Build file architecture graph for project. |
| `scripts/task_gardener.py` | Universal | Clean stale tasks, fix stuck statuses. |
| `scripts/template_scaffolder.py` | Universal | Scaffold skills from templates. |

**What hardening means.**
- Each script independently testable (no harness import dependency)
- Clear output contract (stdout format the LLM can parse)
- Deterministic — same input always same output
- Error handling (DB missing, file missing, bad data)
- Companion scripts auto-discovered via `_load_phase_skills()` glob

**Tests.** Each script should have its own test under `tests/test_scripts/`.

**Connects to.** Domain 6 (scripts are referenced in agent prompts), Domain 1
(scripts are injected when phase subagent dispatches).

---

## Domain 5: Skill System

**What it is.** The skill files (SKILL.md) that define discipline for each
phase, plus the router that matches task descriptions to skills.

**Key files.**

| File | Role |
|------|------|
| `skills/skill-router.yaml` | Maps keywords → skill paths. Router for context injection. |
| `skills/<name>/SKILL.md` | Per-skill discipline (Rationalization Table, Red Flags, Next Steps). |
| `harness/conductor.py` | `_read_skill_files()` — loads always-loaded, stack-loaded, routed skills. |

**Skill structure (DISCIPLINE template).**

Each SKILL.md has: YAML frontmatter (name, description, triggers), Lead
block, Rationalization Table, Red Flags, Next Steps. ≤100 lines.

**What hardening means.**
- Routing accuracy — does `route("fix login bug")` return the right skill?
- Skill freshness — are any skills stale/misaligned with current pipeline?
- Skill+script pair enforcement — every script needs a paired skill
- Discipline enforcement — does the Rationalization Table actually stop
  the agent from skipping the phase?
- Fallback loading when no skill matches

**Tests.** `skills/skill-router.yaml` format validation in
`scripts/validate_command_files.py`.

**Connects to.** Domain 6 (skills loaded into agent prompts), Domain 1
(router invoked during `_read_skill_files`).

---

## Domain 6: Phase Agent Prompts

**What it is.** The system prompts (`agents/*.md`) that define each phase
subagent's role, execution steps, output format, and hard constraints.

**Agent files.**

| File | Agent | Phase |
|------|-------|-------|
| `agents/recaller.md` | RECALL | Search context, Honcho query. |
| `agents/implementer.md` | IMPLEMENT | Write code, TDD-first. |
| `agents/critique.md` | CRITIQUE | Predict bugs, find tradeoffs. |
| `agents/reviewer.md` | REVIEW | Security, compliance, code quality. |
| `agents/verifier.md` | VERIFY | Run tests, verify SHA. |
| `agents/retro.md` | RETRO | Extract lessons, write retro markers. |
| `agents/concluder.md` | CONCLUDE | Honcho proof, punch list close. |
| `agents/conductor.md` | Conductor | Orchestrator host prompt. |

**Each agent prompt has:**
1. YAML frontmatter (name, description, model, skills, tools)
2. Role description
3. What the agent looks for (categorized)
4. Execution steps (numbered)
5. Output format (with template)
6. Available tools (companion scripts)
7. Hard constraints

**What hardening means.**
- Output format consistency (does every agent produce parseable output?)
- Tool reference accuracy (scripts referenced by name actually exist)
- Prompt brevity (subagent token budget is limited)
- Constraint enforcement (do agents actually follow hard constraints?)
- Phase handoff clarity (does REVIEW output work as VERIFY input?)

**Connects to.** Domain 4 (scripts referenced in Available Tools section),
Domain 5 (skills listed in frontmatter), Domain 1 (loaded by `_read_agent_prompt()`).

---

## Domain 7: Knowledge Graph

**What it is.** Two graphs — pipeline patterns within Techne, and project
architecture per repo.

**Key files.**

| File | Role |
|------|------|
| `.techne/memory/wikilinks.json` | Existing graph: 321 nodes, 320 edges. |
| `.techne/memory/wikilinks.md` | Human-readable index. |
| `scripts/knowledge_graph.py` | Query tool: status, phases, mistakes, skill, file, search. |
| `scripts/project_graph_build.py` | Build file-architecture graph per project. |

**Pipeline graph sources.** wikilinks.json (phase links), tasks.db (outcomes),
mistakes.md (recurrence).

**Project graph.** File scan → classify by type/role → build import edges →
`.techne/context/project-graph.json`.

**What hardening means.**
- Node quality (do 321 nodes have useful types?)
- Edge accuracy (are edges real dependencies or noise?)
- Query completeness (can you answer "what phase fails most for auth tasks?")
- Project graph freshness (rebuild on significant changes)
- GRPO signal accuracy (does the graph feed useful reward signals?)

**Connects to.** Domain 8 (graph feeds GRPO), Domain 4 (scripts are injected
into EVAL and REFRESH_CONTEXT phases).

---

## Domain 8: GRPO / Learning Loop

**What it is.** The reward system — phase outcomes logged, override patterns
analyzed, classifier rules auto-adjusted at threshold.

**Key files.**

| File | Role |
|------|------|
| `.techne/memory/rewards.db` | GRPO reward scores. |
| `.techne/memory/mode_overrides.log` | Telemetry of mode overrides (auto-rotated). |
| `.techne/memory/classifier_insights.log` | Learning loop output (at 20-entry threshold). |
| `harness/reward_log.py` | Reward logging functions. |

**What hardening means.**
- Reward signal accuracy (do scores reflect actual outcome quality?)
- Learning loop effectiveness (do classifier adjustments improve accuracy?)
- Memory rotation (do old logs get archived or pruned?)
- Threshold tuning (is 20 the right number for analysis trigger?)
- Feedback loop safety (can bad rewards make the classifier worse?)

**Connects to.** Domain 2 (learning loop adjusts classifier), Domain 7 (graph
provides pattern data), Domain 4 (`knowledge_graph.py` queries rewards).

---

## Domain 9: Plugin Integration

**What it is.** How Techne connects to Hermes Agent — the slash command,
metaprompt validation, and revolver delegation fallback.

**Key files.**

| File | Role |
|------|------|
| `~/.hermes/plugins/techne/__init__.py` | Hermes plugin. `/techne` slash command. |
| `commands/techne.toml` | 1844-char hardened debug command prompt. |
| `scripts/validate_command_files.py` | Validator for command file format. |
| `~/.hermes/plugins/revolver/` | Delegation fallback plugin (6 hyphen commands). |

**Revolver commands.** `/revolver-next`, `/revolver-status`, `/revolver-graph`,
`/revolver-reset`, `/revolver-log`, `/revolver-tool`. Managed via cylinder pool
in `~/.hermes/revolver.yaml`.

**What hardening means.**
- `/techne` command robustness (does it survive bad input?)
- Revolver fallback reliability (does it actually recover from model failures?)
- Metaprompt validation (does plugin catch misconfigured prompts?)
- Cross-profile safety (plugin doesn't modify wrong Hermes profile)
- Command file format enforcement

**Connects to.** Domain 1 (plugin dispatches pipeline loop), Domain 6
(plugin validates agent prompts).

---

## Domain 10: Docs & Workshop

**What it is.** All documentation — plans, ADRs, retro logs, README, workshop
shells. The map and the memory.

**Key files.**

| File | Role |
|------|------|
| `README.md` | Repo overview, setup, usage. |
| `docs/adr/ADR-FORMAT.md` | Architecture Decision Record template. |
| `docs/host-integration-guide.md` | How to integrate Techne with a host. |
| `docs/plans/techne-worker-metaprompt.md` | 227-line master task document. |
| `docs/plans/techne-workshop-build-guide.md` | Workshop setup guide. |
| `docs/plans/techne-workshop-garage.md` | Workshop patterns. |
| `docs/retro/*.md` | Session retrospectives. |
| `docs/techne-domains.md` | This file. |

**What hardening means.**
- Docs completeness (does every domain have documentation?)
- Plan accuracy (do plans match current code?)
- ADR coverage (are architectural decisions recorded?)
- Retro quality (are lessons actionable?)
- README freshness (does setup section still work?)

**Connects to.** Every domain (docs should cover them all accurately).

---

## Domain Map — Quick Reference

| # | Domain | Dir / Prefix | Tests | Hardening Priority |
|---|--------|-------------|-------|-------------------|
| 1 | Pipeline Core | `harness/` | `test_orchestrator_driver.py` | 1 — highest impact |
| 2 | Phase Mode System | `harness/pipeline_enforcer.py` | `test_mode_classifier.py` | 2 |
| 3 | Task Lifecycle | `harness/task_db.py` | (implicit) | 3 — data integrity |
| 4 | Phase Tooling | `scripts/` | (per-script) | 4 |
| 5 | Skill System | `skills/` + `skill-router.yaml` | `validate_command_files.py` | 5 |
| 6 | Phase Agent Prompts | `agents/*.md` | (none) | 6 |
| 7 | Knowledge Graph | `scripts/knowledge_graph.py` | (none) | 7 |
| 8 | GRPO / Learning Loop | `.techne/memory/` | (none) | 8 |
| 9 | Plugin Integration | `~/.hermes/plugins/` | (none) | 9 |
| 10 | Docs & Workshop | `docs/`, `plans/`, README | (none) | 10 |

## Improvement Protocol — Per Domain

When hardening a domain:

1. Open this file to see what belongs to that domain
2. Load the companion skill if one exists (pip install discipline)
3. Read all files listed in that domain's table ✓
4. Write tests for the behavior you're hardening
5. If adding a new script, pair it with a skill + router entry
6. If removing something, update this file
7. Update retro/ with what changed and why
