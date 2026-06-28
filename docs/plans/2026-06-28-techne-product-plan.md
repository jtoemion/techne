# Techne Product Plan — Two Engines, One Product

> **Date:** 2026-06-28
> **Scope:** Turn Techne (the host-driven `./next` loop) and the OrchestratorLoop
> (the model-backed RL runner) into a single coherent product.
> **Status:** Plan. Supersedes nothing — it sequences and frames the existing work
> ([GRAND-PLAN-HERMES](GRAND-PLAN-HERMES.md), [HANDOFF-CC-V0](../../HANDOFF-CC-V0.md),
> [SCOUTING-REPORT](../../ref/SCOUTING-REPORT.md), the harness corpus in
> [agent-knowledge-dimensions](../agent-knowledge-dimensions.md)).

---

## 1. The Product

**Techne is a disciplined coding harness that can't be talked out of doing it right.**
Your agent does the thinking; Techne guarantees the discipline, proves the work with
artifacts, and improves itself over time. No API key required for the spine — the model
is something you bring.

The empirical thesis (from the harness corpus): *Agent = Model + Harness, and the harness
swings real-world performance up to 22%.* Techne is the harness.

### Two modes, one spine

The product has **two execution modes that share one enforcement spine** (the same
phases, gates, audit chain, memory, and RL log):

| Mode | Driver | Who provides each phase artifact | Use for |
|------|--------|----------------------------------|---------|
| **Driven** | `techne` CLI / `./next` | A host agent (you) or its subagents, interactively | Day-to-day human+agent work; the installable product |
| **Autopilot** | `driver.run_plan()` (OrchestratorLoop) | An injected model backend, unattended, over a batch of tasks | Self-improvement, dogfooding, benchmarking, "Techne building Techne" |

Both run the **same real gates** and write the **same audit chain + RL events**. The only
difference is where the phase artifact comes from. This is already the documented design
intent of `driver.py` ("the autonomous/RL counterpart to the host-driven loop") — the
product job is to make that *literally one spine* instead of two parallel implementations.

### Who it's for

1. **Solo builders + small teams** running an agent (Claude Code, Hermes, Codex) who want
   their agent's output to be gated, proven, and resumable — the Driven product.
2. **Power users / the project itself** who want an autonomous loop that runs task batches
   and gets measurably better — the Autopilot product.

---

## 2. The Central Problem: Engine Convergence

Today there are **two pipeline implementations that have drifted apart:**

| | Driven (`./next`) | Autopilot (`OrchestratorLoop`) |
|---|---|---|
| Phases | 5: RECALL→IMPLEMENT→VERIFY→CONCLUDE→DONE | 11: …CONTEXT_GUARD→CRITIQUE→REVIEW→EVAL→RETRO→REFRESH_CONTEXT… |
| Gates | `scripts/next.py` `_check_*_gates` | `harness/gates.py` (Next.js-specific) |
| State | `.techne/loop/state.json` | `techne/tasks.db` (SQLite) |
| Status | Production path | Marked legacy, but owns the RL/GRPO machinery |

**They must converge onto a shared gate core, or the product is two products wearing one
name.** The convergence target:

- **One phase set** — the 5-phase loop is canonical. The 11-phase extras become *gate
  checks inside the 5 phases* (already done for `./next`; the legacy mapping is in
  [host-integration-guide §7](../host-integration-guide.md)).
- **One gate library** — both drivers call the same `_check_*_gates`. `OrchestratorLoop`
  stops using its own `harness/gates.py` phase set and adopts the `next.py` gate core.
- **One state + memory + RL log** — both write `.techne/audit/chain.jsonl`,
  `.techne/events/rl.jsonl`, and `.techne/memory/`. `tasks.db` becomes an Autopilot-only
  batch index, not a second source of truth.

This convergence is **Phase 0** below. Everything else depends on it.

---

## 3. Phases

### Phase 0 — Engine Convergence (de-risk the foundation)

**Goal:** One spine, two drivers. No feature work until this holds.

| Workstream | Deliverable | Exit criteria |
|---|---|---|
| Shared gate core | `OrchestratorLoop` calls `next.py`'s `_check_*_gates` instead of its own phase gates | A task driven by `./next` and the same task driven by `driver.run_plan` hit identical gates |
| Phase-set unification | OrchestratorLoop's 11 phases collapse to the 5-phase set + in-phase checks | `PHASE_SEQUENCE` is the single source; legacy phases are gate checks, not phases |
| Unified telemetry | Both drivers write the same `audit/chain.jsonl` + `events/rl.jsonl` | A GRPO run can score Driven and Autopilot tasks in the same group |
| Dead-code quarantine | Move truly-unused legacy (old per-phase scripts, `plugins/techne/`) to `legacy/` or delete | `ls` of the repo root shows only live machinery (GRAND-PLAN Task 13) |

