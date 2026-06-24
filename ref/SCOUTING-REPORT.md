# Scouting Report: Productizing Techne

> What to borrow from OMO / OMH / oh-my-models to turn Techne from a raw enforcement engine into a product people can actually pick up and use.
>
> Sources studied: [oh-my-openagent.md](oh-my-openagent.md), [oh-my-hermes.md](oh-my-hermes.md), [oh-my-models.md](oh-my-models.md)
> Grounded against: `README.md`, `SKILL.md`, `commands/techne.toml`, `skills/`, productization-roadmap memory.
> Date: 2026-06-24

---

## 1. The Core Finding

**OMO is a product. Techne is a raw engine.**

The gap is not in the spine — Techne's enforcement (phase_guard at the tool-call layer, SHA-chained audit, watchdog cron, GRPO with human ratification) is *categorically stronger* than OMO's prompt-based discipline. The gap is the **on-ramp**:

| | OMO (the product) | Techne (today) |
|---|---|---|
| Start a task | type `ultrawork` or `/start-work` | `mkdir -p .techne/loop && echo '{"task_id":"x","phase":"RECALL"}' > .techne/loop/state.json` |
| Plan a task | Prometheus interviews you (Tab) | hand-write a ticket in the right schema |
| Advance a phase | automatic | write the exact artifact file, then `./next` |
| Check health | `bunx oh-my-openagent doctor` (6-category) | read watchdog exit codes |
| See work state | `bunx ... boulder` | cat `.techne/loop/state.json` |
| Resume later | `/handoff` → boulder rehydrate | nothing |
| Pick models | `oh-my-models use mixed` | edit `~/.hermes/config.yaml` by hand |

Every Techne interaction is a hand-assembled filesystem ritual that the SKILL.md's own "Pitfalls" section admits has been corrected **4+ times** because it's so easy to get wrong. OMO took the same disciplined-loop idea and wrapped it in a surface a human (or agent) can drive without memorizing artifact paths and gate-string formats.

**The productization thesis: keep Techne's hard spine, build OMO's soft surface on top of it.**

---

## 2. The Three Highest-Leverage Borrows

These three, in order, convert Techne from "engine I operate by hand" to "product I talk to."

### A. A real `techne` CLI (replaces the filesystem ritual)

**What OMO has:** `bunx oh-my-openagent <install|doctor|boulder>` — a single binary with discoverable subcommands.

**What Techne has:** `scripts/next.py`, `scripts/watchdog.py`, `scripts/knowledge_graph.py`, `scripts/audit_chain.py` — four separate Python scripts invoked by absolute path, plus a `commands/techne.toml` slash command. The roadmap already lists "Packaging + CLI" as item 5 but it's unbuilt.

**Proposal — one console entry point:**
```
techne init <task-id>      # creates .techne/loop/state.json, scaffolds dirs (no more echo-JSON)
techne next                # advance a phase (wraps next.py)
techne status              # current phase + gates + RL health (wraps knowledge_graph + blocked.log)
techne doctor              # see borrow C
techne plan                # see borrow B
techne handoff             # see §3
techne graph <query>       # wraps knowledge_graph.py
```
Ship as a `pyproject.toml` console_scripts entry point so `pip install -e techne/` gives a real `techne` on PATH. This single move deletes ~80% of the "Pitfalls" in SKILL.md (the ones about hand-formatting state.json, artifact paths, SHA prefixes).

**Effort:** Low-Medium. The logic exists; this is a thin Click/argparse wrapper + packaging. Highest ROI item in the report.

### B. A planning interview (`techne plan`) — Prometheus for Techne

**What OMO has:** Press Tab → **Prometheus** interviews you like an engineer (scope, ambiguities, constraints) → **Metis** gap-analyzes → **Momus** validates → produces a "Decision-Complete plan" that leaves zero choices to the implementer → `/start-work` executes it.

**What Techne has:** `skills/grill.md` (stress-test a plan) and `skills/persona-brainstorm.md` (discover what to build). Both are *single-pass review* skills, not an *interactive intake interview*. The ticket schema (OBJECTIVE/CONSTRAINTS/DONE_WHEN) exists but the human has to fill it in cold.

**The gap:** Techne has no front door that turns a vague human request into a gated, ready-to-dispatch ticket. Today the host agent guesses the ticket, and a bad ticket silently produces a bad RECALL.

**Proposal:** A `techne-interview` skill (and `techne plan` CLI verb) that runs a Socratic intake — OMH's `omh-deep-interview` is a ready-made reference design (Socratic requirements interview with *coverage tracking*). It interviews until the ticket schema is fully populated and DONE_WHEN is concrete, then hands a Decision-Complete ticket to `techne init`. Chain `grill` after it as the adversarial pass (OMO's Metis/Momus role).

```
techne plan  →  interview (coverage-tracked)  →  grill (adversarial)  →  Decision-Complete ticket  →  techne init
```

**Effort:** Medium. Skill authoring + a coverage tracker. OMH's `omh-deep-interview` and `omh-ralplan` are direct design references.

### C. `techne doctor` — a friendly health check

