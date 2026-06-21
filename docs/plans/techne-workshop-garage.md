# TECHNE Workshop Garage — Vision, Inventory & Build Plan

## 1. Executive Summary

Techne is a **harness-engineering skill** — a pipeline-driven development assistant
that runs inside the agent's session and enforces a 10-phase discipline
(RECALL → IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → EVAL →
RETRO → CONCLUDE → DONE). It already has gates, phase routing, workshop context
retrieval, and a basic reward system.

The **Workshop Garage** is the vision of turning Techne from a pipeline into a
**self-improving engineering workshop** — a persistent, project-attached
workspace with:

- **Tools** — indexed context docs, scriptable retrieval, wiki links
- **Protocols** — mandatory pipeline phases, gate-enforced quality, phase-mode
  flexibility
- **Workflow** — RECALL → IMPLEMENT → VERIFY → RETRO → CONCLUDE, with HITL
  blocks and human-gated evolution
- **Recallable Memory** — Honcho durable facts + workshop memory + mistakes
  ledger + reward ledger, surfaced at RECALL time
- **Auto-update Memory** — context docs that refresh after each run, wiki links
  that grow with the codebase
- **RL with GRPO** — reinforcement learning via reward signals driving prompt
  evolution, gate evolution, and skill improvement

---

## 2. Current State Inventory

### 2.1 Pipeline Architecture

| Component | File | Status |
|-----------|------|--------|
| 10-phase pipeline | `harness/orchestrator_loop.py` | ✅ Complete |
| Phase dispatch | `orchestrator_loop.next_phase()` | ✅ PENDING → RECALL/IMPLEMENT → ... → DONE |
| Phase enforcement | `harness/pipeline_enforcer.py` | ✅ PHASES, TRANSITIONS, `can_enter()` |
| Host-driven conductor | `harness/conductor.py` | ✅ Assembles prompts, runs gates |
| Driver entry point | `harness/driver.run_plan()` | ✅ Multi-task, on_submit hook |
| Phase-mode (full/fast) | `task_db.py`, `orchestrator_loop.py` | ✅ Full → RECALL+CONCLUDE; Fast → skip |
| HITL recovery | `pipeline_enforcer.py` | ✅ BLOCK_HITL → unblock(proceed/debug) |

### 2.2 Agent System

| Agent | File | Phase | Status |
|-------|------|-------|--------|
| Recaller | `agents/recaller.md` | RECALL | ✅ New — structured output contract |
| Implementer | `agents/implementer.md` | IMPLEMENT | ✅ Returns raw unified diff |
| Context Guard | `agents/context-guard.md` | CONTEXT_GUARD | ✅ Punch list + docs/context/Honcho |
| Critique | `agents/critique.md` | CRITIQUE | ✅ Risk levels, FOLLOW_UP_TASKS |
| Reviewer | `agents/reviewer.md` | REVIEW | ✅ PASS/HARD_FAIL/SOFT_FAIL |
| Verifier | `agents/verifier.md` | VERIFY | ✅ Runs tests, captures output |
| Debugger | `agents/debugger.md` | DEBUG | ✅ 6-phase diagnostic |
| Concluder | `agents/concluder.md` | CONCLUDE | ✅ New — Honcho write-back + proof |
| Retro | `agents/retro.md` | RETRO | ✅ 7-question structured retro |
| Conductor | `agents/conductor.md` | (meta) | ✅ Pipeline state machine |

### 2.3 Gates & Enforcement

