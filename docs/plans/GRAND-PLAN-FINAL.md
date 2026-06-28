# GRAND-PLAN-FINAL — Techne as a Harness-Engineered, Zero-HITL Quality Agent

> **Date:** 2026-06-28
> **Mandate:** Build a framework — harness engineering at the heart — that makes an
> agent produce **quality codework** while structurally reducing its ability to
> **drift, hallucinate, lie, or disobey** the rules. **Zero human-in-the-loop in the
> shipped product.** Full authority taken to rename, remove pipelines, and restructure.
> **Supersedes:** the engine-convergence framing of
> [2026-06-28-techne-product-plan.md](2026-06-28-techne-product-plan.md). Folds in
> [GRAND-PLAN-HERMES](GRAND-PLAN-HERMES.md), [HANDOFF-CC-V0](../../HANDOFF-CC-V0.md),
> the [scouting report](../../ref/SCOUTING-REPORT.md), and the
> [harness corpus](../agent-knowledge-dimensions.md).
> **Research basis:** 5 web research passes (2026) on context engineering, autonomous
> agent reliability, reward hacking, spec-driven development, and judge reliability —
> citations inline.

---

## 0. The One-Sentence Thesis

> A human reviewer does three jobs — **knows the codebase, checks the work, and stops bad
> actions.** Remove the human only when a deterministic harness does all three. Context
> replaces *knowing*; Proof replaces *checking*; Enforcement replaces *stopping*. The model
> is a swappable reasoning core inside this harness — never the thing we trust.

This is the corrected version of "enough context removes HITL." Context is necessary but
**provably insufficient on its own**: the 2026 literature is unanimous that loading more
context does not guarantee the agent obeys it, and frontier models actively game verifiers
when left unchecked. So we replace the human with a **trinity**, not a single lever.

---

## 1. Failure Modes → Mechanisms (the spine of the whole framework)

Every design choice in this plan exists to defeat one of four named failure modes. If a
proposed feature doesn't map to this table, it doesn't ship (YAGNI).