**Why first:** the harness corpus rule — *fix the harness layer, not the symptom.* Two
diverging engines is a harness defect that will multiply every later feature by two.

---

### Phase 1 — The Driven Product (what people install)

**Goal:** A real, installable, pleasant-to-use tool. This is the OMO-style product surface
the [scouting report](../../ref/SCOUTING-REPORT.md) prescribes. Most of this is built or
in-flight — Phase 1 is about finishing and polishing.

| Workstream | Deliverable | Status |
|---|---|---|
| CLI | `techne init/next/status/doctor/gate/handoff/proposals` as `pip install -e` console entry | ✅ built ([techne_cli](../../techne_cli/main.py)) |
| Doctor | Human-readable health check (CC + Hermes setup, audit chain, context freshness, proposals) | ✅ built; extend per GRAND-PLAN Task 11 |
| Phase reports | Designed, forwarded-to-user phase output (gates, diff summary, tests, next step) | polish |
| Planning interview | `techne plan` — Socratic intake → fills ticket schema → chains `grill` (ref: OMH `omh-deep-interview`) | **new** (scouting #5) |
| `ultrawork` trigger | Natural-language "just do it" that drives the loop autonomously, surfacing only HITL + reports | **new** (scouting #6) |
| Handoff/resume | `techne handoff` continuity doc + `init --resume` | ✅ built; wire resume |
| Packaging | `pipx install techne`, versioned releases, optional-dep extras | **new** |
| Onboarding | <100-line `SKILL.md` (maps not encyclopedias — the corpus lesson), quickstart, one screencast | **new** + **skill-bloat cleanup** |

**Exit criteria:** A new user installs Techne, runs `techne plan` → `ultrawork` on a real
task, and gets a gated, proven, committed change without reading the 30-pitfall SKILL.md.

---

### Phase 2 — The Quality Spine (make "done" mean something)

**Goal:** Autonomy is only safe if "done" is trustworthy. This is the anti-cheat /
test-integrity layer — the thing that lets you run with minimal HITL.

| Workstream | Deliverable | Why |
|---|---|---|
| **Mutation gate** | `scripts/mutation_gate.py` at VERIFY — mutate changed source, require frozen tests to fail; survived mutation = BLOCK | The *only* HITL-free mechanism that catches a test that was weak from the start. Must be un-suppressible (corpus: "ban escape hatches"). |
| **Frozen tests + ticket** | `techne gate frozen` — hash test files + DONE_WHEN at the TEST phase, block edits past it (enforcement layer) | Closes the late door: can't weaken a test after it fails |
| **Separation of authorship** | TEST-author subagent (sees spec only) vs IMPLEMENT subagent (tests read-only) | Corpus: models grade themselves too generously; reduces accommodating tests |
| **Hashline** | Diff-context validation against real file at IMPLEMENT | ✅ built ([hash_gate.py](../../scripts/hash_gate.py)); 6.7%→68.3% per OMO |
| **Execution budgets** | step/time/token/cost budgets per loop; structured failure artifact on exhaustion | Corpus: no invisible doom loops |
| **`verified` phase_mode** | RECALL→SPEC→TEST(freeze)→IMPLEMENT(tests RO)→VERIFY(run+mutate)→CONCLUDE | Opt-in quality tier; existing mode mechanism |

**Exit criteria:** A weak/accommodating test fails the mutation gate; a post-hoc test edit
is blocked at the tool-call layer; a runaway loop returns a failure artifact, not silence.

---

### Phase 3 — Autopilot + Self-Improvement (the moat)

**Goal:** Close the loop the [productization-roadmap](../../ref/SCOUTING-REPORT.md) and the
Ornith model point at — Techne drives a model through task batches and gets measurably
better. This is what no competitor (OMO included) has: hard-gated, audited, RL-improved
autonomy.

| Workstream | Deliverable | Status |
|---|---|---|
| Real model backends | `model_backends.py` adapters: Anthropic SDK, headless `claude -p`, local | partial ([driver.py](../../harness/driver.py) injects model) |
| Sandboxed apply + real VERIFY | Apply the model diff in a throwaway worktree, run tests there, HALT on apply failure | **new** (roadmap item 3 — the top safety gap) |
| Closed GRPO loop | RL events → advantage (per task-type group) → proposals → **human ratify** → `apply_retro.py` | ✅ machinery built; wire end-to-end + surface at CONCLUDE (GRAND-PLAN Task 12) |
| Jointly-optimized scaffold | Make the *test/verification strategy* task-type-aware and let GRPO learn which scaffold catches the most mutations per class (the Ornith insight) | **new** |
| Dogfood harness | Techne runs its own backlog through Autopilot; proposals improve its own skills | **new** — the "Techne building Techne" loop |

**Guardrail (non-negotiable):** proposals **never auto-apply.** `apply_retro.py` +
human ratification is the only write path to skills. (Existing safety clamp — keep it.)

**Exit criteria:** A batch of N tasks runs unattended through Autopilot; the run produces
scored RL events, at least one ratified skill improvement, and a sandboxed-verified diff —
with zero un-gated writes.

---

### Phase 4 — Distribution & GA

**Goal:** Ship editions, prove it, make it trustworthy to adopt.

| Workstream | Deliverable |
|---|---|
| Editions | **Claude Code** ([HANDOFF-CC-V0](../../HANDOFF-CC-V0.md)) + **Hermes** ([GRAND-PLAN-HERMES](GRAND-PLAN-HERMES.md)) + Codex/OpenCode adapters — same spine, harness-specific enforcement adapter |
| Trust posture | No-network / no-telemetry default as a *selling point* (vs OMO's PostHog); audit chain as the proof story |
| Harness-isolation eval | Same task, swap model, attribute pass/fail to model vs harness (corpus: High priority) |
| Benchmark publishing | Run a public task set; publish gate-compliance + mutation-kill-rate, not vanity scores |
| Docs site + releases | Versioned releases, changelog, the `ref/` scouting + corpus as the "why" |

**Exit criteria:** A user on any of the three harnesses installs the matching edition and
gets identical enforcement behavior; published evals separate model quality from harness
quality.

---

## 4. Sequencing & the One Key Decision

```
Phase 0 (converge engines) ──> Phase 1 (driven product) ──> Phase 2 (quality spine)
                                       │                            │
                                       └──────────> Phase 3 (autopilot) <┘
                                                          │
                                                     Phase 4 (GA / editions)
```

**The one decision that shapes everything: Driven-first or Autopilot-first?**

Recommendation: **Driven-first.** Reasons:
1. The Driven product is the *foundation* — Autopilot is the same spine with a model
   driver swapped in, so it reuses Phases 0–2 wholesale.
2. It's the usable surface (someone can install it Monday); Autopilot is a power feature.
3. The quality spine (Phase 2) is required *before* Autopilot is safe — you can't run
   minimal-HITL autonomy without the mutation gate.

So: 0 → 1 → 2, then 3 lands on top, then 4 packages it. Autopilot is not skipped — it's the
moat — but it's earned by the spine beneath it.

---

## 5. Success Metrics

Per the corpus ("evals as instruments, not trophies"):

| Metric | Phase | Target |
|---|---|---|
| Engine parity | 0 | Driven and Autopilot hit identical gates on the same task |
| Time-to-first-gated-change for a new user | 1 | < 10 min from install |
| Mutation-kill-rate on the VERIFY suite | 2 | High enough that a known-weak test is caught |
| Un-gated writes during an Autopilot batch | 3 | **Zero** (audit chain proves it) |
| Ratified skill improvements per dogfood batch | 3 | > 0, trending up |
| Cross-harness behavior parity | 4 | Identical enforcement on CC / Hermes / Codex |

---

## 6. Risks & Non-Goals

**Risks**
- *Engine convergence is invasive.* Mitigate: Phase 0 first, behind the full test suite.
- *Mutation gate is gameable if suppressible.* Mitigate: enforce at the tool-call layer,
  no inline-disable (corpus rule).
- *Skill bloat creeps back.* Mitigate: a CI check on `SKILL.md` line count.

**Non-goals (explicitly out — corpus YAGNI)**
- Multi-provider model orchestration (OMO's problem, not ours — the model is injected).
- OPA/SLSA/SBOM/Cosign supply-chain gates and decentralized proof-of-inference — *future
  inspiration*, filed Low in the corpus backlog. Do not build before there's a CI story.
- Team Mode / parallel mailbox — fights the serial audit-chain invariant.
- Telemetry — the no-network posture is a feature.

---

## 7. Immediate Next Actions

1. **Phase 0, workstream 1:** make `OrchestratorLoop` call `next.py`'s `_check_*_gates`.
   This is the highest-leverage single change — it turns two engines into one spine.
2. **Phase 1 cleanup:** cut `SKILL.md` to a <100-line map (measured 20-pt accuracy win).
3. **Phase 2 spike:** prototype `scripts/mutation_gate.py` on one Python file to prove the
   anti-cheat mechanism before wiring it into VERIFY.

Each goes through the pipeline. The plan itself is the contract; the gates enforce it.