| Gate | Location | What it checks |
|------|----------|----------------|
| Diff gate | `harness/gates.py` | IMPLEMENT output must be valid unified diff |
| SHA gate | `harness/sha_gate.py` | VERIFY output must have pass indicators |
| Context guard | `harness/pipeline_enforcer.py` | Scope audit + docs/context/Honcho punch list |
| Critique gate | `harness/orchestrator_loop.py` | Risk level + FOLLOW_UP_TASK parsing |
| Review gate | `harness/pipeline_enforcer.py` | HARD_FAIL substring blocks pipeline |
| EVAL gate | `harness/orchestrator_loop.py` | Deterministic 100-point score |
| RETRO gate | `harness/orchestrator_loop.py` | ≥100 chars + phase references |
| CONCLUDE gate | `harness/orchestrator_loop.py` | Honcho proof + docs/context closure + SHA |
| Review-only bypass | `harness/sha_gate.py` | `review_only=True` skips pass-indicator check |
| RECALL contract | `harness/orchestrator_loop.py` | HONCHO_CONTEXT + WORKSHOP_CONTEXT required |

### 2.4 Workshop Shell

| Component | Path | Status |
|-----------|------|--------|
| Config | `.techne/config.yaml` | ✅ project_name, context_glob, generated_dir |
| Context docs | `.techne/context/*.CONTEXT.md` | ✅ 7 files (root, harness, memory, scripts, etc.) |
| Context index script | `.techne/scripts/context_index.py` | ✅ Builds `.techne/generated/context_index.json` |
| Context search script | `.techne/scripts/context_search.py` | ✅ Graph-aware retrieval with scoring |
| Refresh script | `.techne/scripts/refresh_generated_docs.py` | ✅ Regenerates stale generated docs |
| Workshop helpers | `harness/workshop.py` | ✅ Path discovery, index building, scoring |
| Wikilink module | `harness/wikilink.py` | ✅ Wiki link parsing and graph building |
| Workshop retrieval in RECALL | `orchestrator_loop._build_workshop_recall_lines()` | ✅ Calls context_search.py |
| Workshop foundation tests | `tests/test_workshop_foundation.py` | ✅ 5 tests pass |

### 2.5 RL / Reward System

| Component | File | Status |
|-----------|------|--------|
| Reward log | `harness/reward_log.py` | ✅ Records per-task rewards (SQLite) |
| Reward ledger | `harness/reward.py` | ✅ CLEAN/SOLVED wins per skill |
| EVAL scorer | `harness/evaluator.py` | ✅ 100-point score across 5 dimensions |
| Prompt evolution | `harness/prompt_evolution.py` | ✅ Propose/validate/ratify firewall |
| Gate evolution | `harness/gate_evolution.py` | ✅ Pattern-based gate proposals |
| Post-run evolution | `orchestrator_loop.post_run_evolve()` | ✅ Stages prompt + gate proposals |
| Mistakes tracker | `harness/mistakes.py` | ✅ Structured mistake logging |
| Checkpoint | `harness/checkpoint.py` | ✅ Pipeline run checkpointing |

### 2.6 Honcho Integration

| Component | File | Status |
|-----------|------|--------|
| honcho_search in RECALL | (prompt-level) | ✅ RECALL agent instructed to search Honcho |
| honcho_conclude in CONCLUDE | (output contract) | ✅ Required proof line in conclude output |
| Structured output | `agents/recaller.md` | ✅ HONCHO_CONTEXT + WORKSHOP_CONTEXT + LESSONS + FOCUS |
| Precompaction checkpoint | `skills/honcho-precompaction-checkpoint.md` | ✅ Skill for durable checkpointing |
| On-submit hook | `driver.run_plan(on_submit=...)` | ✅ Honcho checkpoint after every phase |

### 2.7 Test Coverage

| Test file | Tests | Status |
|-----------|-------|--------|
| `test_orchestrator_driver.py` | 49 | ✅ All pass |
| `test_workshop_foundation.py` | 5 | ✅ All pass |
| `test_conclude_gate.py` | — | ✅ Exists |
| `test_context_build.py` | — | ✅ Exists |
| `test_docs_skill_wiring.py` | — | ✅ Exists |
| `test_hitl_recovery.py` | — | ✅ Exists |
| `test_model_backends.py` | — | ✅ Exists |
| `test_enforcement.py` | — | ✅ Exists |
| `test_conductor.py` | — | ✅ Exists |
| `test_driver.py` | — | ✅ Exists |
| Other test files | 33 total `.py` files | ✅ Various |

