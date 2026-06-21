# Techne

> A project-attached engineering workshop: a disciplined pipeline that governs how code work happens, a `.techne/` shell that holds context and memory, and a GRPO engine that improves prompts and skills over time.

[![Tests](https://img.shields.io/badge/tests-525%2B-brightgreen)](#project-status)
[![Pipeline](https://img.shields.io/badge/pipeline-11%20phases-blue)](#the-11-phase-pipeline)
[![Python](https://img.shields.io/badge/python-3.10%2B-orange)](#requirements)
[![No API Key](https://img.shields.io/badge/API%20key-none%20required-lightgrey)](#architecture)

---

## Table of Contents

- [What is Techne?](#what-is-techne)
- [Architecture](#architecture)
- [The 11-Phase Pipeline](#the-11-phase-pipeline)
- [Workshop Garage](#workshop-garage)
- [GRPO Engine](#grpo-engine)
- [Receptionist Pattern](#receptionist-pattern)
- [Quick Start](#quick-start)
- [Project Status](#project-status)
- [Documentation Map](#documentation-map)

---

## What is Techne?

Techne is a **project-attached engineering workshop** that disciplines how code work happens. It has three parts:

1. **The pipeline** — an 11-phase loop (RECALL → IMPLEMENT → ... → REFRESH_CONTEXT → DONE) that every code change goes through. No exceptions, no shortcuts for one-liners.

2. **The workshop garage** — a `.techne/` directory per project that holds:
   - Context docs describing the codebase
   - Generated indexes and knowledge graphs
   - Memory: mistakes, lessons, decisions
   - Scripts for context search and refresh

3. **The GRPO engine** — reinforcement learning that compares pipeline runs, scores prompt variants and skills, and proposes improvements for human ratification.

> **Techne never calls a model and never needs an API key.** Your agent runs every reasoning turn. Techne supplies the deterministic spine: gates, scoring, memory writes, and RL proposals.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      HOST (Receptionist)                     │
│                                                              │
│  • Plans and classifies requests                             │
│  • Writes tickets (MODE / OBJECTIVE / CONTEXT / CONSTRAINTS) │
│  • Dispatches via delegate_task                              │
│  • Verifies reports and maintains the session plan           │
│  • Synthesizes results after each task                       │
└────────────────────────────┬─────────────────────────────────┘
                             │ delegate_task()
                             │ (ticket schema)
                             ▼
┌──────────────────────────────────────────────────────────────┐
│                      TECHNE (Workshop)                       │
│                                                              │
│  • Executes pipeline phases (RECALL → ... → REFRESH_CONTEXT) │
│  • Enforces hard gates on every phase output                │
│  • Scores runs (100-point EVAL)                              │
│  • Records to Honcho + workshop memory                       │
│  • Runs GRPO: classify → score → advantage → propose        │
└──────────────────────────────────────────────────────────────┘
```

### Hard Separation Rule

```
┌─────────────────┐        ┌─────────────────┐
│   HOST never    │        │  TECHNE never   │
│   implements    │        │     plans      │
│   code directly │        │   or dispatches │
└─────────────────┘        └─────────────────┘
```

**You plan. Techne builds. Never the two in one.**

- **Host** = planner, dispatcher, verifier. Holds session context. Reads tickets and reports.
- **Techne** = execution engine. Runs phases, enforces gates, scores, records memory. Calls no models.

See [docs/host-integration-guide.md](docs/host-integration-guide.md) for the full operational contract.

---

## The 11-Phase Pipeline

```
RECALL → IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → EVAL → RETRO → CONCLUDE → REFRESH_CONTEXT → DONE
```

| Phase | What it does | Gate |
|-------|-------------|------|
| **RECALL** | Search Honcho + workshop graph for relevant context, past mistakes, decisions | `WORKSHOP_CONTEXT:` header required |
| **IMPLEMENT** | Subagent produces a unified diff | `@@`/`--- ` diff markers required |
| **CONTEXT_GUARD** | Scope audit + docs/Honcho punch list closure | Punch list section required |
| **CRITIQUE** | Risk analysis; can `BLOCK_HITL` for human judgment | Risk-level parsing |
| **REVIEW** | Read-only correctness + security check | `HARD_FAIL` substring blocks pipeline |
| **VERIFY** | Run tests, capture real stdout | SHA gate checks pass indicators |
| **EVAL** | Deterministic 100-point score (5 dimensions) | Automatic |
| **RETRO** | 7-question structured retrospective | ≥100 chars + phase references |
| **CONCLUDE** | Honcho write-back, git commit, proof lines | Git state check for `.techne/context` |
| **REFRESH_CONTEXT** | Rebuild workshop graph, generated docs | Script exit code |
| **DONE** | Task closed | — |

### Phase Modes

| Mode | RECALL | CONCLUDE | REFRESH_CONTEXT | Use for |
|------|--------|----------|-----------------|---------|
| `full` (default) | ✅ | ✅ | ✅ | All code changes |
| `fast` | ❌ | ❌ | ❌ | Review-only, no file edits |

**There is no `fast` escape for code changes.** A typo fix still goes through the full pipeline.

### HITL Recovery

When CRITIQUE triggers `BLOCK_HITL`, the pipeline pauses for human judgment. To resume:

```python
p.unblock(task_id, "proceed")   # or "debug"
# Then submit the NEXT phase (not the blocked one)
```

---

## Workshop Garage

The `.techne/` directory is your project's workshop shell. It lives **in the repo**, not in the skill directory — each project has its own.

```
.techne/
├── config.yaml              # Project name, context glob, generated dir
├── context/
│   ├── root.CONTEXT.md      # Repo-level context
│   ├── harness.CONTEXT.md   # Techne internals context
│   ├── memory.CONTEXT.md     # Memory system context
│   └── project_digest.md    # Auto-generated project overview
├── generated/
│   ├── context_index.json   # File-to-subsystem graph
│   ├── subsystem_map.json   # Subsystem ownership
│   └── change_log.json      # What changed in last run
├── memory/
│   ├── wikilinks.json       # Knowledge graph (files + mistakes + decisions)
│   ├── wikilinks.md         # Human-readable mirror
│   └── prompt_variants.json # RL-proposed prompt variants
├── proposals/               # GRPO-proposed changes awaiting ratification
├── scripts/
│   ├── context_index.py     # Build the search index
│   ├── context_search.py     # Graph-aware retrieval at RECALL
│   └── refresh_generated_docs.py  # Refresh stale generated docs
└── tasks/                   # Per-task run artifacts
```

### Keeping Knowledge Fresh

The `REFRESH_CONTEXT` phase runs after every `CONCLUDE`. It:

1. Rebuilds `generated/context_index.json` from the current codebase
2. Updates `generated/subsystem_map.json` if files changed
3. Flags stale authored docs in `generated/stale_docs.json`
4. Rebuilds the wikilink graph connecting files → subsystems → mistakes

Without REFRESH_CONTEXT, context grows stale. With it, RECALL surfaces what actually matters — not just what's nearby.

### Memory Architecture

```
RECAST TIME (before IMPLEMENT):
  ┌─────────────────────────────────────────────────────┐
  │ RECALL Prompt built by _build_user_context()        │
  │  • Task title + tags                                │
  │  • Honcho context (via honcho_search API)           │
  │  • Workshop retrieval packet (via context_search.py)│
  │    - Relevant .CONTEXT.md docs                      │
  │    - Relevant files from index                       │
  │    - Related subsystems                              │
  │    - Past mistakes/lessons/decisions                │
  │  • Latest eval trends                               │
  └─────────────────────────────────────────────────────┘

CONCLUDE TIME (after run completes):
  ┌─────────────────────────────────────────────────────┐
  │ Auto-Update Triggers                                 │
  │  1. honcho_conclude() — save durable facts          │
  │  2. mistakes.py — log gate failures (if any)       │
  │  3. reward.py — log CLEAN/SOLVED (if applicable)   │
  │  4. reward_log.record() — composite reward         │
  │  5. post_run_evolve() — stage prompt/gate proposals│
  │  6. REFRESH_CONTEXT — rebuild generated docs       │
  └─────────────────────────────────────────────────────┘
```

---

## GRPO Engine

**GRPO** (Group Relative Policy Optimization) compares multiple pipeline runs to determine which prompts, gates, and skills produce better outcomes.

### How the RL Loop Works

```
┌─────────────────────────────────────────────────────────────┐
│                    GRPO CYCLE                               │
│                                                             │
│  1. CLASSIFY — Group runs by task type (auth, ui, api…)   │
│                    ↓                                        │
│  2. SCORE — EVAL produces 100-point score per run         │
│                    ↓                                        │
│  3. ADVANTAGE — advantage = score - mean(scores_in_group) │
│                 (requires ≥2 runs in group to compute)     │
│                    ↓                                        │
│  4. PROPOSE — High-advantage variants → proposals          │
│               • prompt_evolution: Propose prompt variants   │
│               • grpo: propose_skill_edits() for skills     │
│               • gate_evolution: Pattern-based gate tweaks   │
│                    ↓                                        │
│  5. RATIFY — Human reviews and approves/rejects            │
│               (via apply_retro.py — never auto-applied)    │
│                    ↓                                        │
│  6. APPLY — Approved changes written to skills/*.md        │
└─────────────────────────────────────────────────────────────┘
```

### Two Comparison Axes

GRPO tracks advantage on two independent axes:

| Axis | What it compares | Key file |
|------|-----------------|----------|
| **Prompt variants** | `v1_strict` vs `v2_pragmatic` vs `v3_contextual` | `.techne/memory/prompt_variants.json` |
| **Skills** | `implementer` vs `diagnose` vs `tdd` vs task-type matches | `skills/*.md` |

> **Safety clamp:** GRPO proposals never auto-apply. Every proposed change goes through `apply_retro.py` for human ratification. The `auto_apply_pending()` function exists but is intentionally not wired to anything.

### What Got Built (Track B)

- `harness/grpo.py` — GRPO proposal engine (proposes to skills + prompts)
- `harness/classify.py` — Task-type classifier from `discipline`/`tags`
- `RewardLog.compute_batch_advantages()` — Group-relative scoring
- `RewardLog.high_advantage_variants()` / `high_advantage_skills()` — Winner detection
- `harness/trajectory_queue.py` — Multi-trajectory queue for variant comparison
- `harness/reward_log.py` — SQLite-backed reward recording with `skill` field

---

## Receptionist Pattern

The **host agent operates as a Receptionist**. Your job is to hold context, understand intent, write precise tickets, delegate execution, verify reports, and maintain the running plan.

### The Cycle

```
INTAKE → CLASSIFY → PLAN → TICKET → DISPATCH → VERIFY REPORT → UPDATE PLAN → next ticket or DONE → SYNTHESIZE
```

### The Three Modes (post-P5.1 collapse)

| Mode | Purpose | When to use |
|------|---------|-------------|
| **EXPLORE** | Build situational awareness of the current codebase | You don't have an accurate map of relevant files |
| **SCOUT** | External research / feasibility for unknown APIs | The answer isn't in the codebase |
| **IMPLEMENT** | ALL code changes — net-new, wiring, bug fixes, config edits | BUILD and DEBUGGING absorbed here |

### Ticket Schema

Every `delegate_task` call uses this exact shape:

```yaml
MODE: [EXPLORE | SCOUT | IMPLEMENT]
OBJECTIVE: <1-2 sentences, single outcome>
CONTEXT: <curated file paths/excerpts — NEVER the whole repo>
CONSTRAINTS: <architecture rules, layer boundaries, do-not-touch>
DONE_WHEN: <concrete, checkable verification criteria>
OUTPUT_FORMAT: <diff | report | both>
FIX_OF: <optional — fill for fix tickets, omit for net-new work.
         When present, subagent MUST include: root cause statement,
         the specific failure being fixed, regression risk note.>
```

### Automatic Dispatch Rule

> **If the request will result in any file being created, edited, or deleted, dispatch `MODE: IMPLEMENT`.**

This is absolute. The only work that stays outside Techne's pipeline is read-only analysis, research, or planning that will never produce a diff.

### Verification Protocol

After each subagent returns:

1. **Read the report** — does it match `DONE_WHEN`?
2. **Run tests** — confirm existing tests still pass
3. If tests fail due to **intentional contract changes** → fix assertions (verification)
4. If tests fail due to **implementation bugs** → write `FIX_OF` ticket, do NOT patch
5. If report is ambiguous → re-ticket with tighter constraints (max 1 retry)

**You never edit implementation code directly.** The one exception is updating test assertions for intentional contract changes.

### ReceptionistEnforcer

`harness/receptionist_enforcer.py` enforces dispatch protocol rules mechanically:
- Mode exclusivity (one mode per ticket)
- One retry max
- Verify-before-close
- `FIX_OF` requirements

Call it explicitly at your dispatch points:
```python
receptionist_enforcer.can_dispatch(ticket)     # before delegate_task
receptionist_enforcer.mark_verified(ticket_id)  # before ticket close
receptionist_enforcer.mark_retry(ticket_id)     # on rejected report
```

---

## Quick Start

See [INSTALL.md](INSTALL.md) for the full install guide. This is the summary:

### 1. Install

```bash
# Option A — git submodule (recommended for a host repo)
git submodule add https://github.com/jtoemion/techne.git techne

# Option B — clone standalone
git clone https://github.com/jtoemion/techne.git

# Option C — vendor (copy the folder in)
cp -r techne/ your-project/
```

### 2. Register the skill entry

Point your agent at `SKILL.md` as its first-read entry point:

```yaml
# Your host's skill config
- name: techne
  path: techne/SKILL.md
  always_read: true
```

### 3. Configure per project

Create `.techne/config.yaml` at the project root:

```yaml
project_name: my-project
context_glob: "src/**/*.{ts,svelte,py}"
generated_dir: .techne/generated
```

### 4. Bootstrap the workshop

```bash
cd your-project/
python .techne/scripts/context_index.py
```

This builds `.techne/generated/context_index.json` — the searchable graph for RECALL.

### 5. Verify

```bash
cd techne/
python tests/test_workshop_foundation.py      # expect 5/5
python tests/test_orchestrator_driver.py      # expect 49/49
```

### 6. Your first task

```python
from task_db import TaskDB
from orchestrator_loop import OrchestratorLoop

db = TaskDB("techne/tasks.db")
tid = db.create_task(
    title="Add login button to header",
    description="...",
    tags=["ui", "p1"],
    phase_mode="full"   # default; omit for review-only
)

loop = OrchestratorLoop(db)
prompt = loop.get_prompt(tid, "RECALL")
# Run prompt as your turn, then:
result = loop.submit(tid, "RECALL", your_output)
```

---

## Project Status

### Tracks A & B — Complete

**Track A — Workshop Knowledge Loop:**
```
A1. Resolve memory-location decision                   ✅
A2. Wire REFRESH_CONTEXT as a real pipeline phase      ✅
A3. Connect entries to subsystem nodes                 ✅
A4. Add task nodes + task-triggered edges              ✅
A5. CONCLUDE git-state scoping fix                     ✅
A6. HITL re-entry state machine fix                   ✅
A7. Honcho proof-verification (checkpoint.py)         ✅
A8. Adapters for symbol/route/schema/test node types   (deferred)
```

**Track B — GRPO:**
```
B0. Fix skill-write path before scoring               ✅
B1. Task-type classifier from discipline/tags          ✅
B2. Group-based scoring / advantage computation        ✅
B3. Policy update — write through B0's path            ✅
B4. Multi-trajectory queue                             ✅
```

### Post-Build Audit (Patch 001 — 2026-06-21)

Five issues found and resolved after verifying all built code:

| Patch | Severity | Finding | Status |
|-------|----------|---------|--------|
| P1 | 🔴 | GRPO `compute_batch_advantages()` never called on normal pipeline path | ✅ Fixed |
| P2 | 🔴 | `prompt_variants.json` shared file with no test isolation | ✅ Fixed |
| P3 | 🟡 | Honcho gate shipped without updating 3 test files | ✅ Fixed |
| P4 | 🟡 | GRPO only targets prompts, not skills | ✅ Fixed |
| P5 | 🟢 | Receptionist handoff had no auto-trigger rule | ✅ Fixed |

### Test Suite

```
34 test files
525+ test functions
65/65 eval suite (deterministic gates + router + intent)
```

### What's Working

- Complete 11-phase pipeline with real gates on every phase
- Deterministic EVAL (100-point, no model call needed)
- Phase-mode fast/full for review-only vs code-change tasks
- HITL recovery with proper state machine handling
- Workshop retrieval in RECALL (graph-aware context search)
- GRPO under human ratification (propose → ratify → apply firewall)
- Structured RECALL contract (`HONCHO_CONTEXT` + `WORKSHOP_CONTEXT` + `LESSONS` + `FOCUS`)
- CONCLUDE git-state gate (`.techne/context` must be committed)

### What's Next (Build Guide §5-6)

- Workshop health check command (`techne workshop health`)
- Auto-run context index rebuild after every CONCLUDE
- Per-agent prompt evolution (not just implementer)
- Value function to predict EVAL from early-phase signals
- Parallel task execution for independent tasks
- Post-DONE deploy/PR hook

---

## Documentation Map

| Document | What it's for |
|----------|---------------|
| **[SKILL.md](SKILL.md)** | **Start here.** Skill router + full pipeline reference |
| **[INSTALL.md](INSTALL.md)** | Install options, verification steps, Pipeline API |
| **[COMPONENTS.md](COMPONENTS.md)** | Every skill, agent, gate, and module catalog |
| **[docs/host-integration-guide.md](docs/host-integration-guide.md)** | **Host agent contract.** Two-layer architecture, dispatch protocol, quick reference |
| **[docs/plans/techne-workshop-garage.md](docs/plans/techne-workshop-garage.md)** | Workshop vision: memory architecture, GRPO integration, build plan |
| **[docs/plans/techne-workshop-build-guide.md](docs/plans/techne-workshop-build-guide.md)** | Operational audit: what's real, what to build, exact steps |
| **[docs/plans/techne-build-guide-patch-001.md](docs/plans/techne-build-guide-patch-001.md)** | Post-build audit: 5 live bugs found, all fixed |

### Key References

```
references/
├── orchestrator-recall-workshop-contract.md   # RECALL output contract
├── orchestrator-pipeline-fixes.md            # RECALL/CONCLUDE/RETRO fixes
├── orchestrator-pipeline-modification.md     # Adding new phases
├── rl-pipeline-notes.md                      # Field notes from real runs
├── receptionist-protocol.md                   # Full Receptionist protocol
└── hook-gate-bridge.md                      # Hermes pre_tool_call → Techne gates
```

---

## License

MIT

## Contributing

When contributing to Techne:
1. Read [docs/host-integration-guide.md](docs/host-integration-guide.md) first
2. Run the test suite before and after any change: `python tests/test_workshop_foundation.py`
3. All code changes go through the pipeline — there is no hotfix exception
4. GRPO proposals must be human-ratified before shipping
