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
> **Research basis:** 11 web research passes (2026) across four rounds — context engineering,
> autonomous agent reliability, reward hacking, spec-driven development, judge reliability,
> mutation-testing cost, Goodhart/eval-contamination, mechanical convention extraction,
> property-based/model-independent verification, sandbox-escape/boundary completeness, and
> cold-start bootstrapping — citations inline.
> **Iteration:** R2 added the Gate Registry, a mutation-gate cost model, and a
> Goodhart-hardened promotion gate. R3 added the **model-independent proof floor** + a
> **spec-soundness gate** + named the spec-intent residual. R4 added **boundary completeness**
> (deny-by-default incl. non-existent paths, boundary self-test, OS-isolation), an
> **anti-injection action-provenance** mechanism (new failure mode), and a **cold-start
> BOOTSTRAP** pass (§9.2, §9.3, §9.8, §9.9, §9.10).

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
| **Lie** | claims success without proof; games the test | **Model-independent invariants (PBT)** · **immutable trust boundary** (tests/verifier/tool-surface outside the model's reach) · **deterministic boundary monitor** (zero-reward + block on any reach for verification machinery) · **mutation gate** · SHA-gated **real** tests · secret scan · separate-model verifier (last resort) | Proof | Ornith two-layer defense; reward-hacking benchmark (arXiv 2605.02964); PBT breaks the "cycle of self-deception" |
| **Disobey** | ignores rules/skills/constraints | **Tool-call enforcement** (phase_guard) · immutable test isolation · **no escape hatches** (no inline-disable) · **small focused skills** (defeat lost-in-the-middle) | Enforcement + Context | escape-hatch ban; skill-bloat 77%→97% (Nick Nisi) |
| **Injected-disobey** *(R4)* | obeys instructions smuggled into retrieved context / tool output instead of the SPEC | **Action-provenance check** (every action must trace to the frozen SPEC) · **retrieved content is DATA, never INSTRUCTIONS** · OS-level isolation of the acting layer | Enforcement + Proof | "tool output is a prompt-injection surface" — 2026 sandbox-escape research |

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
2. **Memory bank** (`.techne/context/`) — durable, cross-session building context, stored
   in the **Open Knowledge Format (OKF)** — Techne's adopted standard
   ([docs/open-knowledge-format-context.md](../open-knowledge-format-context.md)):
   **one concept per markdown file** + YAML frontmatter + **markdown links as graph edges**
   + `index.md` for progressive disclosure + `log.md` for chronology. Concept types map
   1:1 to the harness's artifact kinds: `domain` / `decision` / `runbook` / `risk` /
   `skill-note` / `eval-note` / `policy-note` / `source-note`. This subsumes the old
   "memory bank + wikilink graph" into one git-versioned, human-readable, agent-parseable
   file standard — no database until plain files demonstrably stop being enough (YAGNI).
   Still includes the amortized deterministic map (`project_digest`, `file_roles`,
   `commands`) from `context_build.py`, now emitted as OKF concept files; extended with the
   **context-gap detector**. **OKF's promotion rule is the on-ramp to the rest of the
   harness:** when a concept becomes enforceable, it is promoted into a **gate** (→ Gate
   Registry), eval, skill, or policy — this is how durable context graduates into mechanical
   enforcement.
3. **Per-task SPEC** (`.techne/loop/spec.md`) — the frozen, authoritative contract for
   *this* task (EARS-style requirements + acceptance criteria + FILE_SCOPE). This is the
   single source of truth the whole loop verifies against. **It is hashed and frozen at
   creation** — the agent cannot rewrite the goalposts (anti-drift, anti-lie).
   SPECIFY also **extracts model-independent properties/invariants** the solution must
   satisfy (the PBT contract — see Proof Spine) and runs a **spec-soundness gate**: a spec
   that is internally contradictory, or that yields *no checkable property*, is
   underspecified → BLOCK. (PBT-on-spec mechanically catches underspecification; this is the
   automated answer to "who validates the spec" — bounded, see §9.8.)

**Memory substrate — fast working tier vs deep durable tier.** The three layers above are
*what* is in context; they live on a **two-tier memory substrate** that keeps the working
window lean (out of the "dumb zone") while preserving full detail durably. On **Hermes**
this maps directly to the host's native memory + Honcho; other harnesses map to their
equivalents:

| Tier | Job | Hermes | Claude Code |
|---|---|---|---|
| **Fast / working** | the lean, high-signal set the model reasons over *right now*; session-scoped; compacted | **native memory** | session context + `CLAUDE.md` |
| **Deep / durable** | full detail, cross-session: mistake ledger, decisions, retros, prior task outcomes, conclusions | **Honcho** | `.claude/.../memory/` files + `.techne/memory/` |

The loop uses both tiers explicitly:
- **GROUND retrieves from the deep tier into the fast tier, just-in-time** — pull only the
  Honcho/durable detail this SPEC touches into the working window. Never load the whole deep
  store (that *is* the dumb-zone failure).
- **SEAL writes durable conclusions back to the deep tier** — the task's decisions, lessons,
  and outcome are written to Honcho/durable memory so the next task's GROUND can find them.
  The fast tier is disposable; the deep tier is the source of truth.

This is the research's "intentional compaction" made architectural: native memory is the
compaction layer, Honcho is the durable detail it compacts *from*. **On disk, the durable
tier is OKF** (`.techne/context/`): GROUND starts at `index.md` and **follows only the links
the SPEC needs** — progressive disclosure *is* the lean-retrieval mechanism, so the working
window never loads the whole store.

**Discipline (research-driven), not just files:**
- **Lean context / intentional compaction.** Keep the working window well under the dumb
  zone (~40%). Prefer restart-with-compaction over long correction chains — "the most
  likely continuation after a mistake is another mistake."
- **Grounding over memory.** Before IMPLEMENT, retrieve the *actual* file contents and
  symbols the SPEC touches into context. The agent edits what it can see, not what it
  recalls. (Hashline then proves it saw the real bytes.)
- **Context-gap detector (mechanical, not heuristic).** Derive the codebase's actual
  conventions by **static analysis / AST traversal** (naming, structure, stack mix, test
  patterns, lint configs) and **diff them against the documented constitution + memory
  bank**. Where the code uses a stack/pattern with no corresponding card (e.g. 60% React,
  no React guidance; hundreds of tests, no testing card) → flag the gap and require a card
  before IMPLEMENT. (This is the Packmind `context-evaluator` pattern — comparing
  documentation coverage to the real tree.)
- **Don't narrate what the agent can already see.** A good context engine reads the
  codebase so you don't have to describe it. Reserve the lean window for what the agent
  *can't* derive from tools; let it probe live (read the file, run the linter) rather than
  pre-loading static dumps that burn attention budget.

**Cold-start bootstrap (R4).** On a fresh repo the OKF store and Honcho are empty — the
Context Engine has nothing to ground on. A one-time **BOOTSTRAP pass** seeds it: mechanically
derive the initial context from the codebase itself (AST/static-analysis conventions, detected
stack, `context_build.py`'s deterministic map, test patterns) into verified OKF concept files +
a `constitution.md`. Critically, the seed is **execution-verified, not LLM-asserted** — a
bootstrapped contract whose build/test doesn't actually pass is rejected (the BootstrapAgent
pattern: extract → plan → deterministically verify → repair). Thereafter every SEAL writes
durable OKF/Honcho concepts, so cold-start is a one-time amortized cost that the learning loop
compounds. *Irreducible residual:* a **greenfield** repo (no code yet) has nothing to extract
from — there the conventions must come from the SPEC and the constitution, which is exactly
where richer initial context pays off most (ties to §9.8).

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
- **Layer 3 — boundary completeness (R4).** The 2026 evidence is that escapes come from
  *partial* boundaries drawn in the wrong place, not absent ones. Three hardenings:
  - **Deny-by-default, including paths that don't exist yet.** The boundary is an
    *allowlist* of what the implementer may write (the current phase artifact + source
    inside FILE_SCOPE); everything else is denied — **even if the path is absent now**
    (`tests/`, `.techne/gates/`, `.techne/audit/`, gate scripts, config dirs). (The Codex-CLI
    escape was exactly this: a config dir didn't exist, so `apply_patch` created it ungated.)
  - **Boundary self-test.** A startup gate that *probes* the surface the way attackers do —
    attempt-to-write to verification paths, check subprocess inheritance, check per-task
    secrets scoping — and fails closed if any probe succeeds. Enumeration is itself a gate.
  - **OS-level isolation for the acting layer.** Reasoning may run on normal infra, but the
    *actions* (apply + run tests) execute in a real sandbox — gVisor/Firecracker-class, **not
    a standard container** (shared kernel / Docker-socket = escape). "The orchestration layer
    is the firewall between thinking and acting." (Wired in W6.)
  - **Network egress allowlist (the exfiltration layer).** The sandbox denies outbound
    network by default; only an allowlist (package registry, the model endpoint) is
    permitted. This closes the data-exfiltration vector — code that calls an attacker
    endpoint, or the dark-factory case of a harvested secret leaving in a log/request — which
    the filesystem/config layers don't touch. Egress + filesystem + secrets-scoping + config
    protection are the **four mandatory layers** that vendor guidance (Microsoft/NVIDIA)
    converges on as the completeness checklist.
- **Action provenance (anti-injection).** Retrieved context — code, Honcho, web, tool
  output — is a **prompt-injection surface**: an attacker payload can ride inside a JSON
  response or a source comment. Rule: **retrieved content is DATA, never INSTRUCTIONS.**
  Every IMPLEMENT action must trace to the **frozen SPEC**, not to text the agent read while
  grounding. The boundary monitor flags actions with no SPEC provenance. (This is the cost
  of a context-heavy design — the bigger the Context Engine, the larger this surface — so it
  is defended explicitly, not assumed away.)

**On top of the boundary, defense-in-depth (no single check is trusted):**
**The proof hierarchy — most-trusted (model-independent) to least (gameable):**

1. **Model-independent invariants (the trust floor).** The strongest proof doesn't involve
   an LLM at all. This breaks the **"cycle of self-deception"** — LLM-written tests share
   the blind spots of LLM-written code, so example-based tests can pass on both being wrong
   the same way. Defenses that escape it:
   - **Property-Based Testing (PBT).** Invariants that hold regardless of which model wrote
     the code (round-trip, idempotence, conservation: "factors multiply back to the input").
     PGS-style approaches show large gains over example TDD, and PBT *also validates the
     spec* — it mechanically catches underspecification. These properties are derived at
     SPECIFY (§ Context Engine) and are ground truth the implementer can't game.
   - **Static analysis + type checks + the compiler.** Deterministic, model-free: types,
     lints-as-errors, architecture-boundary checks, dead-code/complexity sensors.
2. **Mechanical execution proof.**
   - **Real tests, SHA-gated.** VERIFY runs the actual suite; output is hashed so faked
     stdout is rejected. Non-empty + explicit count (an empty suite is a lie).
   - **Mutation gate.** Mutate the changed source; the frozen tests must catch it. A suite
     that survives mutation is weak/accommodating → BLOCK. The only HITL-free mechanism that
     catches a test that was weak **from the start**; must be un-suppressible.
   - **Secret / forbidden-pattern scan.** The documented dark-factory failure (tests passed,
     diff clean, yet a plaintext secret and a token-audience mismatch shipped) proves
     test-pass is *necessary, not sufficient*. Deterministic scan, not a judge.
3. **LLM judgment — last resort, defense-in-depth only.**
   - **Test authorship separated + isolated.** Tests authored against the SPEC by a
     **different model family** than the implementer (preference-leakage avoidance), in a
     context that never sees the implementation. Frozen + hashed before IMPLEMENT.
   - **Separate-model verifier** (VerifiAgent-style: meta-check completeness + tool-based
     correctness) reads the diff against the SPEC for scope creep / unstated behavior.

> **The rule:** trust flows *up* this list. An LLM judge never overrides a mechanical
> result, and is never the sole basis for "done." Falsification (testing/PBT) disproves;
> only formal methods prove — so where a domain has cheap invariants, prefer them.

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

**The Gate Registry — what gates exist and why you trust each (provenance ledger).**
In a zero-HITL system you must be able to ask, at any time, *"what gates is this thing
actually running, which did it invent itself, and what's the evidence each one works?"*
`.techne/gates/registry.json` is that living ledger — one entry per gate:

| Field | Meaning |
|---|---|
| `id` / `failure_mode` | what it is, which of drift/hallucinate/lie/disobey it defeats |
| `kind` | **mechanical** (deterministic, model-independent) vs **eval-based** (learned/scored) |
| `provenance` | human-authored, or **GRPO-promoted** (with the promotion event id) |
| `status` | `proposed → calibrating → proven → live → retired` |
| `catch_rate` / `false_block_rate` | measured vs the labeled corpus (W8) |
| `human_decommissioned_at` | when the calibration human was removed from this gate |
| `backing_cases` | the eval cases that justify it |

Surfaced via **`techne gates`** (list/show) and summarized in `techne doctor`. Every gate
creation, calibration, promotion, or retirement is an audit-chained event. This is both a
product feature (you always see the safety surface) and the audit trail for the
HITL-removal protocol (§6) — no gate goes `live` without a registry entry showing its
evidence.

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
| **SPECIFY** | *(new)* | `spec.md` — frozen EARS contract + acceptance criteria + FILE_SCOPE + **extracted invariants/properties**; tests authored + frozen by a separate model | contract exists, hashed; **spec-soundness gate** (no checkable property → BLOCK); tests frozen (drift, lie) |
| **GROUND** | RECALL | `ground.md` — real code + memory-bank refs + **deep-tier (Honcho) retrieval into the lean window** + context-gap check | real context present, no unfilled gaps (hallucinate, drift) |
| **IMPLEMENT** | IMPLEMENT | `diff.txt` | hashline + scope + forbidden-pattern + boundary monitor (hallucinate, drift, lie, disobey) |
| **VERIFY** | VERIFY | `test_output.txt` | **property-based invariants** + static analysis/types + real SHA-gated tests + **mutation gate** + secret scan + (last-resort) separate-model verifier (lie) |
| **SEAL** | CONCLUDE | `seal.md` | retro markers + verify ref + commit; **writes durable conclusions to the deep tier (Honcho)**; fires learning loop |
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
3. **Promotion gate (the new ratifier) — Goodhart-hardened.** A candidate edit is applied
   to a *shadow* copy and must clear **multiple independent signals**, not one score:
   (a) **beat the incumbent on the held-out eval measured by pass^k** (success every run,
   not best-of-k); (b) **zero boundary violations**; (c) pass the **mechanical gates**
   (mutation, hashline, secret scan) — which are model-independent and far harder to game;
   (d) stay within a **divergence bound** from the incumbent (KL-style — prefer
   conservative edits; a large jump to win the eval is itself a red flag). Lose, tie, or
   trip any signal → discarded.
4. **The eval set rotates and is contamination-free.** A *frozen* eval set is
   self-defeating: Skalse et al. (2022) prove **no non-trivial proxy reward is guaranteed
   unhackable**, and a fixed target gets Goodharted given enough optimization pressure. So
   the held-out set (i) lives **inside the immutable boundary** (the policy can never read
   it — canary discipline), (ii) **continuously ingests new real failures** from the
   calibration corpus (W8), and (iii) **retires cases that saturate**. It is a moving,
   blind target, not a static benchmark.
5. Promotion is an audit-chained, reversible event that **writes a Gate Registry entry**
   (provenance = GRPO-promoted, with the evidence). No human, no self-congratulation.

**The trust hierarchy (the load-bearing correction).** The mechanical gates are the **trust
floor** — robust because they're deterministic and model-independent. The eval-based
promotion is only the **improvement signal** — inherently Goodhart-prone, so it is *never*
the sole anchor of trust, only the thing that decides whether an *evolution* is allowed.
Per-task safety always rests on the mechanical proof spine, not on a learned score. This is
"self-improving but not self-deceiving": the scaffold is learnable (the Ornith insight), but
the floor beneath it is mechanical and unreachable. **Honest residual:** no proxy is
unhackable, so this is a *ratchet* — it must keep ingesting new real failures forever; there
is no static "solved." (§9.7)

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
| **W2** | **Context Engine** — `constitution.md`, **OKF durable store in `.techne/context/` (index.md + one-concept-per-file + log.md)**, `SPECIFY` phase + frozen hashed `spec.md`, grounding retrieval, context-gap detector, lean-context/compaction discipline, **two-tier memory wiring (GROUND pulls from Honcho→native, SEAL writes back to Honcho)** | Drift, Hallucinate | W0 |
| **W3** | **Proof Spine** — **property-based invariants + static analysis/types (model-independent trust floor)**; mutation gate (un-suppressible; cost = changed-lines-only + selective operators + weak mutation + cap, full sweep nightly); separated+isolated test authorship (different model family); secret/forbidden scan; separate-model verifier (last resort) | Lie | W1, W2 |
| **W3b** | **Gate Registry** — `.techne/gates/registry.json` + `techne gates`; every gate's kind/provenance/status/catch-rate; audit-chained | trust transparency | W1 |
| **W1b** | **Boundary completeness** — deny-by-default allowlist incl. non-existent paths; boundary self-test (attempt-to-write/subprocess/secrets probes); action-provenance (retrieved content = data, not instructions) | Lie, Injected-disobey | W1 |
| **W2b** | **Cold-start BOOTSTRAP** — one-time pass: derive + **execution-verify** initial OKF store + constitution from the codebase (BootstrapAgent pattern) | Drift, Hallucinate (fresh repos) | W2 |
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

1. **Mutation testing cost.** ~~Open.~~ **Resolved (round 2).** Cost model from the 2026
   literature: mutate **changed lines only** (incremental, PR-diff scope) + **selective
   operators** (a sufficient subset, not every operator) + **weak mutation** (stop once the
   mutated statement executes) + a hard cap, with a **full mutation sweep nightly** out of
   band. Mutation-as-a-sensor for agent-written tests is established practice (Thoughtworks,
   Meta ACH, testdouble). Residual: per-codebase tuning of the operator subset.
2. **Separate-model verifier preference leakage.** ~~Open.~~ **Largely resolved (round 3).**
   The fix isn't a better judge — it's *needing the judge less*. **Property-based invariants
   + static analysis + types** are model-independent ground truth (they break the "cycle of
   self-deception" where LLM tests share LLM-code blind spots). The LLM verifier is demoted
   to last-resort defense-in-depth; trust rests on the model-independent floor. Residual:
   domains with no cheap invariants still lean on the judge — flagged per-task.
3. **Context-gap detector is heuristic.** ~~Open.~~ **Resolved (round 3).** Now mechanical:
   AST/static-analysis-derived conventions diffed against the documented constitution
   (Packmind `context-evaluator` pattern), not a guess. Residual: novel patterns with no
   linter/AST signature can still hide — grown from real misses via the learning loop.
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
   decommissioned per gate. **Decided (2026-06-28): keep the calibration role** — cheap
   evidence that each gate works before autonomy rests on it. The Gate Registry surfaces
   exactly which gates have been calibrated and decommissioned, so the human's removal is
   always visible and evidence-backed.

7. **No proxy reward is unhackable (Skalse et al. 2022) — the promotion gate is a ratchet,
   not a solution.** *Resolved-as-managed (round 2).* A self-improving loop optimizing
   against any fixed eval will eventually Goodhart it. Mitigations now in §4: the eval set
   rotates, lives inside the immutable boundary (contamination-free), and continuously
   ingests new real failures; promotion requires multiple independent signals + a
   divergence bound; and **the mechanical gates, not the eval, are the trust floor.**
   Residual (unavoidable): there is no static endpoint — the system must keep ingesting new
   real failures forever. Accept this as a property, not a bug.

8. **The irreducible core — the spec-intent gap (the deepest residual, named honestly).**
   The whole framework can prove **code ⊨ spec** (the proof spine) and can *largely*
   validate **spec is internally sound** (PBT-on-spec catches underspecification — 2026
   work found ~10%). What no harness can guarantee without a human is **spec ⊨ the user's
   true, unstated intent.** A perfectly-built solution to a subtly-wrong spec passes every
   gate. This is exactly the job the human reviewer did last and best.
   *What we do about it:* (a) shrink the gap with the Context Engine (ground the spec in the
   real ticket + real code so there's less room to misinterpret); (b) force testable EARS
   criteria + extracted invariants (less vagueness to hide in); (c) this is precisely where
   the **calibration human stays longest** (§6) and where context investment has the highest
   return. *Honest bottom line:* zero-HITL makes the agent **trustworthy about what it
   claims** (no drift, no hallucination, no lying, no disobedience) — it does **not** make
   the *specification* infallible. That last gap closes with better context, not with more
   gates, which is exactly your thesis ("building context is the real issue") proven from
   the other direction.

9. **Boundary completeness — the boundary is only as good as its enumeration (R4).**
   *Addressed, with a standing duty.* Partial boundaries are the real escape vector (2026
   sandbox-escape wave). Mitigations now in Pillar II Layer 3: deny-by-default incl.
   non-existent paths, a boundary self-test that probes the surface, OS-level isolation
   (gVisor/Firecracker) for the acting layer, and action-provenance against injection.
   Residual: enumerating *every* verification surface is an ongoing duty — new tools/paths
   must be added to the allowlist denominator, and the self-test must grow with them. This
   is the same ratchet as §9.7: a living deny-list, never "done."

10. **Prompt injection via retrieved context (R4) — the cost of a context-heavy design.**
   The Context Engine is the plan's strength *and* its largest injection surface: grounding
   retrieval (code, Honcho, web, tool output) can carry an attacker's instructions.
   *Mitigation:* retrieved content is treated as **data, not instructions**, and actions must
   trace to the frozen SPEC (provenance check). *Residual:* provenance checking is heuristic
   at the margin — a sufficiently SPEC-shaped injection could pass. The mechanical proof
   spine (tests/mutation/secret-scan) is the backstop, since an injected action still has to
   survive verification it can't reach.

---

## 10. Migration From Current Code

| Plan element | Lands in | Current state |
|---|---|---|
| Gate core | `scripts/next.py` `_check_*_gates` | ✅ exists; W0 points Autopilot at it |
| Hashline | `scripts/hash_gate.py` | ✅ built |
| Boundary monitor | extend `harness/plugins/phase_guard.py` + audit chain | ⚠️ partial (write-block; add verification-surface coverage + negative reward) |
| Mutation gate | new `scripts/mutation_gate.py`, wired into VERIFY like `node_gate` | ❌ new (W3) |
| SPECIFY phase + frozen spec | `next_state.PHASE_SEQUENCE` + new RECALL→GROUND rename | ❌ new (W2) |
| Context Engine | `harness/context_build.py` + `constitution.md` + **OKF `.techne/context/`** + gap detector | ⚠️ partial (OKF standard adopted; emit context_build output as OKF files) |
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
- [Mutation Testing Cost Reduction Techniques: A Survey (Offutt/Untch taxonomy)](https://www.researchgate.net/publication/224132836_Mutation_Testing_Cost_Reduction_Techniques_A_Survey)
- [Keep your coding agent on task with mutation testing — testdouble](https://testdouble.com/insights/keep-your-coding-agent-on-task-with-mutation-testing)
- [Meta Applies Mutation Testing with LLM (ACH) — InfoQ](https://www.infoq.com/news/2026/01/meta-llm-mutation-testing/)
- [Maintainability sensors for coding agents — Martin Fowler](https://martinfowler.com/articles/sensors-for-coding-agents.html)
- [Goodhart's Law in Reinforcement Learning — arXiv 2310.09144](https://arxiv.org/pdf/2310.09144)
- [Over-Optimization — RLHF Book (Nathan Lambert)](https://rlhfbook.com/c/14-over-optimization)
- [Beyond Goodhart's Law: Dynamic Benchmark for Compliance — arXiv 2606.07805](https://arxiv.org/html/2606.07805)
- [Use Property-Based Testing to Bridge LLM Code Generation and Validation (PGS) — arXiv 2506.18315](https://arxiv.org/pdf/2506.18315)
- [PBT for Validating LLM-Synthesised Specifications — Proofs and Intuitions (2026)](https://proofsandintuitions.net/2026/05/18/property-based-testing-specifications/)
- [VeriScale: Adversarial Test-Suite Scaling for Verifiable Code Generation — arXiv 2605.22368](https://arxiv.org/html/2605.22368)
- [Writing AI coding agent context files is easy. Keeping them accurate isn't (context-evaluator) — Packmind](https://packmind.com/evaluate-context-ai-coding-agent/)
- [Agent READMEs: An Empirical Study of Context Files for Agentic Coding — arXiv 2511.12884](https://arxiv.org/pdf/2511.12884)
- [Mutation Testing Cost Reduction (changed-lines/selective/weak) — academia survey](https://www.academia.edu/10784640/Mutation_testing_cost_reduction_techniques_a_survey)
- [The Race to Ship AI Tools Left Security Behind, Part 1: Sandbox Escape — Cymulate](https://cymulate.com/blog/the-race-to-ship-ai-tools-left-security-behind-part-1-sandbox-escape/)
- [How to sandbox AI agents in 2026: MicroVMs, gVisor & isolation — Northflank](https://northflank.com/blog/how-to-sandbox-ai-agents)
- [AI Agent Sandboxing: Enterprise Security Guide 2026 — BeyondScale](https://beyondscale.tech/blog/ai-agent-sandboxing-enterprise-security-guide)
- [BootstrapAgent: Distilling Repository Setup into Reusable Agent Knowledge — arXiv 2605.15815](https://arxiv.org/abs/2605.15815)
- [Context Bootstrapping: Solving the AI Agent Cold Start Problem — Atlan](https://atlan.com/know/context-bootsrapping/)