### 2.8 Reference Documentation

| Document | Content |
|----------|---------|
| `references/orchestrator-pipeline-modification.md` | Phase addition patterns, schema migration |
| `references/orchestrator-pipeline-fixes.md` | RECALL/CONCLUDE, phase_mode, SHA bypass, HITL fix |
| `references/orchestrator-recall-workshop-contract.md` | Structured RECALL contract, workshop retrieval |
| `references/rl-pipeline-notes.md` | Field notes from real pipeline runs |
| `references/orchestrator-retro-visibility.md` | RETRO template + gate requirements |
| `references/orchestrator-pipeline-improvements.md` | Improvement proposals |
| `references/*.md` | 14 more reference docs (bug analysis, deployment, etc.) |

---

## 3. What's Working Well (Strengths to Preserve)

1. **Complete 10-phase pipeline** — every phase from RECALL to CONCLUDE is
   implemented with real gates and agent definitions. No placeholder phases.

2. **Deterministic EVAL** — EVAL computes a real 100-point score from actual
   signals (gates passed, test output, review findings). No model call needed.

3. **Phase-mode fast/full** — review-only tasks can skip RECALL and CONCLUDE,
   saving tokens without breaking the pipeline shape.

4. **HITL recovery works** — `BLOCK_HITL` → `unblock(proceed|debug)` → resume
   at correct phase. The PENDING reset guard prevents losing RECALL completion.

5. **Workshop retrieval in RECALL** — `_build_workshop_recall_lines()` injects
   `.techne/context_search.py` output into the RECALL prompt. Error-tolerant.

6. **Gate evolution under human ratification** — `propose → validate → ratify`
   firewall prevents auto-Goodhart. Only a human writes a gate plugin.

7. **Prompt evolution under human ratification** — Same firewall for prompt
   variants. Winners get reused, losers retired.

8. **Host-driven architecture** — no model API keys required for the pipeline
   itself. The host agent supplies every model turn. Techne runs gates,
   evaluates, and records.

9. **Structured RECALL contract** — `HONCHO_CONTEXT` + `WORKSHOP_CONTEXT` +
   `LESSONS` + `FOCUS` enforced by the RECALL validator.

10. **CONCLUDE git-state gate** — `.techne/context` must be committed before
    CONCLUDE passes. Prevents drift between workshop context and reality.

---

## 4. Flaws, Gaps & Regressions

### 4.1 RL System is Basic (Critical Gap)

| Issue | Current | Needed |
|-------|---------|--------|
| Reward is post-hoc | Reward logged AFTER the run, not used during it | Real-time reward shaping that guides phase transitions |
| No GRPO | Basic weighted composite score | Group Relative Policy Optimization — compare runs against peer group |
| No policy gradient | Prompt evolution is propose/validate/ratify (human-gated) | Automated policy improvement within safety bounds |
| No value function | EVAL score is a single number, not a learned predictor | Learn to predict task success from early signals |
| Single-agent only | One pipeline run = one agent trajectory | Multi-trajectory comparison for GRPO advantage estimation |

### 4.2 Memory Recall is Weak

| Issue | Current | Needed |
|-------|---------|--------|
| Honcho search is prompt-level | RECALL agent is told "search Honcho" but no structured API call | Real Honcho API integration in `_submit_recall()` |
| No auto-memory | Memory/mistakes.md/reward.md are manual append-only files | Auto-extract lessons from RETRO → memory |
| No cross-session memory | Each session starts fresh (Honcho helps but is basic) | Persistent workshop memory across sessions |
| Workshop memory is file-based | `.techne/memory/wikilinks.md` is a generated markdown file | Queryable memory store with semantic search |