**What OMO has:** `bunx oh-my-openagent doctor` runs a **6-category health check** and tells the user what's wrong in plain language.

**What Techne has:** `watchdog.py` with exit codes 0–4 (healthy/stall/tamper/skip/orphan) — designed for *cron*, not for a *human* asking "is my setup OK?" There's also `skills/pipeline-health/`.

**Proposal:** A `techne doctor` that aggregates into a human-readable report:
- Is `.techne/` present and well-formed?
- Is `state.json` valid / is a pipeline active / is it stalled?
- Is the audit chain intact (run the watchdog tamper check)?
- Are there pending GRPO proposals waiting for ratification?
- Is the context pack fresh or stale?
- Are the eval suites passing (86/87)?
- Is the host wired correctly (SKILL.md registered, plugin auto-activating)?

Each with ✅/⚠️/❌ and a one-line fix. This is the difference between "Techne is broken and I don't know why" and "Techne told me my chain was tampered and how to recover."

**Effort:** Low. Mostly aggregation of signals that already exist (watchdog, blocked.log, rl.jsonl, eval runner).

---

## 3. The Interactive / Workflow Layer (the "more interactive with user" goal)

### D. Natural-language modes (the `ultrawork` pattern)

**What OMO has:** Five typed keywords (`ultrawork`, `search`, `analyze`, `team`, `hyperplan`) that inject mode-specific behavior — no command syntax, just say the word in chat.

**What Techne has:** Three internal modes (EXPLORE / SCOUT / IMPLEMENT) but they're *dispatch routing*, invisible to the user. The user can't say "just do it."

**Proposal:** Map Techne's existing modes to user-facing trigger words, documented in SKILL.md's Quick Route so the host recognizes them:
- `ultrawork` / `ulw` → run the full `plan → init → next×5 → done` loop autonomously, surfacing only HITL blocks and phase reports.
- `scout <topic>` → SCOUT mode (already exists, just needs a trigger).
- `grill <plan>` → the adversarial review (skill exists).

The key UX shift: today the *host* must remember to drive the pipeline (SKILL.md nags about this 4+ times). A trigger word makes the *user* the one who opts into autonomy, and the loop runs itself.

**Effort:** Low-Medium. Trigger recognition + an autonomous loop driver (the `driver.py` from roadmap item 2 is the engine; this is its conversational front).

### E. Handoff / session continuity (the `boulder.json` pattern)

**What OMO has:** `/handoff` generates a detailed context summary; `boulder.json` tracks work state so a *new session* (even a different agent) can resume mid-task.

**What Techne has:** `.techne/loop/state.json` (current phase only) + the Honcho precompaction checkpoint skill. State survives, but there's no *handoff document* — a human picking up tomorrow gets a phase name, not "here's where we are and why."

**Proposal:** `techne handoff` writes a `.techne/loop/handoff.md`: active task + ticket, phases completed with proof lines, open HITL blocks, next action, and the RECALL context that's already loaded. On `techne init --resume`, it rehydrates. This pairs naturally with the existing context-amortization pack.

**Effort:** Low-Medium. Most data exists in state.json + audit chain + loop artifacts; this is a serializer + a resume path.

### F. Phase reports as first-class UX (already half-built — finish it)

SKILL.md RULE 6 already mandates forwarding the full `./next` phase report to the user. This is *good* and OMO-like (structured, labeled responses). **Lean into it:** make the phase report a designed artifact (gates passed, diff summary, test results, next step, RL delta) rather than raw text. This is Techne's equivalent of OMO's "agents label their actions and surface decision points."

**Effort:** Low. Polish existing output.

---

## 4. The Reliability Borrow: Hashline

**What OMO has:** **Hashline** — every file read is tagged with a content hash; edits validate against the hash before applying. Reported edit-success improvement **6.7% → 68.3%**. Solves the "whitespace reproduction" problem.

**Why it matters for Techne:** SKILL.md has an entire section (lines 97–110) on the `patch` tool mangling whitespace, dropping lines, and corrupting `\n` literals — with a "recovery from corruption" procedure. That's *exactly* the problem Hashline solves. Techne's IMPLEMENT gate checks that a diff *has markers* (`@@`/`---`), but not that the diff *applies cleanly against the real file*.

**Proposal:** Add a pre-IMPLEMENT-gate hash check: when the diff is submitted, validate each hunk's context lines against the current file content hash before accepting it into `diff.txt`. Reject with "stale read / hash mismatch — re-read the file" instead of letting a corrupt patch through to VERIFY. This is roadmap item 3 (sandboxed diff-application) but cheaper and upstream — catch the bad patch at the gate, not at the test run.

**Effort:** Medium. New gate logic in the IMPLEMENT phase; needs a read-hash registry.

**This is the single highest-confidence quality borrow** — OMO published a before/after metric, and Techne has the exact pain documented in its own skill file.

---

## 5. Model Routing (the oh-my-models pattern) — defer, but note

**What OMO/oh-my-models have:** Per-agent model fallback chains and presets (`use mixed`, `use fast`), category routing (`quick`→cheap model, `ultrabrain`→strong model).

