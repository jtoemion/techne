# Techne

> A project-attached engineering workshop: a disciplined `./next` loop with disk-proven enforcement, a `.techne/` context shell that amortizes project understanding, and a GRPO engine that improves skills and prompts over time.

[![Tests](https://img.shields.io/badge/tests-781%2B-brightgreen)](#project-status)
[![Pipeline](https://img.shields.io/badge/pipeline-5--phase%20./next%20loop-blue)](#the-next-loop)
[![Enforcement](https://img.shields.io/badge/enforcement-phase__guard%20%2B%20audit%20chain%20%2B%20watchdog-green)](#enforcement-stack)
[![GRPO/RL](https://img.shields.io/badge/GRPO-RL%20engine%20%2B%20framework%20skills-purple)](#grpo-engine)
[![Python](https://img.shields.io/badge/python-3.10%2B-orange)](#requirements)
[![No API Key](https://img.shields.io/badge/API%20key-none%20required-lightgrey)](#architecture)

---

## Table of Contents

- [What is Techne?](#what-is-techne)
- [Architecture](#architecture)
- [The ./next Loop](#the-next-loop)
- [Enforcement Stack](#enforcement-stack)
- [Context Amortization](#context-amortization)
- [Wikilink Knowledge Graph](#wikilink-knowledge-graph)
- [EVAL System](#eval-system)
- [GRPO Engine](#grpo-engine)
- [Quick Start](#quick-start)
- [Project Status](#project-status)
- [Documentation Map](#documentation-map)

---

## What is Techne?

Techne is a **project-attached engineering workshop** that disciplines how code work happens. It has three actual systems:

1. **The `./next` loop** — a 5-phase pipeline (`RECALL → IMPLEMENT → VERIFY → CONCLUDE → DONE`) enforced by disk artifacts. Every code change goes through every phase. No exceptions.

2. **The Workshop Garage** — a `.techne/` directory per project that holds:
   - Deterministic context packs (project digest, file roles, commands, risk boundaries)
   - Wikilink knowledge graph rebuilt on every `CONCLUDE`
   - RL event log, reward ledger, and mistake ledger
   - Hermes plugin (`phase_guard`) that blocks writes outside the active pipeline

3. **The GRPO/RL Engine** — reinforcement learning that compares pipeline runs, scores skills and prompts, computes group-relative advantages, and proposes framework skill edits for human ratification.

> **Techne never calls a model and never needs an API key.** Your agent runs every reasoning turn. Techne supplies the deterministic spine: gates, scoring, memory writes, and RL proposals.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      HOST (Planner)                          │
│                                                              │
│  • Holds session context and intent                          │
│  • Writes precise tickets (OBJECTIVE / CONSTRAINTS)         │
│  • Delegates via MODE dispatch                               │
│  • Verifies reports before closing tickets                   │
└────────────────────────────┬─────────────────────────────────┘
                             │ ./next phase artifacts
                             │ (.techne/loop/recall.txt, etc.)
                             ▼
┌──────────────────────────────────────────────────────────────┐
│                      TECHNE (Engine)                         │
│                                                              │
│  ./next loop:                                                │
│    • RECALL  →  .techne/loop/recall.txt    (gate: WORKSHOP_) │
│    • IMPLEMENT → .techne/loop/diff.txt     (gate: diff hdrs) │
│    • VERIFY   →  .techne/loop/test_output.txt (gate: SHA)    │
│    • CONCLUDE →  .techne/loop/conclude.txt  (gate: git)     │
│    • DONE     →  (task closed)                              │
│                                                              │
│  Enforcement stack (live on every run):                     │
│    phase_guard  — blocks writes without active pipeline      │
│    audit_chain  — tamper-evident .techne/audit/chain.jsonl │
│    watchdog    — cron detects stalled/tampered pipelines   │
│                                                              │
│  post_run_evolve():                                          │
│    • RL reward → wikilink rebuild → context amortization    │
│    • Batch mode: TrajectoryQueue for rl_batch_size > 1      │
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
- **Techne** = execution engine. Runs `./next` phases, enforces gates, scores, records memory. Calls no models.

---

## The ./next Loop

### Primary Pipeline: 5-Phase ./next Loop

```
RECALL → IMPLEMENT → VERIFY → CONCLUDE → DONE
```

Every task passes through every phase. Phases are never skipped — not even for one-liners.

| Phase | Artifact | What it does | Gate |
|-------|----------|-------------|------|
| **RECALL** | `.techne/loop/recall.txt` | Search wikilink graph + ledger for relevant context, past mistakes, decisions | `WORKSHOP_CONTEXT:` header required |
| **IMPLEMENT** | `.techne/loop/diff.txt` | Unified diff for all file changes | `@@`/`--- ` diff markers required |
| **VERIFY** | `.techne/loop/test_output.txt` | Run tests, capture real stdout | SHA gate checks pass indicators |
| **CONCLUDE** | `.techne/loop/conclude.txt` | Honcho write-back, git commit, proof lines; triggers `post_run_evolve()` | Git state check for `.techne/context` |
| **DONE** | — | Task closed; wikilink graph rebuilt | — |

### Phase Modes

| Mode | RECALL | CONCLUDE | Context rebuild | Use for |
|------|--------|----------|-----------------|---------|
| `full` (default) | ✅ | ✅ | ✅ | All code changes |
| `fast` | ❌ | ❌ | ❌ | Review-only, no file edits |

**There is no `fast` escape for code changes.** A typo fix still goes through the full pipeline.

### Phase Artifact Paths

Each phase writes its artifact to `.techne/loop/`:

```
.techne/loop/
├── state.json        # current task + phase (source of truth)
├── recall.txt        # RECALL output
├── diff.txt          # IMPLEMENT output (unified diff)
├── test_output.txt   # VERIFY output (real test stdout)
└── conclude.txt      # CONCLUDE output
```

### Running the Loop

```bash
# Initialize (one-time per project)
mkdir -p .techne/loop .techne/audit .techne/memory .techne/events
echo '{"task_id":"my-task-1","phase":"RECALL"}' > .techne/loop/state.json

# Advance one phase (after writing the current phase's artifact)
python3 /path/to/techne/scripts/next.py

# Or symlink for convenience
ln -s /path/to/techne/scripts/next.py ./.next
./next
```

### Legacy Pipeline (Deprecated)

The old 11-phase `OrchestratorLoop` still exists in `harness/orchestrator_loop.py` but is **not recommended**. Use `./next` for all new work.

The 11-phase sequence was: `RECALL → IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → EVAL → RETRO → CONCLUDE → REFRESH_CONTEXT → DONE`

---

## Enforcement Stack

Three independent enforcement mechanisms work together to guarantee pipeline integrity.

### phase_guard

`plugins/techne/plugin.yaml` + `harness/plugins/phase_guard.py` — blocks writes that violate phase discipline:

- **No active pipeline**: Blocks all writes to project source files. Agent must call `./next` first.
- **Wrong phase artifact**: Blocks writes to other phase's artifact files.
- **Audit dir**: Blocks all writes to `.techne/audit/` — the agent must not touch the audit trail.
- **Blocked log**: Every blocked write is appended to `.techne/audit/blocked.log`.

The Hermes plugin (`pre_tool_call` hook) activates automatically when a `.techne/` directory is detected in the project root.

### Audit Chain

`.techne/audit/chain.jsonl` — a tamper-evident, append-only log with SHA-256 hash chaining:

- Every entry seals with `entry_hash = SHA256(seq + timestamp + task_id + phase + gates + summary + prev_hash)`
- First entry uses `prev_hash = "0" * 64` (genesis)
- Tampering with any past entry breaks the chain and is detectable by `watchdog`
- Each pipeline phase produces exactly one audit entry

### Watchdog

`scripts/watchdog.py` — runs via cron every 5 minutes:

```
*/5 * * * * cd /project && python3 /path/to/techne/scripts/watchdog.py
```

Exit codes:
| Code | Meaning |
|------|---------|
| 0 | Healthy |
| 1 | **STALL** — `state.json` not updated within `phase_timeout_min` (default 30 min) |
| 2 | **TAMPER** — `chain.jsonl` hash chain is broken |
| 3 | **SKIP** — Phase advanced but no matching audit entry |
| 4 | **ORPHAN** — No `state.json` but recent task dirs exist |

### Enforcement Eval Suite

`tests/evals/graders/enforcement_grader.py` — evaluates phase_guard, audit_chain, and watchdog behavior deterministically. Run with:

```bash
python3 tests/evals/run_evals.py enforcement
```

---

## Context Amortization

Context amortization means **no agent starts with a blank repo**. Every `RECALL` begins with a deterministic context pack derived from the current repo state — no model call, no tokens spent on rediscovery.

### Context Files (`.techne/context/`)

| File | What it contains | Generated by |
|------|-----------------|-------------|
| `project_digest.md` | Project name, detected stack, top-level layout, README lead | `context_build.py` |
| `commands.md` | Test/build/lint commands from `package.json`, `Makefile`, `pyproject.toml` | `context_build.py` |
| `file_roles.md` | Top-level dirs grouped with one-line roles + file counts | `context_build.py` |
| `risk_boundaries.md` | HITL boundaries + sensitive areas detected in the tree | `context_build.py` |
| `*.CONTEXT.md` | Human-written or enriched context (preserved across runs) | Human or enrichment layer |

### How It Works

```
ensure_context()  ←  called at RECALL start
  • Computes context hash from repo state (stack, top-level files, commands)
  • If hash changed since last run → regenerates the 4 deterministic files
  • If hash unchanged → uses cached files (zero re-derivation)
  • Human-owned files (risk_boundaries.md, docs/) are NEVER overwritten

conclude_context()  ←  called at DONE
  • Updates docs index for files changed in this run
  • Marks context as current for next ensure_context() cycle
```

### Project-Root Awareness

All scripts (`next.py`, `phase_guard`, `watchdog`, `audit_chain`) walk up from `cwd` to find the nearest `.techne/` directory. This means the project root is wherever `.techne/` lives — no configuration required.

---

## Wikilink Knowledge Graph

`scripts/knowledge_graph.py` — connects mistakes, ledger entries, tasks, files, and subsystems into a queryable graph. Rebuilt on every `CONCLUDE` (via `post_run_evolve` + `./next CONCLUDE`).

### Node Types

Files, tasks, mistakes, ledger entries, subsystems, and skills are all nodes. Edges encode relationships (file → subsystem, task → file, mistake → related task).

### Query Commands

```bash
python3 scripts/knowledge_graph.py status              # node/edge counts, RL summary
python3 scripts/knowledge_graph.py phases             # phase outcome breakdown
python3 scripts/knowledge_graph.py mistakes           # mistake recurrence
python3 scripts/knowledge_graph.py skill <name>      # skill graph
python3 scripts/knowledge_graph.py file <path>        # file graph (project mode)
python3 scripts/knowledge_graph.py search <term>      # search nodes
python3 scripts/knowledge_graph.py rewards            # RL reward history
```

### Techne's Own Graph

The techne repo's own graph has **4000+ nodes**. Run `python3 scripts/knowledge_graph.py status` in the techne repo to explore it.

---

## EVAL System

`harness/evaluator.py` — deterministic scoring after every pipeline completion (pass or fail). No model call.

### 8 Dimensions (120 raw points → weighted 100pt scale)

| Dimension | Raw max | Weight | Focus |
|-----------|---------|--------|-------|
| Gate Compliance | 20 | 1.2 | Phase gates passed without workaround |
| Verification Integrity | 20 | 1.2 | Tests ran and actually pass |
| Process Discipline | 20 | 1.0 | All phases followed in order |
| Review Quality | 20 | 1.0 | Diff review thoroughness |
| Retro Value | 20 | 0.8 | Retrospective insight quality |
| RL/GRPO Contribution | 15 | 0.8 | RL event log completeness |
| Enforcement Compliance | 15 | 1.0 | phase_guard blocks respected |
| Execution Efficiency | 10 | 0.6 | Pipeline completed in reasonable time |

### Grades

| Score | Grade |
|-------|-------|
| ≥90 | EXCELLENT |
| ≥75 | GOOD |
| ≥60 | FAIR |
| ≥40 | POOR |
| <40 | CRITICAL |

### Regression Detection

Compares last N eval scores against N previous runs. Severity: `none` / `warning` / `critical`.

### Threshold Gating

- `PASS` — score ≥ 75
- `WARN` — score 60–74 (logged but task continues)
- `BLOCK` — score < 60 (requires human sign-off to proceed)

### Eval Suites

Run all evals or pick a suite:

```bash
python3 tests/evals/run_evals.py              # all suites
python3 tests/evals/run_evals.py router       # skill routing
python3 tests/evals/run_evals.py gates        # gate enforcement
python3 tests/evals/run_evals.py intent       # intent classification
python3 tests/evals/run_evals.py pipeline     # ./next loop correctness
python3 tests/evals/run_evals.py rl            # RL/GRPO engine
python3 tests/evals/run_evals.py enforcement   # phase_guard, audit_chain, watchdog
```

Baseline comparison: `tests/evals/` contains baseline expectation files. Current eval suites: **86/87 passing** (1 pre-existing router issue).

---

## GRPO Engine

**GRPO** (Group Relative Policy Optimization) compares multiple pipeline runs to determine which prompts, gates, and skills produce better outcomes.

### How the RL Loop Works

```
┌─────────────────────────────────────────────────────────────┐
│                    GRPO CYCLE                               │
│                                                             │
│  1. CLASSIFY — Group runs by task type (auth, ui, api…)  │
│                    ↓                                        │
│  2. SCORE — EVAL produces 100-point score per run        │
│                    ↓                                        │
│  3. ADVANTAGE — advantage = score - mean(scores_in_group) │
│                 (requires ≥2 runs in group to compute)     │
│                    ↓                                        │
│  4. PROPOSE — High-advantage variants → proposals         │
│               • prompt_evolution: Propose prompt variants   │
│               • grpo: propose_skill_edits() for skills     │
│               • propose_framework_edits() — framework self-improvement │
│               • gate_evolution: Pattern-based gate tweaks   │
│                    ↓                                        │
│  5. RATIFY — Human reviews and approves/rejects            │
│               (via apply_retro.py — never auto-applied)    │
│                    ↓                                        │
│  6. APPLY — Approved changes written to skills/*.md       │
└─────────────────────────────────────────────────────────────┘
```

### Two Comparison Axes

| Axis | What it compares | Key file |
|------|-----------------|----------|
| **Prompt variants** | `v1_strict` vs `v2_pragmatic` vs `v3_contextual` | `.techne/memory/prompt_variants.json` |
| **Skills** | `implementer` vs `diagnose` vs `tdd` vs task-type matches | `skills/*.md` |

### post_run_evolve() — DONE phase hook

Called automatically at `CONCLUDE` (before `DONE`):

1. **RL reward log** — composite score recorded to `.techne/memory/rewards.db`
2. **Wikilink rebuild** — `build_graph()` rebuilds the knowledge graph
3. **Context amortization** — `conclude_context()` finalizes the context pack
4. **GRPO proposals** — staged to `.techne/proposals/` for human ratification

### Batch Mode

When `rl_batch_size > 1` in config, `TrajectoryQueue` holds multiple trajectories for group-relative scoring. The RL event log (`.techne/events/rl.jsonl`) records every RL event for post-hoc analysis.

### Knowledge Graph CLI

```bash
python3 scripts/knowledge_graph.py rewards  # RL reward history from rewards.db
```

### RL Event Log

`.techne/events/rl.jsonl` — every RL cycle event (classify, score, advantage, propose) is appended with a timestamp. Use for audit and regression analysis.

> **Safety clamp:** GRPO proposals never auto-apply. Every proposed change goes through `apply_retro.py` for human ratification.

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
python3 .techne/scripts/context_index.py
```

This builds `.techne/generated/context_index.json` — the searchable graph for RECALL.

### 5. Verify

```bash
cd techne/
python3 tests/test_workshop_foundation.py      # expect 5/5
python3 tests/test_orchestrator_driver.py      # expect 52/52
```

### 6. Your first task

```bash
# Create the task state (phase = RECALL)
mkdir -p .techne/loop .techne/audit .techne/memory .techne/events
echo '{"task_id":"my-task-1","phase":"RECALL"}' > .techne/loop/state.json

# Write your RECALL artifact
echo "WORKSHOP_CONTEXT:
- File: src/auth.py (authentication module)
- Past mistake: forgot to hash passwords in A7
- Decision: use argon2 for password hashing" > .techne/loop/recall.txt

# Advance to IMPLEMENT
python3 /path/to/techne/scripts/next.py

# Write your IMPLEMENT artifact (unified diff)
echo "--- a/src/auth.py
+++ b/src/auth.py
@@ -10,6 +10,8 @@ def hash_password(password):
+    import argon2
+    return argon2.PasswordHasher().hash(password)" > .techne/loop/diff.txt

# Advance to VERIFY
python3 /path/to/techne/scripts/next.py

# Write VERIFY output (real test run)
python -m pytest tests/auth_test.py > .techne/loop/test_output.txt

# Advance to CONCLUDE
python3 /path/to/techne/scripts/next.py

# Write CONCLUDE artifact
echo "Git commit: a1b2c3d
Proof lines: src/auth.py:12-13" > .techne/loop/conclude.txt

# Advance to DONE (triggers post_run_evolve)
python3 /path/to/techne/scripts/next.py
```

---

## Project Status

### Current State

| Area | Status |
|------|--------|
| Pipeline | 781 tests, `./next` loop primary, 5 phases |
| Enforcement | phase_guard + audit_chain + watchdog all live |
| RL | Closed loop with framework skills, batch mode, event log |
| EVAL | 8 dimensions, 6 eval suites, baseline comparison |
| Context | Amortization deterministic, project-root-aware |
| Wikilinks | Rebuilt on every DONE, 4000+ nodes in techne's own graph |
| Eval suites | 86/87 passing (1 pre-existing router issue) |

### What Got Built

**Framework Skills Self-Improvement:**
- `propose_framework_edits()` — GRPO can propose edits to Techne's own skill files
- Wikilink rebuild on every DONE via `post_run_evolve`
- `TrajectoryQueue` for batch RL (rl_batch_size > 1)
- RL event log at `.techne/events/rl.jsonl`

**Production Enforcement:**
- phase_guard: Hermes plugin, `pre_tool_call` hook, auto-activation on `.techne/` detection
- Audit chain: SHA256 hash-chained `chain.jsonl`
- Watchdog: cron-detectable stall/tamper/skip/orphan conditions
- Blocked writes: `.techne/audit/blocked.log`

**Context Amortization:**
- `ensure_context()` at RECALL — deterministic, zero model call
- `conclude_context()` at DONE — finalizes context for next cycle
- Context hash freshness tracking — regenerates only when repo state changes
- Human-owned files preserved (risk_boundaries.md, docs/)

---

## Documentation Map

| Document | What it's for |
|----------|---------------|
| **[SKILL.md](SKILL.md)** | **Start here.** Skill router + full pipeline reference |
| **[INSTALL.md](INSTALL.md)** | Install options, verification steps, Pipeline API |
| **[COMPONENTS.md](COMPONENTS.md)** | Every skill, agent, gate, and module catalog |
| **[docs/host-integration-guide.md](docs/host-integration-guide.md)** | **Host agent contract.** Two-layer architecture, dispatch protocol |
| **[docs/enforcement-operations.md](docs/enforcement-operations.md)** | phase_guard, audit_chain, watchdog operations |
| **[docs/plans/2026-06-23-production-enforcement.md](docs/plans/2026-06-23-production-enforcement.md)** | Enforcement design and implementation plan |
| **[scripts/next.py](scripts/next.py)** | The `./next` loop driver |
| **[scripts/knowledge_graph.py](scripts/knowledge_graph.py)** | Wikilink graph query CLI |
| **[harness/context_build.py](harness/context_build.py)** | Context amortization (ensure_context, conclude_context) |
| **[harness/evaluator.py](harness/evaluator.py)** | 8-dimension EVAL system |
| **[harness/plugins/phase_guard.py](harness/plugins/phase_guard.py)** | phase_guard enforcement logic |

### Key References

```
references/
├── orchestrator-recall-workshop-contract.md   # RECALL output contract
├── orchestrator-pipeline-fixes.md            # RECALL/CONCLUDE/RETRO fixes
├── orchestrator-pipeline-modification.md     # Adding new phases
├── rl-pipeline-notes.md                      # Field notes from real runs
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
