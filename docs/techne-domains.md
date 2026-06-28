# Techne Domains — Architecture Parts

Techne is a disciplined engineering harness built as **two cooperating layers**
(enforcement + orchestration) over a deterministic Python spine. It is not one
thing — it is a set of domains that connect through loop state (`.techne/loop/`),
delegation (host subagents), and deterministic gates (Python). Each domain can be
hardened independently.

> **Architecture version:** 5-phase `./next` loop + two-layer plugin model (2026-06).
> The legacy 11-phase `OrchestratorLoop` is retained only for the model-backed RL
> driver; it is **not** the production path. See [host-integration-guide.md §7](host-integration-guide.md).

```

  ┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
  │  2. Phase /     │     │  3. Loop & Task  │     │  4. Phase Gates  │
  │  Mode System    │     │  State           │     │  + Tooling       │
  └───────┬─────────┘     └────────┬─────────┘     └────────┬─────────┘
          │                        │                        │
          ▼                        ▼                        ▼
  ┌───────────────────────────────────────────────────────────────────┐
  │                 1. Pipeline Core (scripts/ + harness/)            │
  │   next.py ── next_state.py ── gates ── hash_gate ── audit_chain   │
  └───────────┬───────────────────────────────────────────┬───────────┘
              │                                           │
              ▼                                           ▼
  ┌──────────────────┐                          ┌──────────────────┐
  │  5. CLI Surface  │                          │  6. Enforcement  │
  │  (techne_cli/)   │                          │  Layer (plugins/ │
  │                  │                          │  + hooks/)       │
  └──────────────────┘                          └──────────────────┘

  ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
  │  7. Knowledge    │     │  8. GRPO /       │     │  9. Orchestration│
  │  Graph + Memory  │     │  Learning Loop   │     │  Layer (plugins) │
  └──────────────────┘     └──────────────────┘     └──────────────────┘

  ┌───────────────────────────────────────────────────────────────────┐
  │                  10. Skills, Docs & Workshop                       │
  │   skills/ ── docs/ ── plans/ ── README ── retro/                  │
  └───────────────────────────────────────────────────────────────────┘

```

---

## Domain 1: Pipeline Core

**What it is.** The 5-phase loop driver — decides which phase runs next, runs the
phase's gates against real disk artifacts, advances state only on pass, and fires
post-run evolution at DONE.

**Key files.**

| File | Role |
|------|------|
| `scripts/next.py` | **The production loop.** Phase gates (`_check_recall_gates`, `_check_implement_gates`, `_check_verify_gates`, `_check_conclude_gates`), advance logic, audit append, post-run evolution at CONCLUDE→DONE. |
| `scripts/next_state.py` | `LoopState` dataclass + `state.json` read/write. `PHASE_SEQUENCE = RECALL → IMPLEMENT → VERIFY → CONCLUDE → DONE`. |
| `scripts/hash_gate.py` | Hashline gate — validates diff context lines against the real file at IMPLEMENT. |
| `scripts/audit_chain.py` | SHA-256 hash-chained audit log (`append_entry`, `verify_chain`). |
| `harness/gates.py` | Deterministic gate function library (stack-specific gates). |
| `harness/orchestrator_loop.py` | **Legacy** model-backed RL driver. Not the production path. |
| `harness/driver.py` | CLI entry for the legacy model-backed loop. |

**What hardening means.**
- Gate strictness (RECALL FILE_SCOPE/KG, IMPLEMENT hashline/scope, VERIFY non-empty, CONCLUDE retro markers)
- Per-phase retry caps (enforced by the orchestration layer, Domain 9)
- Post-run evolution robustness (wikilink rebuild, context refresh, retro persistence must be best-effort, never block DONE)

**Tests.** `tests/test_cli.py`, `tests/test_scripts/test_hash_gate.py`, `tests/test_orchestrator_driver.py` (legacy driver).

**Connects to.** Domain 4 (gates), Domain 3 (loop state), Domain 6 (enforcement mirrors gate checks), Domain 8 (RL events at DONE).