### 4.3 Workshop Integration is Partial

| Issue | Current | Needed |
|-------|---------|--------|
| Workshop scripts exist but aren't auto-run | `context_index.py` must be invoked manually | Auto-rebuild context index after every pipeline run |
| Context docs drift from code | `.techne/context/*.CONTEXT.md` are hand-written | Auto-detect when context is stale and flag for refresh |
| No workshop health check | No way to know if workshop is out of date | `workshop health` command that checks freshness |
| No workshop bootstrap | New project: must manually create `.techne/` dir | `techne init` workshop command |

### 4.4 Agent Quality Issues

| Issue | Current | Needed |
|-------|---------|--------|
| review_only SHA bypass is a bandaid | Review-only tasks skip pass-indicator check | Better VERIFY mode for review-only (check review output instead) |
| HARD_FAIL substring is fragile | Any review containing "HARD_FAIL" blocks the task, even in negation | Context-aware review verdict parsing |
| RECALL contract is text-parsed | `_submit_recall` uses `.lower()` substring matching | Structured output parsing (prefix lines are fragile) |
| IMPLEMENT contract is text-parsed | Same — `workshop_context:` substring check | Use the same structured line format as RECALL |

### 4.5 Infrastructure Gaps

| Issue | Current | Needed |
|-------|---------|--------|
| No agent-to-agent communication | Each phase runs independently | Agents should be able to reference previous phase output |
| No run history visualization | `eval_history.json` and `run_log.json` are raw JSON | Dashboard or summary view |
| No rollback mechanism | If a change goes wrong, manual revert | Pipeline rollback that creates an undo task |
| No parallel execution | Tasks run sequentially even when independent | Parallel phase execution for independent tasks |
| No deploy pipeline integration | Pipeline ends at DONE — no deploy hook | Post-DONE hook for deploy/PR creation |

### 4.6 Regression Risks

| Risk | Why | Mitigation |
|------|-----|------------|
| RECALL contract too strict | Adding WORKSHOP_CONTEXT requirement may break tasks without a workshop | Fast-mode exists, but full-mode without workshop gets stuck | Make workshop check graceful: emit warning, don't block |
| CONCLUDE git-state too strict | Tasks that don't touch `.techne/context` still get blocked if ANY context file is dirty | Only check files relevant to the task, not all context files |
| HITL re-entry still fragile | The `current != "RECALL"` guard is a bandaid | Formalize the state machine to track which phases are complete vs. which are pending |
| Driver phase_mode only for dict specs | String specs still default to full | Make string specs accept `phase_mode:` prefix or always default to full |
| 54 tests is not enough | One pipeline change can break phase ordering without a test catching it | Add phase-ordering property tests |

---

## 5. The Workshop Garage Vision

### 5.1 What Is a Workshop Garage?

A **workshop garage** is a persistent, project-attached engineering environment
that an AI agent uses to build, learn, and improve over time. It's a garage
because:

- **Tools on the wall** — context docs, scripts, indexes, reference materials
  are always available, organized, and searchable
- **Workbench** — the pipeline phases are the workbench where work gets done
- **Parts bin** — memory (Honcho + workshop) stores reusable knowledge, past
  decisions, and learned patterns
- **Diagnostic lift** — when something breaks, the garage has diagnostic tools
  (debugger, mistake tracker, regression detector)
- **Self-improving** — the garage learns from every job. Better tools get
  added, broken tools get fixed, workflow improves over time

### 5.2 Core Components

