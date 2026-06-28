# Host Integration Guide — Techne Operational Contract

> **Audience:** You, the host agent (Claude Code, Hermes, OpenCode, or any LLM loop).
> You are **not** a human reading this. This is your operational contract with Techne.
> Read it once at integration time, refer to the Quick Reference Card (Section 6) daily.
>
> **Architecture version:** 5-phase `./next` loop + two-layer plugin model (2026-06).
> The legacy 11-phase `OrchestratorLoop` is deprecated — see §7 if you hit old references.

---

## 1. Architecture — Two Layers, Never One

```
┌─────────────────────────────────────────────────────────┐
│  HOST (you) = Planner / Dispatcher                      │
│  Role: plan, dispatch, verify, synthesize               │
│  Reads: SKILL.md, this guide, phase reports             │
│  Produces: tickets, verification decisions              │
├─────────────────────────────────────────────────────────┤
│  TECHNE = Engine (two cooperating layers)               │
│                                                          │
│  • Enforcement layer  — blocks bad writes at the        │
│    tool-call layer, logs the audit chain, writes RL     │
│    events. Runs on EVERY tool call, always.             │
│      Hermes:  plugins/techne-plugin/                    │
│      Claude Code: hooks/phase_guard_hook.py            │
│      Shared logic: harness/plugins/phase_guard.py      │
│                                                          │
│  • Orchestration layer — drives the 5-phase loop,       │
│    enforces retry caps, surfaces HITL, writes handoff.  │
│      Hermes:  plugins/orchestrator/                     │
│      Any host: scripts/next.py via the `techne` CLI     │
└─────────────────────────────────────────────────────────┘
```

**Hard separation:** You (host) never write implementation code directly. Techne never
plans or dispatches. The two roles are a compile-time separation, not a suggestion.

- You = **planner + dispatcher**: you hold the full session context, write tickets,
  delegate to subagents, verify reports, advance the loop.
- Techne = **execution spine**: phase gates, enforcement, audit chain, RL events,
  GRPO proposals, structured memory. **It calls no models and needs no API key.**

> **Reference:** [COMPONENTS.md](../COMPONENTS.md) catalogs every skill, gate, and
> harness module Techne ships. [GRAND-PLAN-HERMES.md](plans/GRAND-PLAN-HERMES.md) is
> the live architecture spec for the two-layer model.

---

## 2. Install (for the Host)

### 2.1 Get the code

| Method | When to use |
|--------|-------------|
| **git submodule** | Your project is a git repo and you want pinned versioning |
| **clone standalone** | You're evaluating or developing Techne itself |
| **vendor (copy folder)** | You want zero external dependency at runtime |

### 2.2 Install the CLI

The `techne` CLI is the primary operating surface — it replaces the old
hand-assembled `echo '{...}' > state.json` ritual.

```bash
pip install -e /path/to/techne/        # gives you `techne` on PATH
techne --help                          # init / next / status / doctor / gate / handoff / proposals
```

If you can't install the CLI, fall back to invoking the script directly:
`python3 /path/to/techne/scripts/next.py` (and a symlink `ln -sf .../next ./next`).

### 2.3 Register the skill entry

Point your agent at `SKILL.md` as its first-read entry point every task — it is the
router that maps task keywords to skill cards and states the pipeline contract.

```yaml
- name: techne
  path: techne/SKILL.md          # or .hermes/skills/techne/SKILL.md
  always_read: true
```

### 2.4 Register the enforcement layer

- **Hermes:** register `plugins/techne-plugin/` (and `plugins/orchestrator/`) in
  `.hermes/config.yaml`. The plugin auto-activates when `.techne/` is present.
- **Claude Code:** wire `hooks/phase_guard_hook.py` as a `PreToolUse` hook in
  `.claude/settings.json` (matcher: `Write|Edit|MultiEdit|NotebookEdit`).

### 2.5 Configure per project

Create `.techne/config.yaml` at the target project root:

```yaml
project_name: my-project
context_glob: "src/**/*.{ts,svelte,py}"
generated_dir: .techne/generated
scope_limit: 10          # max files an IMPLEMENT diff may touch before warning
```

### 2.6 Verify

```bash
cd /path/to/techne/
python3 -m pytest tests/ -q       # full suite
techne doctor                     # health check (see §6)
```

---

## 3. The Mandatory Pipeline Contract

### 3.1 The rule

> **ALL code changes go through the pipeline. Zero exceptions.**

Every file edit, every config tweak, every one-line typo fix — pipeline or nothing.
There is **no hotfix exception** and **no `phase_mode=fast` escape for code changes.**

### 3.2 The flow (5 phases)

```
RECALL → IMPLEMENT → VERIFY → CONCLUDE → DONE
```

