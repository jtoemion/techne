# Scouting Report 2 — Loop Once More

> Second pass against OMO / OMH / oh-my-models after the v0 build sprint.
> Grounded against current codebase state (post-PR #8 + #9).
> Sources: `ref/oh-my-openagent.md`, `ref/oh-my-hermes.md`, `ref/oh-my-models.md`
> Date: 2026-06-25

---

## What Got Built (v0 Sprint Recap)

| # | Item | PR |
|---|------|-----|
| ✅ | `techne` CLI — init/next/status/doctor/handoff | #8 |
| ✅ | PreToolUse enforcement hook | #8 |
| ✅ | `techne doctor` | #8 |
| ✅ | Phase report redesign (box header, RL delta, preview) | #9 |
| ✅ | `techne handoff` | #9 |
| ✅ | Hashline gate (diff context validation) | #8 |
| ✅ | CC ultrawork orchestrator section | #9 |

The hard spine is solid. RECALL, IMPLEMENT, VERIFY gates are well-enforced. The
on-ramp (CLI, hooks, doctor, handoff) now exists. The one phase still under-gated
is **CONCLUDE** — and the wisdom that should flow out of it is currently dropped.

---

## Finding 1 — Wisdom Extraction Is Disconnected (High Impact, Low Effort)

### What exists in the harness

`harness/_retro_conclude.py` has a fully-built `_persist_retro()` function:

```python
def _persist_retro(task_id, reflection, task_title):
    # 1. Archive full retro to .techne/memory/retros/{task_id}.md
    # 2. Extract DECISION/LESSON/DISCIPLINE markers → ledger.py
    # 3. Extract error/cause/lesson patterns → mistakes.md
```

It parses structured markers from a retro reflection:
```
- DECISION: use pytest-httpx for async mocks — avoids event-loop teardown
- LESSON: always check .techne/context/ before searching the codebase
- DISCIPLINE: one file per IMPLEMENT phase — scope creep causes hashline failures
```

`harness/ledger.py`, `harness/mistakes.py`, `scripts/mistakes_logger.py` are
all wired to receive this data. The knowledge graph (`scripts/knowledge_graph.py`)
reads from the same stores.

### The gap

`_persist_retro` is **only called from `OrchestratorLoop._submit_retro()`** — the
model-backed Python driver. When a CC agent drives the pipeline via `./next`, the
CONCLUDE phase transitions with a gate check for:
1. "HONCHO" keyword present
2. Length ≥ 20 characters

That's it. No wisdom is extracted. The ledger stays empty. The knowledge graph
has nothing to learn from. Every task completes and the lessons evaporate.

### Fix

When `./next` transitions CONCLUDE → DONE, call `_persist_retro` against the
`conclude.txt` artifact. This is a ~10-line addition to `next.py`'s main loop,
after the wikilink rebuild block:

```python
# Already there (CONCLUDE → DONE path in next.py ~line 735):
if old_phase == "CONCLUDE":
    # ← ADD HERE: extract wisdom from conclude.txt
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent / "harness"))
        from _retro_conclude import _parse_retro_markers, _persist_retro
        conclude_text = (cwd / ".techne" / "loop" / "conclude.txt").read_text()
        _persist_retro(state.task_id, conclude_text, state.task_id)
    except Exception:
        pass  # best-effort
```

Also update the CONCLUDE gate to require the DECISION/LESSON/DISCIPLINE structure:
```python
has_markers = bool(re.search(r"^\s*[-*]\s+(DECISION|LESSON|DISCIPLINE):", text, re.MULTILINE))
results.append(GateResult(
    "retro markers",
    has_markers,
    "DECISION/LESSON/DISCIPLINE found" if has_markers
    else "missing retro markers — add at least one: DECISION: / LESSON: / DISCIPLINE:",
))
```

**Effort:** Low — code already exists, just unwired. Gate addition is 6 lines.
**Impact:** High — every completed task now feeds the knowledge graph, ledger, and
mistakes store. This is what makes Techne's learning loop close.

---

## Finding 2 — CONCLUDE Gate Is Trivially Bypassed (Low Effort Fix)

Current gate checks:
- ✅ artifact exists and non-empty
- ✅ "HONCHO" keyword present
- ✅ length ≥ 20 chars

A CC agent can pass all three with `HONCHO: done ok` (13 chars — wait, 20+ needed,
but `HONCHO: done ok this was fine` passes). Nothing is verified about quality.

### Hardened gate additions (in order of value)

**1. Require retro markers** (see Finding 1 above) — forces structured reflection.

**2. Require VERIFY reference** — the conclusion should acknowledge test results:
```python
has_verify_ref = bool(re.search(
    r"(?:tests?\s+pass|✓\s+test|all\s+\d+\s+pass|pytest|test_output)", text, re.I
))
results.append(GateResult(
    "verify reference",
    has_verify_ref,
    "test reference found" if has_verify_ref
    else "no test reference — mention test results in conclude.txt",
))
```

**3. Raise minimum length** — 20 chars is trivially small. 100 chars forces at
least one meaningful sentence.

**Effort:** Low. Gate additions only; no new logic.

---

## Finding 3 — `techne plan` Interview Is Still Missing (The Front Door)

**What OMO has:** Prometheus interviews until the plan is Decision-Complete.
`omh-deep-interview` runs Socratic coverage-tracked intake.

**What Techne has:** `grill.md` (stress-test an *existing* plan — single pass,
no structured output), `persona-brainstorm.md` (discover *what* to build).
Neither produces a gated, structured ticket.

**The gap:** The pipeline starts at `techne init <task-id>`. But what goes in
`task-id`? The agent guesses it. A bad task description → a bad RECALL → a bad
IMPLEMENT. The garbage enters at the very first step.

**Proposed `techne plan` skill:**
```
1. Read codebase context (.techne/context/, relevant source files)
2. Interview user — one question at a time, wait for each answer:
   a. OBJECTIVE: what does "done" look like concretely?
   b. CONSTRAINTS: what must NOT change?
   c. DONE_WHEN: exact acceptance criteria (testable, not "it works")
   d. FILE_SCOPE: which files are expected to change?
   e. RISK: what could go wrong?
3. Pass draft through grill.md (adversarial stress-test)
4. Produce structured ticket:
   OBJECTIVE: <one sentence>
   CONSTRAINTS: <list>
   DONE_WHEN: <testable criteria>
   FILE_SCOPE: <expected files — feeds Finding 4>
   task_id: <kebab-case derived from OBJECTIVE>
5. Run: techne init <task_id>
```

**Effort:** Medium. Skill authoring (prose + coverage tracker). No code changes.
Build via `writing-skill.md` process.

---

## Finding 4 — No File-Scope Gate (OMH `ralph-task` Pattern)

OMH's `omh-ralph-task` requires:
- Task envelope declares `FILE_SCOPE` upfront (at plan time)
- IMPLEMENT subagent has "file-scope rigidity" — can ONLY touch declared files
- Verify step checks diff against declared scope before submitting

Techne's IMPLEMENT gate checks:
- ✅ Diff has markers
- ✅ Hashline context matches
- ✅ Forbidden patterns absent
- ✅ Scope ≤ 10 files (configurable count limit)

What it doesn't check: **whether the touched files are in scope for this task.**
An IMPLEMENT that accidentally edits 3 files not declared in RECALL will pass all
gates. Scope creep is silent.

**Proposed addition:**
1. `techne plan` writes `FILE_SCOPE:` into `recall.txt` (see Finding 3)
2. RECALL gate extracts and saves `file_scope.json` to `.techne/loop/`
3. IMPLEMENT gate: if `file_scope.json` exists, verify diff only touches declared files.
   Files not in scope → GateResult failure with list of unexpected paths.

**Effort:** Medium. Requires `techne plan` (Finding 3) to populate scope. Gate
addition is ~20 lines once scope file exists.

---

## Finding 5 — `omh-triage` Pattern Not Represented

OMH's `omh-triage` runs two roles against an issue backlog:
- **Maintainer** — code-anchored, scores by impact and reproduction confidence  
- **Skeptic** — prunes duplicates, false positives, out-of-scope items
- Consensus required before an issue is promoted to "confirmed"

Techne has `task-gardener` and `kanban` skills for task management, but no
structured **multi-role triage** of an issue backlog. `grill.md` is single-agent
adversarial on a *plan*; it doesn't triage a *list*.

**Use case:** Given a list of bugs/issues/tasks, produce a Maintainer+Skeptic
consensus triage: confirmed, deferred, duplicate, rejected — with evidence anchors.

**Proposed `techne-triage` skill:**
```
Input:  list of issues (backlog.md or inline)
Role 1: Maintainer — read source, score reproducibility + impact
Role 2: Skeptic — challenge each item, mark duplicates/false positives
Output: triage.md with confirmed/deferred/duplicate/rejected + rationale
```

**Effort:** Low-Medium. Skill authoring only. No code changes.

---

## Finding 6 — RECALL Gate Doesn't Verify Context Was Read

RECALL gate currently checks:
- ✅ Artifact exists and non-empty
- ✅ WORKSHOP_CONTEXT: or HONCHO_CONTEXT: present
- ✅ ≥ 3 non-empty lines

What it doesn't check: whether `.techne/context/project_digest.md` was actually
consulted. An agent can write `WORKSHOP_CONTEXT: none` and pass.

**Simple hardening:** Require a reference to at least one file in `.techne/context/`:
```python
has_context_ref = bool(re.search(
    r"\.techne/context/|project_digest|file_roles|context_hash", text
))
results.append(GateResult(
    "context reference",
    has_context_ref,
    "context file referenced" if has_context_ref
    else "no .techne/context/ reference — read context pack before RECALL",
))
```

This forces the agent to actually open and reference the context pack, not just
acknowledge its existence.

**Effort:** Low. One gate addition.

---

## New Prioritized Backlog

| # | Item | Section | Effort | Why first |
|---|------|---------|--------|-----------|
| 1 | **Wire wisdom extraction at CONCLUDE** | F1 | Low | Code exists, just unwired. Closes the learning loop on every task. |
| 2 | **Harden CONCLUDE gate** (markers + verify ref + length) | F2 | Low | Prevents trivial bypass of the only unguarded phase. |
| 3 | **Harden RECALL gate** (context reference check) | F6 | Low | Ensures context pack is actually consulted before RECALL passes. |
| 4 | **`techne plan` interview skill** | F3 | Medium | The missing front door. Produces Decision-Complete tickets. Needed before F4. |
| 5 | **File-scope gate** | F4 | Medium | Prevents silent scope creep. Requires `techne plan` to populate FILE_SCOPE. |
| 6 | **`techne-triage` skill** | F5 | Low-Med | Multi-role issue triage; standalone; no deps. |

Items 1–3 are **a single afternoon** — all code changes, no new skills. They convert
CONCLUDE from Techne's weakest phase into its most instructive.

Items 4–6 are the next sprint. `techne plan` is the keystone that unlocks file-scope.

---

## What NOT to Build (Reconfirmed)

- **LSP/AST tools** — high effort, low priority; the Hashline gate already
  catches whitespace/context corruption without needing workspace-level tooling.
- **Multi-provider model routing** (`oh-my-models` pattern) — Techne is
  deliberately model-agnostic. Don't break that.
- **Team Mode / parallel mailbox** — fights the serial audit-chain invariant.
- **PostHog telemetry** — no-network stance is a selling point.
- **`omh-deep-research`** — multi-phase web search is out of scope for a
  disciplined *engineering* harness. Use a research skill from a different layer.

---

## One-Paragraph Status

> The v0 sprint built the hard spine and on-ramp. Techne now has a CLI, an
> enforcement hook, a doctor, a handoff command, a polished phase report, and a
> Hashline gate that catches stale reads before they corrupt VERIFY. The loop is
> live and enforced. What it doesn't yet do is *learn* — every completed task
> throws its lessons away because wisdom extraction is wired into the model-backed
> driver but not into `./next`. Fixing that is three afternoon-sized patches. After
> that, `techne plan` adds the front door and file-scope adds the scope invariant.
> At that point Techne becomes a system that not only enforces discipline but
> accumulates it.