---

## Domain 2: Phase / Mode System

**What it is.** The classifier that picks `full` vs `fast` mode (and, in the legacy
loop, micro/heavy) based on task shape. Controls whether RECALL and CONCLUDE run.

**Key files.**

| File | Role |
|------|------|
| `harness/pipeline_enforcer.py` | `classify_phase_mode()`, `validate_mode_fit()`, `recommend_mode()`, sensitive-change detection, override telemetry. |

**Modes (current 5-phase loop).**

| Mode | Phases | Use for |
|------|--------|---------|
| `full` (default) | RECALL → IMPLEMENT → VERIFY → CONCLUDE → DONE | All code changes |
| `fast` | IMPLEMENT → VERIFY → DONE | Review-only tasks with zero file modifications |

> The legacy loop also defined `micro` and `heavy` modes; those apply only to the
> deprecated `OrchestratorLoop`.

**What hardening means.**
- Auto-classification accuracy (no false `fast` on real code changes — there is no fast escape for code)
- Edge cases: empty diffs, doc-only tasks, config-only changes
- Override telemetry feeding the learning loop (Domain 8)

**Connects to.** Domain 1 (mode determines phase list), Domain 3 (mode stored on state).

---

## Domain 3: Loop & Task State

**What it is.** The state layer — what phase the current task is in, plus the
durable per-project memory and evidence. If state is corrupt, the loop is blind.

**Key files.**

| File | Role |
|------|------|
| `.techne/loop/state.json` | Source of truth: `task_id`, `phase`, timestamps, `phase_timeout_min`. Managed by `techne`/`./next` — never hand-edited. |
| `.techne/loop/{recall,diff,test_output,conclude}.txt` | Per-phase artifacts the gates read. |
| `.techne/loop/file_scope.json` | Written by the RECALL FILE_SCOPE gate, consumed by the IMPLEMENT file-scope gate. |
| `.techne/audit/chain.jsonl` | Tamper-evident audit trail (one entry per advanced phase). |
| `.techne/audit/blocked.log` | Persistent log of blocked writes. |
| `.techne/events/rl.jsonl` | RL events written by the enforcement layer on every gate outcome. |
| `.techne/memory/` | Ledger, mistakes, retros, rewards, wikilinks, GRPO proposals. |
| `techne/tasks.db` | SQLite task DB (used by the legacy model-backed driver). |

**What hardening means.**
- State integrity (no skipped phases — cross-checked by the audit chain)
- Structured-over-narrative (JSON for machine-resumable state)
- Cold-start resumability (`techne handoff` writes a continuity doc; see Domain 9)

**Connects to.** Every other domain reads or writes loop/memory state.

---

## Domain 4: Phase Gates + Tooling

**What it is.** The deterministic checks that validate each phase artifact, plus the
companion scripts that do data assembly so the model focuses on reasoning.

**Per-phase gates (in `scripts/next.py`).**

| Phase | Gate function | Checks |
|-------|---------------|--------|
| RECALL | `_check_recall_gates` | context-pack reference, `FILE_SCOPE:` declared (writes file_scope.json), knowledge-graph consulted |
| IMPLEMENT | `_check_implement_gates` | hashline (diff context matches real file), file-scope (only declared files), no forbidden patterns, doc-task mode |
| VERIFY | `_check_verify_gates` | non-empty suite (not `0 passed`/`ran 0 tests`), explicit `N passed` count |
| CONCLUDE | `_check_conclude_gates` | retro markers (`DECISION:`/`LESSON:`/`DISCIPLINE:`), verify reference, ≥150 chars, valid `HONCHO:` id |

**Companion / standalone tooling (`scripts/`).**