```
┌─────────────────────────────────────────────────────────┐
│                   WORKSHOP GARAGE                        │
│                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │   TOOLS      │  │  PROTOCOLS   │  │   WORKFLOW     │  │
│  │             │  │              │  │                │  │
│  │ • context   │  │ • pipeline   │  │ • RECALL →     │  │
│  │   index     │  │   phases     │  │   IMPLEMENT →  │  │
│  │ • search    │  │ • gates      │  │   VERIFY →     │  │
│  │ • wikilink  │  │ • phase-mode │  │   RETRO →      │  │
│  │ • scripts   │  │ • HITL       │  │   CONCLUDE     │  │
│  │ • diagrams  │  │ • evolution  │  │                │  │
│  └──────┬──────┘  └──────┬───────┘  └───────┬────────┘  │
│         │                │                   │           │
│  ┌──────┴────────────────┴───────────────────┴────────┐  │
│  │                  MEMORY LAYER                       │  │
│  │  ┌──────────┐  ┌───────────┐  ┌─────────────────┐  │  │
│  │  │ Honcho   │  │ Workshop  │  │ Auto-update     │  │  │
│  │  │ durable  │  │ context   │  │ context refresh │  │  │
│  │  │ facts    │  │ docs      │  │ after each run  │  │  │
│  │  └──────────┘  └───────────┘  └─────────────────┘  │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌─────────────────────────────────────────────────────┐  │
│  │              RL ENGINE (GRPO)                       │  │
│  │  ┌──────────┐  ┌───────────┐  ┌─────────────────┐  │  │
│  │  │ Reward   │  │ Prompt    │  │ Gate evolution  │  │  │
│  │  │ shaping  │  │ policy    │  │ (pattern →      │  │  │
│  │  │          │  │ evolution │  │  gate)          │  │  │
│  │  └──────────┘  └───────────┘  └─────────────────┘  │  │
│  └─────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 5.3 Key Design Principles

1. **Memory is recallable, not queried** — The RECALL phase MUST surface
   relevant memory BEFORE IMPLEMENT starts. The agent doesn't search for
   context — it's handed to it.

2. **Memory auto-updates after every run** — Each CONCLUDE phase triggers:
   - Context doc refresh (if files changed)
   - Wikilink rebuild
   - Honcho fact checkpoint
   - Mistake/reward ledger update (from RETRO output)
   - Prompt/gate evolution (if thresholds met)

3. **RL is human-gated, not autonomous** — GRPO proposes improvements, but
   only human ratification ships them. The propose/validate/ratify firewall
   stays.

4. **Tools are project-attached** — Every project gets its own `.techne/`
   directory. The workshop config, context docs, scripts, and memory live
   IN the repo, not in the skill.

5. **The pipeline IS the workflow** — All work goes through RECALL → IMPLEMENT
   → ... → CONCLUDE. No shortcuts. Phase-mode fast is the only bypass, and
   only for review-only tasks.

### 5.4 Memory Architecture (Recallable + Auto-Update)

```
┌──────────────────────────────────────────────────────┐
│                  MEMORY ARCHITECTURE                   │
│                                                        │
│  RECALL TIME (before IMPLEMENT):                       │
│  ┌─────────────────────────────────────────────────┐  │
│  │ RECALL Prompt (built by _build_user_context)     │  │
│  │                                                   │  │
│  │ • Task title + tags (from TaskDB)                 │  │
│  │ • Honcho context (via honcho_search API)          │  │
│  │ • Workshop retrieval packet (via context_search)  │  │
│  │   - Relevant .CONTEXT.md docs                     │  │
│  │   - Relevant files from index                     │  │
│  │   - Related subsystems                            │  │
│  │   - Past mistakes/lessons/decisions               │  │
│  │ • Latest eval trends (improving/degrading?)       │  │
│  └─────────────────────────────────────────────────┘  │
│                                                        │
│  CONCLUDE TIME (after run completes):                   │
│  ┌─────────────────────────────────────────────────┐  │
│  │ Auto-Update Triggers                             │  │
│  │                                                   │  │
│  │ 1. honcho_conclude() — save durable facts         │  │
│  │ 2. mistakes.py — log gate failures (if any)       │  │
│  │ 3. reward.py — log CLEAN/SOLVED (if applicable)   │  │
│  │ 4. reward_log.record() — composite reward         │  │
│  │ 5. post_run_evolve() — stage prompt/gate proposals│  │
│  │ 6. context_index.py — rebuild (if files changed)  │  │
│  │ 7. refresh_generated_docs.py — regenerate         │  │
│  │ 8. wikilink rebuild (if files changed)            │  │
│  └─────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