**What Techne has:** Deliberately model-agnostic — "Techne never calls a model." Subagent model is set once in `~/.hermes/config.yaml` (`deepseek-v4-flash:free`).

**The tension:** Techne's purity ("no API key, no model call") is a *real architectural virtue* and a differentiator. Don't break it. But there's a thin, honest version: Techne could *recommend* a model tier per mode in the dispatch ticket (RECALL→cheap/large-context, IMPLEMENT→strongest coder — SKILL.md already says this in prose) and expose a `techne models` config that the *host* reads. This is advisory routing, not Techne calling models.

**Recommendation:** Low priority. The oh-my-models preset UX is nice but it's solving OMO's multi-provider problem, which Techne doesn't have. Capture the *advisory* per-phase tier hint in the phase report; skip the rest.

**Effort:** Low (advisory only). Don't build the full preset system.

---

## 6. What NOT to Copy

- **OMO's soft discipline** (todo trackers, comment-checkers, "loop until done" prompts). Techne's hard enforcement is strictly better. Keep it.
- **OMO's 11-agent zoo** (Sisyphus/Hephaestus/Atlas/Oracle/…). Techne's 3-mode dispatch (EXPLORE/SCOUT/IMPLEMENT) is simpler and sufficient. Naming agents after Greek gods is branding, not capability.
- **Multi-provider model orchestration.** Solves a problem Techne chose not to have.
- **Team Mode / parallel mailbox.** Techne is serial-by-design (one phase, on disk, auditable). Parallelism fights the audit-chain invariant. Don't.
- **PostHog telemetry.** Techne's no-network stance is a selling point for security-conscious users. Keep it.

---

## 7. Prioritized Backlog

Ordered by (impact on "is this a product") ÷ effort:

| # | Item | Section | Effort | Why first |
|---|------|---------|--------|-----------|
| 1 | **`techne` CLI** (init/next/status/doctor/plan/handoff/graph) | 2A | Low-Med | Deletes the filesystem ritual + 80% of SKILL.md pitfalls. Everything else hangs off it. |
| 2 | **`techne doctor`** | 2C | Low | Cheap, high trust-building. Turns watchdog codes into answers. |
| 3 | **Phase report polish** | 3F | Low | Already mandated; finish the UX. |
| 4 | **Hashline gate** | 4 | Med | Highest-confidence quality win; fixes documented pain. |
| 5 | **`techne plan` interview** | 2B | Med | The front door. Turns vague requests into gated tickets. |
| 6 | **`ultrawork` trigger + autonomous loop** | 3D | Low-Med | The "just do it" UX; engine (driver.py) already exists. |
| 7 | **`techne handoff` / resume** | 3E | Low-Med | Session continuity; data mostly exists. |
| 8 | Advisory model-tier hint | 5 | Low | Nice-to-have; don't build the preset system. |

**The first three are a weekend.** They convert Techne from "engine I operate by hand" to "tool I run." Items 4–7 are the next sprint and deliver the interactive product the goal is asking for.

---

## 8. One-Paragraph Pitch (the product Techne becomes)

> *Techne is the disciplined engineering harness that can't be talked out of doing it right. Tell it what you want in plain language — `techne plan` interviews you until the task is decision-complete, then `ultrawork` drives it through RECALL → IMPLEMENT → VERIFY → CONCLUDE with hard gates that block at the tool-call layer, a tamper-evident audit chain, and edit-hash validation so patches never corrupt your files. `techne doctor` tells you if anything's off; `techne handoff` lets you walk away and resume tomorrow. It never calls a model or needs an API key — your agent does the thinking, Techne guarantees the discipline — and it quietly learns which of its own prompts and skills produce better code, proposing improvements for you to approve. The rigor of a senior reviewer, the surface of a CLI you already know.*

---

## Appendix: Reference Crosswalk

| Borrow | OMO source | OMH source | Techne touch-point |
|---|---|---|---|
| CLI surface | `oh-my-openagent <cmd>` | `hermes skills` | `scripts/*.py` → `pyproject.toml` entry point |
| Planning interview | Prometheus + `/start-work` | `omh-deep-interview`, `omh-ralplan` | `skills/grill.md`, `skills/persona-brainstorm.md`, ticket schema |
| Adversarial plan review | Metis + Momus, `hyperplan` | `omh-ralplan` (Planner/Architect/Critic) | `skills/grill.md` |
| Health check | `doctor` | — | `scripts/watchdog.py`, `skills/pipeline-health/` |
| Handoff/resume | `/handoff`, `boulder.json` | — | `.techne/loop/state.json`, honcho checkpoint skill |
| Autonomous loop | `ultrawork`, `/ralph-loop` | `omh-ralph`, `omh-ralph-driver` | `harness/driver.py`, 3-mode dispatch |
| Edit reliability | Hashline | — | IMPLEMENT diff gate, SKILL.md `patch` warning |
| Model routing | category system | — | `delegation.model` config (advisory only) |
| Verified execution | `/refactor` (LSP+AST+TDD) | `omh-ralph-task` | `skills/tdd.md`, VERIFY phase |