| Script | Job |
|--------|-----|
| `hash_gate.py` | Hashline diff-context validation. |
| `audit_chain.py` | Hash-chained audit append + verify. |
| `node_gate.py` / `scan_node_violations.py` / `classify_module.py` / `generate_node_map.py` | Node-discipline gate + analysis (VERIFY soft gate, `--strict-nodes` hard block). |
| `init_project.py` | Scaffold `.techne/`; runs pre-flight (audit-chain integrity, relevant mistakes, KG hits). |
| `knowledge_graph.py` | Query the wikilink graph (status/phases/mistakes/skill/file/search/rewards). |
| `project_graph_build.py` | Build per-project file-architecture graph. |
| `mistakes_logger.py` / `session_reporter.py` | Mistake logging + session summary. |
| `watchdog.py` | External stall/tamper/skip/orphan detector (cron). |
| `task_gardener.py` / `task_reset.py` / `template_scaffolder.py` | Maintenance utilities. |

> The legacy per-phase scripts for CONTEXT_GUARD / CRITIQUE / REVIEW (`context_guard_check.py`,
> `critique_preflight.py`, `diff_gate_checker.py`, `conclude_proof_gen.py`, `recall_honcho.py`)
> remain for the deprecated 11-phase loop and are not invoked by `./next`.

**What hardening means.** Each gate independently testable; deterministic (same input →
same output); actionable failure messages (tell the agent exactly what to add).

**Tests.** `tests/test_scripts/`.

**Connects to.** Domain 1 (gates run in the loop), Domain 6 (enforcement re-invokes gates via the CLI).

---

## Domain 5: CLI Surface

**What it is.** The `techne` console entry point — the primary operating surface for
any host. Replaces the old hand-assembled filesystem ritual.

**Key files.**

| File | Role |
|------|------|
| `pyproject.toml` | Declares the `techne` console_scripts entry point. |
| `techne_cli/main.py` | CLI dispatch: `init`, `next`, `status`, `doctor`, `gate`, `handoff`, `proposals`. |
| `techne_cli/core.py` | Import bridge to `scripts/` + `harness/` internals. |

**Commands.**

| Command | Effect |
|---------|--------|
| `techne init <id>` | Scaffold `.techne/loop/`, write `state.json` (RECALL), run pre-flight. |
| `techne next` | Run current-phase gates, advance on pass. |
| `techne status` | Phase, blocked-log summary, RL health. |
| `techne doctor` | CC + Hermes setup, audit-chain integrity, context freshness, pending proposals. |
| `techne gate <name> <target>` | Run a gate standalone (`hashline` / `forbidden` / `audit`). |
| `techne handoff` | Write a session-continuity doc. |
| `techne proposals` | Review pending GRPO proposals. |

**What hardening means.** Zero-dep stdlib CLI; gates callable standalone (so the
enforcement plugins and any runtime can invoke them without importing Python).

**Tests.** `tests/test_cli.py`.

**Connects to.** Domain 1 (`next` wraps `next.py`), Domain 4 (`gate` runs gates), Domain 6 (plugins shell out to `techne gate`).

---

## Domain 6: Enforcement Layer

**What it is.** Tool-call-layer write enforcement — blocks writes that violate phase
discipline, logs the audit chain, and writes RL events. Runs on **every** write, always.

**Key files.**

| File | Role |
|------|------|
| `plugins/techne-plugin/__init__.py` + `plugin.yaml` | **Hermes** enforcement adapter. `pre_tool_call` → `techne gate hashline` (IMPLEMENT), `techne gate forbidden` (any write), `techne gate audit`; writes `rl.jsonl`. Commands: `/techne-plugin status`, `/techne-plugin off`. |
| `hooks/phase_guard_hook.py` | **Claude Code** `PreToolUse` hook — exits 2 to deny a wrong-phase / wrong-artifact write. |
| `harness/plugins/phase_guard.py` | Shared logic: `check_write_allowed(path, cwd)`. Fails open when no `.techne/` is present. |
| `plugins/techne/` | Legacy single Hermes plugin (superseded by `techne-plugin` + `orchestrator`). |

**What blocks:** writes outside the current phase's artifact, writes to `.techne/audit/`,
forbidden patterns (reverse shells, etc.), stale diffs (hashline), and — when active —
phase-timeout and tool-count limits.