### 5.5 GRPO Integration (Reinforcement Learning)

GRPO (Group Relative Policy Optimization) compares multiple pipeline runs
against each other to determine which prompts, gates, and workflows produce
better outcomes.

```
Current RL (basic):
  Single run → EVAL score → reward_log.record() → post_run_evolve()

Target RL (GRPO):
  Run A (prompt variant v1) → EVAL score A
  Run B (prompt variant v2) → EVAL score B
  Run C (prompt variant v3) → EVAL score C
                  ↓
        GRPO: compare A vs B vs C
        advantage = score - mean(scores)
                  ↓
        Update policy: higher advantage → promote variant
                  ↓
        Propose new variants (mutate winners)
                  ↓
        Human ratify or reject
```

**Key GRPO components to build:**

| Component | Description |
|-----------|-------------|
| Task type grouping | Group runs by task type (auth, ui, data, api, infra) for fair comparison |
| Advantage computation | `advantage = score - mean(scores_in_group)` |
| Policy update | Promote winning variants, mutate for new candidates |
| Safety clamp | Never auto-ship — always ratify gate |
| Multi-trajectory | Queue similar tasks, run with different variants, compare results |

---

## 6. Build Plan

### Phase 1: Foundation (Current State ✅)

**Already done:**
- 10-phase pipeline with gates
- Workshop shell (config, context docs, scripts)
- Structured RECALL contract
- Phase-mode full/fast
- HITL recovery
- Basic reward system
- Agent definitions
- 54 passing tests

### Phase 2: Memory Upgrade (Next Priority)

**Objective:** Make memory recallable + auto-updating.

| Task | Description | Priority |
|------|-------------|----------|
| Auto-context-index rebuild | Run `context_index.py` after every CONCLUDE | P0 |
| Auto-wikilink rebuild | Rebuild wikilinks when files change | P0 |
| RETRO → memory extraction | Auto-extract lessons from RETRO output → mistakes.md / reward.md | P0 |
| Honcho API integration | Real `honcho_search` call in `_submit_recall()` instead of prompt-level instruction | P0 |
| Workshop health check | `techne workshop health` command to detect stale context | P1 |
| Memory freshness flag | Flag in RECALL prompt when memory is >N runs stale | P1 |
| Cross-session memory bridge | Honcho as cross-session memory backbone, not just per-session | P1 |

### Phase 3: RL Engine (GRPO)

**Objective:** Replace basic reward system with GRPO-driven policy optimization.

| Task | Description | Priority |
|------|-------------|----------|
| Task type classifier | Auto-classify tasks into type groups for fair comparison | P0 |
| Group-based scoring | Run multiple tasks of same type → group scores → compute advantage | P0 |
| GRPO policy update | Promote winning variants based on advantage signal | P0 |
| Safety clamp | Never auto-ship — human ratification before any policy change | P0 |
| Multi-trajectory queue | Queue runner that dispatches N variants of same task and compares | P1 |
| Value function | Learn to predict EVAL score from early-phase signals | P2 |
| Real-time reward shaping | Adjust phase behavior mid-run based on live signal | P2 |

### Phase 4: Workshop Garage Tooling

**Objective:** Build the "garage" feel — tools on the wall, diagnostic lift, parts bin.

| Task | Description | Priority |
|------|-------------|----------|
| `techne init` command | Bootstrap `.techne/` in any project | P0 |
| `techne workshop health` | Check freshness of all workshop components | P0 |
| `techne workshop sync` | Force rebuild all generated artifacts | P1 |
| `techne dashboard` | Summary of recent runs, trends, open proposals | P1 |
| Workshop browser | TUI or markdown view to browse context docs, memory, recent runs | P2 |
| Regression dashboard | Show what's degrading across runs (from evaluator trends) | P2 |

