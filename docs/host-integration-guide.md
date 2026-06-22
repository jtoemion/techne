# Host Integration Guide — Techne Operational Contract

> **Audience:** You, the host agent (Claude Code, Hermes, OpenCode, or any LLM loop).
> You are **not** a human reading this. This is your operational contract with Techne.
> Read it once at integration time, refer to the Quick Reference Card (Section 6) daily.

---

## 1. Architecture — Two Layers, Never One

```
┌─────────────────────────────────────────────────────────┐
│  HOST (you) = Receptionist                              │
│  Role: plan, dispatch, verify, synthesize               │
│  Reads: SKILL.md, this guide, ticket reports            │
│  Produces: tickets, verification decisions              │
├─────────────────────────────────────────────────────────┤
│  TECHNE = Workshop                                      │
│  Role: execute pipeline phases, enforce gates,          │
│        score, record memory, run GRPO                   │
│  Reads: task tickets, project context, skills/*.md      │
│  Produces: diffs, reports, eval scores, retro proposals │
└─────────────────────────────────────────────────────────┘
```

**Hard separation:** You (host) never write implementation code. Techne never plans
or dispatches. The two roles are a compile-time separation, not a suggestion.

- You = **planner + dispatcher**: you hold the full session context, write tickets,
  delegate to subagents, verify reports, and maintain the ticket log.
- Techne = **execution layer**: the pipeline phases, gates, intent reasoning,
  eval scoring, GRPO reinforcement, and structured memory. It calls no models
  and needs no API key — it is a deterministic spine your agent runs through.

> **Reference:** [COMPONENTS.md](../COMPONENTS.md) catalogs every skill, agent,
> gate, and harness module Techne ships. Read it before first use — it flags the
> conflict surfaces (Next.js/TypeScript stack assumptions, generic skill names,
> root-file ownership) that will block you at runtime.

---

## 2. Install (for the Host)

### 2.1 Get the code

Pick one method (see [INSTALL.md §2](../INSTALL.md) for full commands):

| Method | When to use |
|--------|-------------|
| **git submodule** | Your project is a git repo and you want pinned versioning |
| **clone standalone** | You're evaluating or developing Techne itself |
| **vendor (copy folder)** | You want zero external dependency at runtime |

### 2.2 Register the skill entry

Point your agent at `SKILL.md` as its first-read entry point every task.
This is the router — it maps task keywords to skill cards in `skills/`.

If your host uses a `SKILL.md`-style entry (Hermes does), add this reference
to your host's skill config:

```yaml
- name: techne
  path: techne/SKILL.md          # or ~/.hermes/skills/techne/SKILL.md
  always_read: true
```

If your host has its own router, see [COMPONENTS.md §Name & Trigger Collisions](../COMPONENTS.md)
for the full overlap table — 8 Techne skill names may shadow your host's.

### 2.3 Configure per project

Create `.techne/config.yaml` at the target project root:

```yaml
project_name: my-project
context_glob: "src/**/*.{ts,svelte,py}"
generated_dir: .techne/generated
```

### 2.4 Bootstrap the workshop graph

```bash
cd your-project/
python .techne/scripts/context_index.py
```

This scans `context_glob` and builds `.techne/generated/context_index.json` —
the searchable graph the RECALL phase uses to build context packs.

### 2.5 Verify

```bash
cd /path/to/techne/
python tests/test_workshop_foundation.py
```

Expect **5/5 pass**. If the stack-level gates don't match your project
(Next.js+TypeScript gates on a Python project, for example), see
[COMPONENTS.md §Adapting to your stack](../COMPONENTS.md) to disable or replace
them **before** running any pipeline task.

---

## 3. The Mandatory Pipeline Contract

### 3.1 The rule

> **ALL code changes go through the pipeline. Zero exceptions.**

Every file edit, every config tweak, every one-line typo fix — pipeline or
nothing. The pipeline is not a suggestion, not a best practice, not a
preference. It is the **only way code enters the repo**.

### 3.2 The flow

```
RECALL → IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY →
EVAL → RETRO → CONCLUDE → REFRESH_CONTEXT → DONE
```

| Phase | What happens |
|-------|--------------|
| **RECALL** | Search Honcho + workshop graph for relevant context, mistakes, past decisions |
| **IMPLEMENT** | Subagent produces a unified diff through the harness |
| **CONTEXT_GUARD** | Checks scope, docs/context/Honcho punch list |
| **CRITIQUE** | Risk analysis; can BLOCK_HITL for human judgment |
| **REVIEW** | Read-only correctness + security check; HARD_FAIL blocks pipeline |
| **VERIFY** | Run tests, capture real output (SHA gate checks pass indicators) |
| **EVAL** | Deterministic 100-point score (5 dimensions) |
| **RETRO** | 7-question structured retrospective; ≥100 chars + phase references |
| **CONCLUDE** | Honcho write-back, git commit, punch-list closure proof |
| **REFRESH_CONTEXT** | Rebuild workshop graph, update generated docs |
| **DONE** | Task closed |

### 3.3 What you do, what Techne does