**What hardening means.** Fail-open outside Techne projects; never block the audit trail
from being written by the loop itself; parity between the CC hook and the Hermes plugin.

**Tests.** `tests/test_scripts/` (synthetic tool payloads), enforcement E2E suite.

**Connects to.** Domain 4 (re-invokes gates), Domain 3 (reads state, writes audit/RL), Domain 8 (RL events).

---

## Domain 7: Knowledge Graph + Memory

**What it is.** The wikilink graph connecting mistakes, ledger entries, tasks, files,
and skills — rebuilt at CONCLUDE→DONE — plus the durable memory stores.

**Key files.**

| File | Role |
|------|------|
| `.techne/memory/wikilinks.json` / `.md` | Graph + human-readable index. Rebuilt on every DONE. |
| `scripts/knowledge_graph.py` | Query tool (status/phases/mistakes/skill/file/search/rewards). |
| `harness/wikilink.py` | Graph build (`build_graph`, `format_markdown`). |
| `scripts/project_graph_build.py` | Per-project file-architecture graph. |
| `.techne/memory/ledger.md`, `mistakes.md`, `retros/` | Wisdom extraction targets (written by `_persist_retro`). |

**RECALL requirement:** the RECALL gate requires evidence the knowledge graph was
consulted (`techne kg search <term>` or equivalent reference in `recall.txt`).