### Phase 5: Pipeline Hardening

**Objective:** Fix remaining fragility and complete edge cases.

| Task | Description | Priority |
|------|-------------|----------|
| RECALL contract graceful downgrade | Full-mode without workshop gets warning, not block | P0 |
| CONCLUDE git-state scoping | Only check task-relevant context files, not all | P0 |
| HARD_FAIL parsing | Context-aware review verdict parsing, not substring match | P1 |
| Structured output throughout | All phases use structured lines (not substring matching) | P1 |
| Phase-ordering property tests | PBT-style tests that phase ordering is invariant under mutations | P1 |
| Parallel task execution | Independent tasks run in parallel | P2 |
| Post-DONE deploy hook | After CONCLUDE → DONE, optional deploy/PR workflow | P2 |

### Phase 6: Agent Improvement

**Objective:** Make agents better at their jobs through the RL loop.

| Task | Description | Priority |
|------|-------------|----------|
| Agent-to-agent context passing | RETRO should see CRITIQUE output; CONCLUDE should see RETRO | P0 |
| Per-agent prompt evolution | Different prompt variants per agent, not just implementer | P0 |
| Cross-agent reward shaping | Reward based on multi-agent coherence (critique caught reviewer's finding) | P1 |
| Agent specialization | Fine-tune agent prompts per task type | P2 |

---

## 7. Success Criteria

The Workshop Garage is **done** when:

1. **Every pipeline run updates memory automatically** — no manual context
   refresh, no manual wiki rebuild. After CONCLUDE, everything is current.

2. **RECALL surfaces truly relevant context** — not just task title keywords,
   but related decisions, mistakes, and patterns from Honcho + workshop +
   past runs. The agent never starts IMPLEMENT blind.

3. **GRPO improves outcomes measurably** — after N runs of a task type, the
   prompt variants that win are measurably better (>5% EVAL score improvement)
   than the variants that lose.

4. **Workshop is project-attached, not skill-attached** — every project with
   a `.techne/` directory has its own context, memory, and tools. No
   cross-project pollution.

5. **Pipeline is robust** — no fragile substring parsing. Structured output
   contracts everywhere. Phase-ordering invariant tests pass.

6. **New project setup takes < 1 minute** — `techne init` creates the full
   workshop shell with sensible defaults.

---

## 8. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| GRPO auto-ships bad policy | Low | High | Human-ratify firewall: propose → validate → ratify |
| Memory auto-update overwrites context | Medium | Medium | Auto-update is append-only; deletions need human approval |
| Workshop drift from actual codebase | Medium | Medium | Workshop health check flags stale docs |
| Pipeline becomes too slow | Medium | Medium | Phase-mode fast exists; parallel execution in Phase 5 |
| Over-engineering before core needs | High | High | Build in priority order; Phase 1 (done) → Phase 2 → Phase 3 |
| Token costs from auto-update | Medium | Low | Auto-update runs locally (Python scripts, no model calls) |
| Cross-session memory bloat | Low | Medium | Honcho auto-compacts; workshop memory is git-tracked |

---

## 9. Immediate Next Steps

The current state has **Phase 1 complete**. The highest-impact next work is:

1. **Phase 2 (Memory Upgrade):** Auto-context-index rebuild, RETRO→memory
   extraction, Honcho API integration. These directly improve every pipeline
   run.

2. **Phase 5 (Pipeline Hardening):** RECALL graceful downgrade, CONCLUDE
   git-state scoping. These fix the most likely failure modes.

3. **Phase 3 (GRPO):** Task type classifier + group-based scoring. Without
   this, the RL loop can't learn.

Shall I proceed with Phase 2 prioritization and ticket creation?