| Step | Who |
|------|-----|
| Create task via `task_db.create_task()` | **You (host)** |
| Dispatch IMPLEMENT via `delegate_task` | **You (host)** |
| Produce diff through pipeline phases | **Techne (subagent)** |
| Run deterministic gates on diff/output | **Techne (harness)** |
| Score the run, write eval history | **Techne (harness)** |
| Read the report, verify it | **You (host)** |
| Re-ticket or advance | **You (host)** |

### 3.4 Even one-liners

A typo fix does **not** get a shortcut. The correct sequence:

1. `db.create_task(title="Fix typo in login page", tags=["p1"])`
2. `delegate_task` with ticket (MODE: IMPLEMENT, OBJECTIVE: fix typo, ...)
3. Subagent runs RECALL → IMPLEMENT → ... → DONE
4. You read the report, verify, close

There is no `phase_mode="fast"` escape for code changes. `phase_mode="fast"`
skips RECALL and CONCLUDE and is only valid for **review-only** tasks that
produce zero file modifications.

### 3.5 Phase-mode reference

| `phase_mode` | RECALL | CONCLUDE | Use for |
|--------------|--------|----------|---------|
| `full` (default) | ✅ | ✅ | All code changes |
| `fast` | ❌ | ❌ | Review-only, no file edits |

---

## 4. Host Dispatch Protocol (Receptionist Pattern)

### 4.1 The cycle

```
INTAKE → CLASSIFY → PLAN → TICKET → DISPATCH → VERIFY REPORT →
UPDATE PLAN → next ticket or DONE → SYNTHESIZE
```

You are the **Receptionist**. Your job is to hold context, understand intent,
write precise tickets, delegate execution, verify reports, and maintain the
running plan. Subagents are stateless between dispatches — you are not.

> **Reference:** See `receptionist/SKILL.md` for the full Receptionist
> dispatch pattern, prime directives, and verification protocol.

### 4.2 Ticket schema — mandatory for every `delegate_task` call

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

**Context hygiene:** Free models have small context windows. Over-including
wastes budget; under-including produces hallucinated wiring. Curate tightly.

### 4.3 The Three Modes (post-P5.1 collapse)

The Receptionist dispatches in exactly three modes:

| Mode | Purpose | When to use |
|------|---------|-------------|
| **EXPLORE** | Build situational awareness of the current codebase | You don't have an accurate, current map of relevant files |
| **SCOUT** | External research/feasibility for unknown APIs or approaches | The answer isn't in the codebase |
| **IMPLEMENT** | ALL code changes — net-new, wiring, bug fixes, config edits | Something needs to be built or modified; BUILD, DEBUGGING absorbed here |

**FIX_OF field:** Set it on any ticket that fixes a reproducible failure. The
subagent's report must then additionally include: root cause statement, the
specific failure being fixed, and regression risk note. Omit for net-new work.

### 4.4 `/techne` — explicit pipeline dispatch

Use the `/techne` command (commands/techne.toml) to invoke the full RECALL→DONE
pipeline directly for any task. It is the explicit form of the automatic
dispatch rule in §2.1.

### 4.5 ReceptionistEnforcer gates

`harness/receptionist_enforcer.py` (docs/plans/) enforces Receptionist protocol
rules mechanically — mode exclusivity, one-retry-max, verify-before-close,
FIX_OF requirements. It mirrors `pipeline_enforcer.py` for the dispatch layer.

**It does nothing by itself.** The host must call it explicitly:

- `can_dispatch()` — before every `delegate_task` call
- `mark_verified()` — before every ticket close
- `mark_retry()` — on rejected reports

It is a correctly-tested module sitting unused. Until the host explicitly calls
it, treat its rules as prose guidance — not automated enforcement.

### 4.5 Model routing for subagents

Subagents inherit the parent's model/provider from the host's config.
[COMPONENTS.md §Agents catalog](../COMPONENTS.md) declares suggested models
per phase agent — map these to your host's available models:

| Phase agent | Suggested model tier |
|-------------|---------------------|
| implementer, verifier, reviewer, conductor | Strongest coding model |
| retro | Cheapest fast model |
| recaller, concluder | Capable context model |

### 4.6 Verify by report, not by re-implementing

After each subagent returns:

1. **Read the report** — does it match the ticket's DONE_WHEN?
2. **Run tests** — confirm existing tests still pass
3. **If tests fail due to intentional behavior changes** — update test
   assertions yourself. This is verification, not implementation.
4. **If tests fail due to implementation bugs** — write a new IMPLEMENT
   ticket with `FIX_OF` set. Do **not** patch it yourself.
5. **If the report is ambiguous** — re-ticket with tighter constraints.
   One retry max. Second failure → flag to user.

**Hard rule:** You never edit implementation code directly. The one exception
is updating test assertions for intentional contract changes — that is
verification, and only because the subagent cannot know the old test contract.

### 4.7 Close every loop

- Read every report before the next dispatch
- Update your ticket log after every verification
- One ticket → one report → one verification → next ticket
- Never fire-and-forget

---

## 5. Consequences of Breaking the Contract

### 5.1 Direct edits outside the pipeline

If you edit a file directly without creating a task and driving it through the
pipeline:

- **That task is LOST.** No RECALL phase ran — the workshop graph, Honcho
  context, and mistake ledger were never consulted. No RETRO phase ran — the
  learning signal from that work is gone. No CONCLUDE phase ran — no structured
  memory write, no git commit with task context.
- **No learning signal for GRPO.** GRPO improves from scored pipeline runs.
  A direct edit produces zero eval scores, zero retro proposals, zero prompt
  evolution. It is invisible to the improvement loop.
- **The pipeline IS the workflow.** Quoting `docs/plans/techne-workshop-garage.md`:
  "The pipeline IS the workflow — the host does NOT edit files directly."
  Every edit outside the pipeline is a workflow violation.

### 5.2 Hotfix bypass

There is no hotfix exception. When the pressure is highest (user is frustrated,
deadline is near, "I have hours until presenting") is precisely when the
pipeline is most important. Every pipeline-skipped edit in this codebase's
history produced a new problem that required another fix. The pipeline phases
(CRITIQUE, REVIEW, VERIFY) exist to catch the half-baked solutions produced
when rushing.

### 5.3 Self-enforcement

The host enforces this contract on itself. Two mechanisms:

1. **Pre-commit hook** (recommended): Reject commits whose message lacks a
   `task_id:` reference. Every pipeline task ends with a git commit in
   CONCLUDE — if there's no task_id, the edit bypassed the pipeline.
2. **SKILL.md reference:** Your own `SKILL.md` (§Receptionist Dispatch Pattern)
   spells out the same rule: "Pipeline over manual edits — zero exceptions."

### 5.4 When you catch yourself

If you realize mid-edit that you skipped the pipeline: **stop immediately.**
Create a task for the work you're doing, dispatch it through the pipeline, and
commit via CONCLUDE. Do not commit pipeline-skipped work directly.

---

## 6. Quick Reference Card

### Ticket Schema Template

```
MODE: [EXPLORE | SCOUT | IMPLEMENT]
OBJECTIVE: <single outcome in 1-2 sentences>
CONTEXT: <curated paths + excerpts>
CONSTRAINTS: <boundaries, do-not-touch>
DONE_WHEN: <checkable criteria>
OUTPUT_FORMAT: diff | report | both
FIX_OF: <optional — fill for fix tickets>
```

### Pipeline Phases (in order)

```
RECALL → IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY →
EVAL → RETRO → CONCLUDE → REFRESH_CONTEXT → DONE
```

| Phase | You submit | Techne checks |
|-------|------------|---------------|
| RECALL | Honcho context + workshop retrieval | HONCHO_CONTEXT + WORKSHOP_CONTEXT required |
| IMPLEMENT | Unified diff | All gates + intent L1/L2 |
| CONTEXT_GUARD | Punch list (DOCS/CONTEXT/HONCHO) | Scope audit + closure proof |
| CRITIQUE | Risk analysis + FOLLOW_UP_TASKS | Risk-level parsing |
| REVIEW | Findings (no "HARD_FAIL" in passing review) | HARD_FAIL substring blocks |
| VERIFY | Test stdout | SHA gate (real, unique output) |
| EVAL | — | 100-point automatic score |
| RETRO | 7-question retro (≥100 chars) | Phase references required |
| CONCLUDE | Honcho proof + SHA + docs/context closure | Git state check |
| REFRESH_CONTEXT | — | Workshop graph rebuild |
| DONE | — | Task closed |

### Model Routing

| Agent role | Suggested model | Notes |
|------------|-----------------|-------|
| Conductor / Implementer / Verifier / Reviewer | Strongest coder | `claude-sonnet-4-6` or equivalent |
| Recaller / Concluder | Capable context model | Needs Honcho API access |
| Retro | Cheapest fast model | `claude-haiku-4-5` or equivalent |

### Verification Checklist (after every dispatch)

```
[ ] Read the report — does it meet DONE_WHEN?
[ ] Run existing tests — nothing broken?
[ ] Test failures = intentional contract change? → fix assertions
[ ] Test failures = implementation bug? → IMPLEMENT ticket with FIX_OF, do not patch
[ ] FIX_OF set? → report includes root cause + regression risk note
[ ] Report ambiguous? → re-ticket with tighter constraints (max 1 retry)
[ ] Ticket log updated?
```

### Key commands (from [INSTALL.md](../INSTALL.md))

```bash
# Bootstrap workshop graph
python .techne/scripts/context_index.py

# Verify foundation
python tests/test_workshop_foundation.py      # expect 5/5

# Create a task
python -c "from task_db import TaskDB; db = TaskDB(); \
  t = db.create_task('fix login redirect', '...', tags=['p1'])"

# Run full install verification (no API key needed)
python tests/test_workshop_foundation.py
```

### Data flow reminder

```
You (host): plan → ticket → delegate_task → read report → verify → next ticket
Techne:    RECALL → IMPLEMENT → gates → CONTEXT_GUARD → CRITIQUE → REVIEW →
           VERIFY → EVAL → RETRO → CONCLUDE → REFRESH_CONTEXT → DONE
```

**You plan, Techne builds. Never the two in one.**