**What hardening means.** Node/edge quality; query completeness ("what phase fails most
for auth tasks?"); rebuild robustness (best-effort, never block DONE).

**Connects to.** Domain 8 (graph feeds GRPO), Domain 1 (rebuild at DONE), Domain 4 (KG gate at RECALL).

---

## Domain 8: GRPO / Learning Loop

**What it is.** The reward system — gate outcomes logged as RL events, advantages
computed per task-type group, high-advantage variants staged as human-ratified proposals.

**Key files.**

| File | Role |
|------|------|
| `.techne/events/rl.jsonl` | RL event log (written by the enforcement layer on every gate outcome). |
| `.techne/memory/rewards.db` | Composite reward scores. |
| `.techne/memory/retro_proposals.md` | Staged `PROPOSE ADD` skill-edit proposals. |
| `harness/grpo.py` | Advantage computation + proposal generation. |
| `harness/reward.py` / `reward_log.py` | Reward logging. |
| `harness/apply_retro.py` | The **only** skill-write path — human-ratified application. |
| `harness/_retro_conclude.py` | `_persist_retro` — wisdom extraction wired at CONCLUDE→DONE. |

**Proposal surfacing:** at CONCLUDE, `./next` prints pending proposal count; review via
`techne proposals`. **Proposals never auto-apply** — `apply_retro.py` gates every edit.

**What hardening means.** Reward-signal accuracy; safe feedback loop (bad rewards must
not silently degrade behavior); proposal review never bypassed.

**Connects to.** Domain 2 (learning adjusts classifier), Domain 7 (graph data), Domain 6 (RL event source).

---

## Domain 9: Orchestration Layer

**What it is.** The layer that drives the loop, enforces retry caps, surfaces HITL
blocks, and manages session continuity — what prose alone cannot enforce.

**Key files.**

| File | Role |
|------|------|
| `plugins/orchestrator/__init__.py` + `plugin.yaml` | Hermes orchestration plugin. Hooks: `on_session_start` (surface active phase), `pre_tool_call` (retry-cap block), `on_session_end` (write handoff if incomplete). Commands: `orchestrator status/retry/block/unblock/handoff`. |
| `techne_cli/main.py` → `cmd_handoff` | `techne handoff` — continuity doc for resuming in a new session. |
| `harness/pipeline_enforcer.py` | Phase-transition rules + retry budgets. |

**HITL / retry:** when a phase exceeds its retry cap, the orchestrator blocks with an
HITL message rather than looping forever. Optional **Revolver** companion plugin rotates
model/provider on failure (see GRAND-PLAN Task 15).

**What hardening means.** Retry-cap correctness; handoff completeness (a fresh agent can
resume from disk); HITL messages that explain the block in plain language.

**Connects to.** Domain 1 (drives the loop), Domain 3 (reads/writes state + handoff), Domain 6 (shares the `pre_tool_call` surface).

---

## Domain 10: Skills, Docs & Workshop

**What it is.** The skill library, the documentation, plans, ADRs, and retro logs —
the map and the memory.

**Key files.**

| File | Role |
|------|------|
| `SKILL.md` | Skill router + pipeline contract. First-read entry point. |
| `skills/` | Skill library (under restructure — Techne skills relocate to `.hermes/skills/` per GRAND-PLAN Task 13). |
| `docs/host-integration-guide.md` | Host operational contract (5-phase, two-layer). |
| `docs/agent-knowledge-dimensions.md` | Cross-source harness-engineering knowledge map. |
| `docs/open-knowledge-format-context.md` | **OKF — the durable building-context standard** (one concept per file, YAML frontmatter, markdown links as edges, `index.md`, `log.md`). |
| `docs/plans/GRAND-PLAN-FINAL.md` | Zero-HITL framework: Context/Proof/Enforcement replace HITL. |
| `docs/plans/GRAND-PLAN-HERMES.md` | Live architecture spec for the two-layer model. |
| `docs/retro/*.md`, `docs/adr/` | Retrospectives + decision records. |

**Durable building context uses OKF.** Shared, cross-session context lives as
[OKF](open-knowledge-format-context.md) concept files under `.techne/context/`
(`index.md` + `domains/` + `decisions/` + `runbooks/` + `risks/` + `skills/` + `log.md`) —
one concept per file, git-versioned, human-readable, agent-parseable. **YAGNI: plain files
until they demonstrably stop being enough; no new database.** When a concept becomes
enforceable, promote it into a gate, eval, skill, or policy.

> **Note:** `agents/*.md` (the old phase-agent prompts) were removed in the restructure;
> phase roles are now expressed through skills + subagent dispatch, not standalone prompt
> files. The legacy domain map's "Phase Agent Prompts" domain no longer applies.

**What hardening means.** Root instruction files are **maps, not encyclopedias** (the
"lost in the middle" lesson — see `agent-knowledge-dimensions.md`); plans match current
code; docs cover every live domain accurately.

**Connects to.** Every domain (docs should describe them all accurately).

---

## Domain Map — Quick Reference

| # | Domain | Dir / Prefix | Tests | Hardening Priority |
|---|--------|-------------|-------|-------------------|
| 1 | Pipeline Core | `scripts/next.py`, `harness/` | `test_cli.py`, `test_hash_gate.py` | 1 — highest impact |
| 2 | Phase / Mode System | `harness/pipeline_enforcer.py` | (mode tests) | 2 |
| 3 | Loop & Task State | `.techne/loop/`, `.techne/memory/` | (implicit) | 3 — integrity |
| 4 | Phase Gates + Tooling | `scripts/` | `tests/test_scripts/` | 4 |
| 5 | CLI Surface | `techne_cli/` | `test_cli.py` | 5 |
| 6 | Enforcement Layer | `plugins/techne-plugin/`, `hooks/` | enforcement E2E | 2 — security |
| 7 | Knowledge Graph + Memory | `scripts/knowledge_graph.py`, `harness/wikilink.py` | (none) | 7 |
| 8 | GRPO / Learning Loop | `harness/grpo.py`, `.techne/events/` | (none) | 8 |
| 9 | Orchestration Layer | `plugins/orchestrator/` | (none) | 6 |
| 10 | Skills, Docs & Workshop | `skills/`, `docs/` | (none) | 9 |

## Improvement Protocol — Per Domain

When hardening a domain:

1. Open this file to see what belongs to that domain.
2. Read all files listed in that domain's table.
3. Write tests for the behavior you're hardening.
4. If adding a new gate/script, pair it with a CLI subcommand or gate name.
5. If removing something, update this file.
6. Record what changed and why in `docs/retro/`.