| Phase | Artifact (`.techne/loop/`) | What happens |
|-------|----------------------------|--------------|
| **RECALL** | `recall.txt` | Search context pack + knowledge graph + ledger. Declare `FILE_SCOPE`. |
| **IMPLEMENT** | `diff.txt` | Subagent produces a unified diff. Hashline + file-scope gates run. |
| **VERIFY** | `test_output.txt` | Run tests, capture real stdout. Non-empty + explicit count required. |
| **CONCLUDE** | `conclude.txt` | Retro markers + verify reference + HONCHO id. Triggers wisdom extraction, wikilink rebuild, context refresh, GRPO proposal surfacing. |
| **DONE** | — | Task closed. |

### 3.3 What you submit, what Techne checks

| Phase | You submit | Techne's gate checks |
|-------|------------|----------------------|
| RECALL | context-pack references + `FILE_SCOPE:` line + knowledge-graph evidence | `_check_recall_gates` — context ref present, FILE_SCOPE declared (writes `file_scope.json`), KG consulted |
| IMPLEMENT | unified diff (`@@` / `--- ` markers) | `_check_implement_gates` — hashline (context lines match real file), file-scope (only declared files), no forbidden patterns |
| VERIFY | real test stdout | `_check_verify_gates` — non-empty suite (not `0 passed` / `ran 0 tests`), explicit `N passed` count |
| CONCLUDE | conclusion text | `_check_conclude_gates` — retro markers (`DECISION:`/`LESSON:`/`DISCIPLINE:`), verify reference, ≥150 chars, valid `HONCHO:` id |

Gate functions live in `scripts/next.py`. They read the real filesystem — an agent
**cannot self-report a pass.**

### 3.4 Running the loop

```bash
techne init <task-id>     # scaffold .techne/loop/ + write state.json (phase=RECALL)
# write recall.txt (WORKSHOP_CONTEXT + FILE_SCOPE + KG evidence)
techne next               # gates RECALL → advance to IMPLEMENT
# write diff.txt
techne next               # gates IMPLEMENT → advance to VERIFY
# run tests, write test_output.txt
techne next               # gates VERIFY → advance to CONCLUDE
# write conclude.txt
techne next               # gates CONCLUDE → DONE (fires post-run evolution)
```

> **Note:** `./next --init` does **not** exist. Use `techne init <task-id>`. Never edit
> `state.json` by hand to skip a blocked gate — that is a pipeline violation. If a gate
> blocks legitimate work, report the gate stats to the user and let them decide.

### 3.5 Documentation-only tasks

Creating `.techne/context/*.md` files produces an empty `git diff` (`.techne/` is
gitignored). The IMPLEMENT gate detects this and switches to doc-task mode, accepting
the context files as the deliverable. No manual state edits needed.

### 3.6 Phase-mode reference

| `phase_mode` | RECALL | CONCLUDE | Use for |
|--------------|--------|----------|---------|
| `full` (default) | ✅ | ✅ | All code changes |
| `fast` | ❌ | ❌ | Review-only tasks that produce **zero file modifications** |

---

## 4. Host Dispatch Protocol

### 4.1 The cycle

```
INTAKE → CLASSIFY → PLAN → TICKET → DISPATCH → VERIFY REPORT →
UPDATE PLAN → next ticket or DONE → SYNTHESIZE
```

You hold context, write precise tickets, delegate execution, verify reports, and
maintain the running plan. Subagents are stateless between dispatches — you are not.

### 4.2 Ticket schema — mandatory for every `delegate_task` call

```yaml
MODE: [EXPLORE | SCOUT | IMPLEMENT]
OBJECTIVE: <1-2 sentences, single outcome>
CONTEXT: <curated file paths/excerpts — NEVER the whole repo>
CONSTRAINTS: <architecture rules, layer boundaries, do-not-touch>
DONE_WHEN: <concrete, checkable verification criteria>
OUTPUT_FORMAT: <diff | report | both>
FIX_OF: <optional — fill for fix tickets. When present, the subagent's report
         MUST include: root cause, the specific failure fixed, regression risk>
```

**Context hygiene:** over-including wastes budget; under-including produces hallucinated
wiring. Curate tightly.

### 4.3 The three modes

| Mode | Purpose | When to use |
|------|---------|-------------|
| **EXPLORE** | Build situational awareness of the codebase (read-only) | You lack an accurate current map of the relevant files |
| **SCOUT** | External research/feasibility for unknown APIs or patterns | The answer isn't in the codebase |
| **IMPLEMENT** | ALL code changes — net-new, wiring, bug fixes, config edits | Something must be built or modified |

### 4.4 Model routing for subagents

Subagents inherit the parent's model/provider. Suggested tiers:

| Role | Suggested model tier |
|------|---------------------|
| Implementer / verifier | Strongest coding model |
| Recall / context work | Capable large-context model |
| Retro / summary | Cheapest fast model |