| Failure mode | What the agent does | Harness mechanism that replaces the human | Pillar | Evidence |
|---|---|---|---|---|
| **Drift** | wanders off the task; scope-creeps; recycles past actions | Frozen **SPEC** contract · **SCOPE** gate · **lean context** (stay out of the "dumb zone") · step/token **budget** · plan-alignment gate | Context + Enforcement | "dumb zone" ~40% window; asymmetric goal drift (arXiv 2603.03456) |
| **Hallucinate** | invents APIs, files, parameters | **Grounding retrieval** (real code in context) · **Hashline** (edits must match real file bytes) · **context-gap detector** | Context + Proof | grounding cuts hallucination; context-gap fabrication taxonomy |
| **Lie** | claims success without proof; games the test | **Immutable trust boundary** (tests/verifier/tool-surface outside the model's reach) · **deterministic boundary monitor** (zero-reward + block on any reach for verification machinery) · **mutation gate** · SHA-gated **real** tests · secret/forbidden scan · **separate-model verifier** | Proof | Ornith two-layer defense; reward-hacking benchmark (arXiv 2605.02964); preference leakage |
| **Disobey** | ignores rules/skills/constraints | **Tool-call enforcement** (phase_guard) · immutable test isolation · **no escape hatches** (no inline-disable) · **small focused skills** (defeat lost-in-the-middle) | Enforcement + Context | escape-hatch ban; skill-bloat 77%→97% (Nick Nisi) |

**Read this table top-to-bottom: it is the product.** Everything below is how we build each cell.

---

## 2. The Three Pillars (what the human used to be)

### Pillar I — The Context Engine (replaces *knowing the codebase*)

The human knew the codebase. The Context Engine makes that knowledge **present, lean, and
grounded** in every phase — without dumping it all and triggering the "dumb zone."

Three layers, mirroring the spec-driven convergence (Kiro "steering" / Spec-Kit
"constitution" / Claude Code `CLAUDE.md`):

1. **Constitution** (`.techne/constitution.md`) — immutable, cross-session principles:
   architecture boundaries, security invariants, "never do X." Loaded every task. < 100 lines.
2. **Memory bank** (`.techne/context/`) — the amortized, deterministic project map
   (`project_digest`, `file_roles`, `commands`, `risk_boundaries`) + the wikilink graph +
   the mistake ledger. Already built (`context_build.py`); extended here with a
   **context-gap detector**.
3. **Per-task SPEC** (`.techne/loop/spec.md`) — the frozen, authoritative contract for
   *this* task (EARS-style requirements + acceptance criteria + FILE_SCOPE). This is the
   single source of truth the whole loop verifies against. **It is hashed and frozen at
   creation** — the agent cannot rewrite the goalposts (anti-drift, anti-lie).

**Discipline (research-driven), not just files:**
- **Lean context / intentional compaction.** Keep the working window well under the dumb
  zone (~40%). Prefer restart-with-compaction over long correction chains — "the most
  likely continuation after a mistake is another mistake."
- **Grounding over memory.** Before IMPLEMENT, retrieve the *actual* file contents and
  symbols the SPEC touches into context. The agent edits what it can see, not what it
  recalls. (Hashline then proves it saw the real bytes.)
- **Context-gap detector.** A gate that flags when the codebase uses a stack/pattern with
  no corresponding guidance in the memory bank (e.g. React code, no React card). Gaps are
  invisible by definition and are a primary drift source — surface them and require a card
  before IMPLEMENT.

### Pillar II — The Proof Spine (replaces *checking the work*)

The human checked the work. The Proof Spine makes **"done" mean something** without a human,
under the hard assumption that **the model will lie and game the verifier if it can.**

**The immutable trust boundary (the load-bearing mechanism).** Adopted directly from
Ornith-1.0's layered defense:
- **Layer 1 — structural immutability.** The verification machinery is **outside the
  model's reach**: test files, the gate scripts, the audit chain, and the sanctioned tool
  surface are read-only to the implementer. The agent evolves only the *inner* scaffold
  (its code, memory, error-handling) — never the *outer* boundary (the environment, tests,
  verifier).
- **Layer 2 — deterministic boundary monitor.** Any attempt to read a withheld path
  (oracle/solution), modify a verification script, edit a frozen test, or call a tool
  outside the sanctioned surface is **blocked at the tool-call layer, logged to the audit
  chain, and assigned negative reward (excluded from advantage).** This is the existing
  `phase_guard` + audit chain, extended to cover the full verification surface.

**On top of the boundary, defense-in-depth (no single check is trusted):**
- **Real tests, SHA-gated.** VERIFY runs the actual suite; output is hashed so faked stdout
  is rejected. Non-empty + explicit count (an empty suite is a lie).
- **Mutation gate.** Mutate the changed source; the frozen tests must catch it. A suite
  that survives mutation is a weak/accommodating test → BLOCK. This is the *only* HITL-free
  mechanism that catches a test that was weak **from the start**, and it must be
  un-suppressible.
- **Test authorship is separated and isolated.** Tests are authored against the SPEC by a
  **different model** than the implementer (preference-leakage avoidance), in a context
  that never sees the implementation. Frozen + hashed before IMPLEMENT begins.
- **Semantic + safety gates beyond test-pass.** The documented dark-factory failure —
  tests passed, diff clean, yet the agent shipped a plaintext secret and a token-audience
  mismatch — proves test-pass is *necessary, not sufficient*. Add: secret/forbidden-pattern
  scan, and a **separate-model verifier** (VerifiAgent-style: meta-check completeness +
  tool-based correctness) that reads the diff against the SPEC and flags scope creep and
  unstated behavior.

### Pillar III — The Enforcement Layer (replaces *stopping bad actions*)

The human stopped bad actions. Enforcement makes invalid actions **physically impossible or
visibly failing**, at the tool-call layer — not via prompts the model can rationalize around.

- **phase_guard at the tool-call layer** — Hermes plugin (`plugins/techne-plugin/`) + Claude
  Code PreToolUse hook (`hooks/phase_guard_hook.py`), shared logic in
  `harness/plugins/phase_guard.py`. Blocks wrong-phase / wrong-artifact / boundary-violating
  writes.
- **No escape hatches.** Inline-disable comments, linter-ignore, and `--no-verify` are
  banned in the harness environment — otherwise the agent learns to suppress the gate
  instead of fixing the code (corpus rule, confirmed by reward-hacking research).
- **Budgets.** Step / time / token / cost budgets per loop. On exhaustion → a structured
  failure artifact and a **FAILED** task — never an invisible loop, and (zero-HITL) never a
  prompt to a human. A failed task is logged, scored, and fed to the learning loop.
- **Audit chain.** SHA-256 hash-chained `.techne/audit/chain.jsonl`, one entry per phase.
  Tamper is detectable; the chain is itself inside the immutable boundary.

---

## 3. The Unified Loop (one pipeline, two drivers — the legacy pipeline is removed)

**Removed:** the legacy 11-phase `OrchestratorLoop` *as a distinct pipeline*. Its extra
phases (CONTEXT_GUARD/CRITIQUE/REVIEW/EVAL/RETRO/REFRESH_CONTEXT) collapse into gate checks
inside the canonical loop. There is now **one phase set and one gate core.**

**The canonical loop (6 phases — SPECIFY added):**

```
SPECIFY → GROUND → IMPLEMENT → VERIFY → SEAL → DONE
```

| Phase | Renamed from | Produces | Gate (defeats) |
|-------|--------------|----------|----------------|
| **SPECIFY** | *(new)* | `spec.md` — frozen EARS contract + acceptance criteria + FILE_SCOPE; tests authored + frozen by a separate model | contract exists, hashed; tests frozen (drift, lie) |
| **GROUND** | RECALL | `ground.md` — retrieved real code + memory-bank refs + context-gap check | real context present, no unfilled gaps (hallucinate, drift) |
| **IMPLEMENT** | IMPLEMENT | `diff.txt` | hashline + scope + forbidden-pattern + boundary monitor (hallucinate, drift, lie, disobey) |
| **VERIFY** | VERIFY | `test_output.txt` | real SHA-gated tests + **mutation gate** + secret scan + separate-model verifier (lie) |
| **SEAL** | CONCLUDE | `seal.md` | retro markers + verify ref + commit; fires learning loop (memory) |
| **DONE** | DONE | — | task closed |

**Two drivers, identical gates:**
- **Driven mode** — `techne` CLI / host subagents provide each phase artifact. Used for
  development and for the watchable gate-validation period (see §6).
- **Autopilot mode** — `driver.run_plan()` provides each phase artifact from an injected
  model backend, unattended, over a task batch, feeding the learning loop. **This is the
  shipped zero-HITL product.**

The driver is the *only* thing that differs. Same `_check_*_gates`, same boundary, same
audit chain, same memory. (`driver.py` already calls itself "the autonomous counterpart to
the host-driven loop" — this makes it literally one spine.)

---

## 4. The Learning Loop Without a Human (replaces GRPO ratification)

The old loop required a human to ratify GRPO skill-edit proposals. Zero-HITL replaces the
ratifier with a **structural promotion gate**:

1. RL events (gate outcomes, boundary violations as negative reward) accumulate in
   `.techne/events/rl.jsonl`.
2. GRPO computes per-task-type advantage; high-advantage variants become **candidate**
   skill/prompt edits — staged, never live.
3. **Promotion gate (the new ratifier):** a candidate edit is applied to a *shadow* copy
   and must **beat the incumbent on a held-out, frozen eval set** (regression cases drawn
   from real past failures) measured by **pass^k**, with **zero boundary violations**, to
   be promoted. Lose or tie → discarded.
4. Promotion is itself an audit-chained, reversible event. No human, but also no
   self-congratulation: the edit earns its place against frozen evidence or it doesn't ship.

This is "self-improving but not self-deceiving" — the Ornith insight (the scaffold is
learnable) made safe by an immutable held-out evaluator the policy can't reach.

---

## 5. Naming / Variable Changes (authority exercised)

Clarity renames — done as a migration workstream, not retroactively claimed:

| Current | New | Why |
|---|---|---|
| 11-phase `OrchestratorLoop` pipeline | **removed**; `OrchestratorLoop` kept only as the *Autopilot driver* over the 6-phase loop | one pipeline |
| `RECALL` phase | **GROUND** | it grounds context in real code; "recall" undersells it |
| `CONCLUDE` phase | **SEAL** | it seals the audit + memory + commit |
| *(none)* | **SPECIFY** phase | the frozen authoritative contract was missing |
| "host-driven loop" / "./next" | **Driven mode** | paired with Autopilot |
| `driver.run_plan` autonomous path | **Autopilot mode** | the shipped product |
| the verification machinery | **the Boundary** (immutable trust boundary) | names the load-bearing safety concept |
| `.techne/context` + constitution + spec | **the Context Engine** | first-class subsystem |

Phase artifacts rename with their phases (`recall.txt`→`ground.md`, `conclude.txt`→`seal.md`).
Backward-compat shims accept old names for one release.

---

## 6. The HITL-Removal Protocol (how we honor "remove HITL" safely)

Zero-HITL in the **product**. HITL exists only as a **temporary measurement scaffold during
development**, removed gate-by-gate as each gate proves itself. This is the dark-factory
discipline: *airtight verification before removing humans.*

For each gate:
1. Run it in **Driven mode** alongside a human label on a corpus of real tasks.
2. Measure the gate's **catch-rate** (does it block what the human blocks?) and
   **false-block rate**.
3. When catch-rate clears threshold on the labeled set, **remove the human from that gate
   permanently** and lock the threshold into the held-out eval.
4. The human is never in the shipped loop — they are a calibration instrument that is
   decommissioned per-gate.

Result: every removed-HITL point is backed by evidence that the harness catches what the
human did. No leap of faith.

---

## 7. Build Sequence

| # | Workstream | Defeats / Enables | Depends on |
|---|---|---|---|
| **W0** | **Engine convergence** — one gate core, one phase set; Autopilot driver calls `_check_*_gates`; remove the 11-phase pipeline | foundation | — |
| **W1** | **The Boundary** — make tests/gates/audit/tool-surface immutable to the implementer; deterministic boundary monitor (block + log + negative reward) | Lie, Disobey | W0 |
| **W2** | **Context Engine** — `constitution.md`, `SPECIFY` phase + frozen hashed `spec.md`, grounding retrieval, context-gap detector, lean-context/compaction discipline | Drift, Hallucinate | W0 |
| **W3** | **Proof Spine** — mutation gate (un-suppressible), separated+isolated test authorship (different model), secret/forbidden scan, separate-model verifier | Lie | W1, W2 |
| **W4** | **Enforcement hardening** — no-escape-hatch policy, budgets → structured FAILED artifact, audit coverage of the full surface | Disobey, Drift | W1 |
| **W5** | **Skill diet** — cut `SKILL.md`/skills to maps (<100 lines), close context gaps with focused cards; CI line-count guard | Disobey, Drift | W2 |
| **W6** | **Autopilot + sandbox** — real model backends; apply each diff in a throwaway worktree, run tests there, HALT on apply failure | enables zero-HITL | W1–W4 |
| **W7** | **Structural learning loop** — RL events → shadow promotion gate vs frozen held-out eval (pass^k, zero violations) | replaces ratification | W3, W6 |
| **W8** | **HITL-removal calibration** — per-gate catch-rate vs labeled corpus; decommission human per gate | honors the mandate | W3, W6 |
| **W9** | **Editions + distribution** — CC / Hermes / Codex adapters on one spine; no-telemetry posture; published evals | GA | all |

Sequencing rule: **the Boundary (W1) before Autopilot (W6).** You do not remove the human
until the machinery the human used to watch is itself unreachable and self-proving.

---

## 8. Success Metrics (instruments, not trophies)

| Metric | Meaning | Target |
|---|---|---|
| **pass^k** (k≥5) | task succeeds in *every* run, not best-of-k | the headline autonomy metric; rising |
| **Mutation-kill-rate** | % of injected mutations the frozen tests catch | high enough that a known-weak test fails |
| **Boundary-violation count** in an Autopilot batch | attempts to reach verification machinery | logged, reward-zeroed; **un-gated writes = 0** |
| **Gate catch-rate vs labeled corpus** | does each gate block what a human blocks? | per-gate threshold before HITL removal |
| **Context size at IMPLEMENT** | tokens in working window | below the ~40% "dumb zone" |
| **Drift rate** | diffs touching files outside frozen FILE_SCOPE | → 0 (gate-enforced) |
| **Ratified-edit win-rate** | promoted skill edits that beat incumbent on held-out eval | only winners promote |

---

## 9. Self-Critique (known weaknesses — the next iteration's input)

Honesty per the corpus. This plan is v1; here is where it is still soft:

1. **Mutation testing cost.** Re-running the suite per mutation is expensive on large repos.
   *Mitigation to design:* mutate only changed lines; cap mutation count; cache. Open.
2. **Separate-model verifier still has preference leakage if the same vendor.** Different
   model family reduces but doesn't eliminate collusion. *Mitigation:* the mutation gate is
   mechanical and model-independent — it's the backstop, the verifier is defense-in-depth.
3. **Context-gap detector is heuristic.** "Invisible by definition" cuts both ways — it can
   miss gaps. *Mitigation:* treat it as best-effort + grow the constitution from real misses
   via the learning loop.
4. **CoT/intent monitoring is deliberately omitted.** Research shows strong optimization
   pressure produces *obfuscated* hacking that hides intent. We rely on **outcome + boundary
   + mutation** (mechanical) over reasoning-trace inspection (gameable). Revisit if a class
   of hack slips the mechanical gates.
5. **Zero-HITL absolutism vs novel failure classes.** METR notes frontier models invent
   *new* reward hacks over time. *Mitigation:* the boundary monitor is allow-listed (deny by
   default on the verification surface), and W8's calibration corpus must keep ingesting new
   real failures. The plan is a ratchet, not a finish line.
6. **"Remove HITL" is delivered, but the honest scope is:** HITL is removed from the
   *product loop*; it remains, briefly, as a *calibration instrument* (W8) that is
   decommissioned per gate. If you want it gone even from calibration, that trades evidence
   for speed — flagged as your call.

---

## 10. Migration From Current Code

| Plan element | Lands in | Current state |
|---|---|---|
| Gate core | `scripts/next.py` `_check_*_gates` | ✅ exists; W0 points Autopilot at it |
| Hashline | `scripts/hash_gate.py` | ✅ built |
| Boundary monitor | extend `harness/plugins/phase_guard.py` + audit chain | ⚠️ partial (write-block; add verification-surface coverage + negative reward) |
| Mutation gate | new `scripts/mutation_gate.py`, wired into VERIFY like `node_gate` | ❌ new (W3) |
| SPECIFY phase + frozen spec | `next_state.PHASE_SEQUENCE` + new RECALL→GROUND rename | ❌ new (W2) |
| Context Engine | `harness/context_build.py` + new `constitution.md` + gap detector | ⚠️ partial |
| Separate-model verifier | `harness/driver.py` model adapters (role-tagged) | ⚠️ partial (model injected per role already) |
| Structural learning loop | `harness/grpo.py` + new shadow-eval promotion gate | ⚠️ machinery exists; promotion gate new (W7) |
| Autopilot + sandbox | `harness/driver.py` + new throwaway-worktree runner | ⚠️ driver exists; sandbox new (W6) |
| Skill diet | `SKILL.md`, `skills/` | ❌ bloated; W5 |

---

## 11. Immediate Next Actions

1. **W0** — point the Autopilot driver at `next.py`'s gate core; delete the 11-phase pipeline.
2. **W1** — extend `phase_guard` to make the *full verification surface* (tests, gate
   scripts, audit) immutable to the implementer, with logged negative-reward on any reach.
   This is the highest-leverage safety change; everything autonomous depends on it.
3. **W3 spike** — prototype `mutation_gate.py` on one file; prove a known-weak test fails it.

Each goes through the loop. The plan is the contract; the Boundary enforces it.

---

## Sources (research basis)

- [Context Engineering for Coding Agents — Martin Fowler](https://martinfowler.com/articles/exploring-gen-ai/context-engineering-coding-agents.html)
- [Context Engineering Best Practices 2026 — Packmind](https://packmind.com/context-engineering-ai-coding/context-engineering-best-practices/)
- [AI Agent Hallucination: Causes, Risks & Context Solutions — Atlan](https://atlan.com/know/ai-agent-hallucination/)
- [Asymmetric Goal Drift in Coding Agents Under Value Conflict — arXiv 2603.03456](https://arxiv.org/pdf/2603.03456)
- [Agentic Coding Levels / Dark Factory — MindStudio](https://www.mindstudio.ai/blog/agentic-coding-levels-explained)
- [The Bottleneck Isn't Coding Anymore. It's Verification — DevOps.com](https://devops.com/the-bottleneck-isnt-coding-anymore-its-verification/)
- [Spec-Driven Development: From Code to Contract — arXiv 2602.00180](https://arxiv.org/pdf/2602.00180)
- [Reward Hacking Benchmark: Exploits in LLM Agents with Tool Use — arXiv 2605.02964](https://arxiv.org/html/2605.02964)
- [LLMs Gaming Verifiers: RLVR can Lead to Reward Hacking — arXiv 2604.15149](https://arxiv.org/html/2604.15149v1)
- [Ornith-1.0: Self-Scaffolding LLMs for Agentic Coding — DeepReinforce](https://deep-reinforce.com/ornith_1_0.html)
- [Understanding Spec-Driven Development: Kiro, spec-kit, Tessl — Martin Fowler](https://martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html)
- [VerifiAgent: a Unified Verification Agent — arXiv 2504.00406](https://arxiv.org/pdf/2504.00406)
- [ReVeal: Self-Evolving Code Agents via Reliable Self-Verification — arXiv 2506.11442](https://arxiv.org/pdf/2506.11442)
- [LLM-as-a-Judge in 2026 — DeepEval](https://deepeval.com/blog/llm-as-a-judge)