### 4.5 Verify by report, not by re-implementing

1. **Read the report** — does it meet the ticket's `DONE_WHEN`?
2. **Run tests** — confirm nothing existing broke.
3. **Tests fail due to intentional contract change?** → update test assertions yourself.
   This is verification, not implementation.
4. **Tests fail due to an implementation bug?** → new IMPLEMENT ticket with `FIX_OF`.
   Do **not** patch it yourself.
5. **Report ambiguous?** → re-ticket with tighter constraints. One retry max.

---

## 5. Consequences of Breaking the Contract

### 5.1 Direct edits outside the pipeline

A direct edit means: no RECALL (graph/ledger never consulted), no VERIFY gate, no
CONCLUDE (no wisdom extraction, no structured memory, no git commit with task context),
and **zero learning signal for GRPO** — the work is invisible to the improvement loop.

### 5.2 No hotfix bypass

When pressure is highest (frustrated user, near deadline) is exactly when the pipeline
matters most. The VERIFY and CONCLUDE gates exist to catch the half-baked solutions
produced when rushing.

### 5.3 Self-enforcement

- **Enforcement layer** blocks wrong-artifact and out-of-phase writes at the tool-call
  layer (Hermes plugin / CC PreToolUse hook).
- **Pre-commit hook (recommended):** reject commits whose message lacks a `task_id:`
  reference — every pipeline task ends with a CONCLUDE commit.

### 5.4 When you catch yourself

If you realize mid-edit that you skipped the pipeline: **stop.** `techne init` a task for
the work, drive it through the loop, and commit via CONCLUDE.

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
RECALL → IMPLEMENT → VERIFY → CONCLUDE → DONE
```

| Phase | You submit | Techne checks |
|-------|------------|---------------|
| RECALL | context refs + `FILE_SCOPE:` + KG evidence | context ref, FILE_SCOPE (writes file_scope.json), KG consulted |
| IMPLEMENT | unified diff | hashline (context matches file), file-scope, no forbidden patterns |
| VERIFY | test stdout | non-empty suite, explicit `N passed` |
| CONCLUDE | conclusion | retro markers, verify ref, ≥150 chars, valid HONCHO id |
| DONE | — | task closed; post-run evolution fires |

### `techne` CLI

| Command | Effect |
|---------|--------|
| `techne init <id>` | Scaffold `.techne/loop/` + write `state.json` (RECALL) |
| `techne next` | Run current-phase gates, advance on pass |
| `techne status` | Current phase, blocked-log summary, RL health |
| `techne doctor` | Health check (CC + Hermes setup, audit chain, context freshness, proposals) |
| `techne gate <name> <target>` | Run a named gate standalone (`hashline` / `forbidden` / `audit`) |
| `techne handoff` | Write a continuity doc for resuming in a new session |
| `techne proposals` | Review pending GRPO proposals |

### Verification Checklist (after every dispatch)

```
[ ] Report meets DONE_WHEN?
[ ] Existing tests pass?
[ ] Test failure = intentional contract change? → fix assertions
[ ] Test failure = implementation bug? → IMPLEMENT ticket with FIX_OF, do not patch
[ ] FIX_OF set? → report includes root cause + regression risk
[ ] Report ambiguous? → re-ticket (max 1 retry)
[ ] Ticket log updated?
```

### Data flow reminder

```
You (host): plan → ticket → delegate_task → read report → verify → next ticket
Techne:    RECALL → IMPLEMENT → VERIFY → CONCLUDE → DONE
           (+ enforcement layer on every write, + post-run evolution at DONE)
```

**You plan, Techne builds. Never the two in one.**

---

## 7. Migrating From the Legacy 11-Phase Loop

If you find references to the old pipeline, here is the mapping:

| Legacy (11-phase `OrchestratorLoop`) | Current (5-phase `./next`) |
|---|---|
| RECALL | RECALL (now also: FILE_SCOPE + KG gate) |
| IMPLEMENT | IMPLEMENT (now: hashline + file-scope gate) |
| CONTEXT_GUARD | folded into RECALL context-ref gate + DONE context refresh |
| CRITIQUE / REVIEW | moved to skills/subagent review, not a pipeline phase |
| VERIFY | VERIFY (now: non-empty + count gate) |
| EVAL | runs at DONE via post-run evolution (no separate phase) |
| RETRO | retro markers required in CONCLUDE; `_persist_retro` runs at CONCLUDE→DONE |
| CONCLUDE | CONCLUDE (now: retro markers + verify ref + HONCHO gate) |
| REFRESH_CONTEXT | runs automatically at CONCLUDE→DONE (`conclude_context`) |
| DONE | DONE |

The `OrchestratorLoop` (`harness/orchestrator_loop.py`) still exists for the model-backed
RL driver but is **not** the production path. Use the `techne` CLI / `./next` for all
host-driven work.
