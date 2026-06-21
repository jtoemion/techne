# Techne Workshop — Full Build Guide

Date: 2026-06-20
Status: Audited against the actual repo (`techne.zip`), corrected across three
verification passes. Supersedes the inventory tables in
`techne-workshop-garage.md` and `2026-06-20-techne-project-workshop-redesign.md`.
Those two documents remain useful for vision and schema design — this
document is the operational layer: what's true right now, why each gap
matters, and exactly how to close it.

---

## How to use this document

This is not a vision document. The other two docs already did that job well
— Doc 1 (`techne-workshop-garage.md`) made the case for what a "workshop
garage" should feel like, and Doc 2 (the redesign doc) wrote a careful schema
for the project shell, the knowledge graph, and the refresh phase. Neither
needs to be rewritten.

What was missing was ground truth: which of those ideas are already code,
which are half-built, and which don't exist at all. That's what this
document supplies — file paths, function names, and exact line numbers where
useful, so that whoever picks up the next ticket isn't re-discovering the
same things by trial and error.

Read it in this order if you're about to start building:

1. **Section 1** — the one-line definition, so every decision below has a
   reference point to be checked against.
2. **Section 2** — how the audit was done and what got corrected along the
   way. Worth reading once, because two of the corrections reverse claims
   made earlier in this same project, and you should know why.
3. **Sections 3–5** — the three subsystems (pipeline, workshop shell,
   RL/GRPO), each broken into "what's real" and "what to build," with exact
   instructions.
4. **Section 6** — the actual build sequence, numbered, with dependencies
   called out so nothing gets built in the wrong order.
5. **Section 7** — guardrails: specific things that are easy to break while
   doing this work, based on what the audit found.
6. **Section 8** — a definition-of-done checklist per milestone, so "is this
   actually finished" has a concrete answer instead of a feeling.

---

## 1. What Techne is — the one-line definition

**Techne is a project-attached engineering workshop: a 10-phase pipeline
that disciplines how code work happens, plus a `.techne/` shell per project
that holds context, generated knowledge, and memory — currently missing the
loop that keeps that knowledge fresh after the work is done, and missing
most of the relational richness that would make recalled context actually
useful instead of just present.**

Two clauses do the work in that sentence:

- **"Missing the loop that keeps knowledge fresh"** — this is the
  auto-update question you asked at the start. The answer turned out to be:
  partially solved, with a fully-built script sitting disconnected from the
  pipeline, plus a second, narrower auto-update path that *is* wired in but
  only fires under a specific condition. Both are covered in Section 4.

- **"Missing most of the relational richness"** — this is the deeper reason
  RECALL can feel shallow even once workshop retrieval is switched on. The
  knowledge graph today knows which file belongs to which subsystem. It does
  not know which mistake happened in which file, which lesson came from
  which task, or which decision constrains which subsystem. That's a bigger
  and more important gap than the missing refresh wiring, and it's covered
  in Section 4 as well.

Everything below exists to make that one sentence stop being true — to get
to a state where knowledge actually does stay fresh, and recall actually
does surface what matters, not just what's nearby.

---

## 2. How this was audited, and what changed along the way

Three passes were made against the real codebase (extracted from
`techne.zip`), not against the prior planning docs' claims. This section
exists so the corrections are visible rather than silently folded in — if a
claim below contradicts something said earlier in this project, that's
intentional, and the reason is given.

### Pass 1 — broad inventory check

Checked the pipeline phase list, the gates, the workshop scripts directory,
the RL/reward files, and the Honcho integration, against Doc 1's tables.
Most of Doc 1 held up. Two things did not:

- **Test count was wrong in the safe direction.** Doc 1 said 54 tests
  passing. The repo actually has 34 test files and 271 test functions. Doc 1
  undercounted — there's more coverage than anyone had given Techne credit
  for.
- **`refresh_generated_docs.py` already exists**, fully matching the spec in
  Doc 2 §5.3, despite Doc 2 presenting it as something still to design.
  But — and this is the finding that mattered most — nothing in `harness/`
  called it. It was built and then never connected.

### Pass 2 — re-verification before a second review

A second look was done specifically to check whether Pass 1's "zero
wiring" claims held up against parts of the repo that hadn't been searched
yet — agent prompt files, test files, and non-`harness/*.py` locations.
This caught a real miss:

- **`tests/test_workshop_foundation.py` does call `refresh_generated_docs.py`**
  — but only as a standalone subprocess test, not as something the pipeline
  invokes during a real task. The "disconnected from the pipeline" finding
  held, but the document needed to say "no pipeline caller, but it does have
  test coverage" rather than implying it was untested.

### Pass 3 — correcting the knowledge graph and memory location claims

This is the most consequential round of corrections, and it happened while
drafting this very document — a reminder that even a careful audit benefits
from a second look before anyone builds against it.

- **The wikilink graph has more in it than Pass 1 reported.** Pass 1 checked
  `g["nodes"]` and `g["edges"]` in `.techne/memory/wikilinks.json`, found 4
  node kinds (`project`, `subsystem`, `context_doc`, `file`) and 3 edge types,
  and reported that as the whole graph. It isn't. The same JSON file also
  has a separate `entries` array — 24 entries at audit time, with kinds
  `MISTAKE` (21), `DECISION` (1), `LESSON` (1), `DISCIPLINE` (1) — built by
  an older part of `harness/wikilink.py` (`parse_mistakes()` /
  `parse_ledger()`) that predates the `.techne/` workshop shell entirely.
  **The correction that matters:** these 24 entries have zero edges
  connecting them to the structural graph. `harness/wikilink.py:273-277`
  overwrites `graph["nodes"]` and `graph["edges"]` wholesale from
  `context_index.json` on every rebuild, and never cross-references them
  against `graph["entries"]`. So it's not "4 node kinds, nothing else" — it's
  "two disconnected graphs living in the same file, one structural
  (4 kinds), one narrative (4 kinds), with no edges between them."

- **`memory/ledger.md` and `memory/mistakes.md` do exist.** Pass 1 checked
  `.techne/memory/` (the path Doc 2 specifies) and correctly found nothing
  there, then incorrectly reported that as "doesn't exist anywhere." They
  exist at repo-root `memory/ledger.md` and `memory/mistakes.md` — an older
  location the new `.techne/` shell hasn't absorbed. This matters for the
  build plan: the data already exists, the work is consolidating where it
  lives, not creating it from nothing.

- **The auto-update story is less binary than "wired in" vs. "not wired
  in."** `harness/orchestrator_loop.py`'s `_log_retro_learn_trigger()`
  (called from the DONE handler) does rebuild `memory/wikilinks.json` and
  `memory/wikilinks.md` by calling `wikilink.build_graph()` — but only when
  `any(n >= 2 for n in recurrence.values())`, i.e. only when a skill has at
  least two recurring active mistakes. The method's own docstring claims the
  rebuild happens "every DONE," which is incorrect — its caller gates it.
  So there are, in effect, **two independent auto-update mechanisms** in the
  codebase right now: a conditional one (mistake-recurrence-triggered,
  rebuilds the legacy entries+structural graph, lives at repo-root
  `memory/`) and a dormant one (`refresh_generated_docs.py`, rebuilds
  `context_index.json` + `subsystem_map.json` + the `.techne/memory/`
  wikilinks, never called automatically). Neither knows the other exists.

These corrections don't overturn the overall direction — they sharpen it.
The gap is real, but it's a *consolidation and connection* problem more than
a *build from zero* problem. That distinction changes how each piece below
should be approached.

---

## 3. Pipeline core — confirmed solid, minimal action needed

This part of Techne doesn't need a build plan. It needs to be left alone
except for two specific, narrow fixes. Listing it here mainly so the rest of
this document has a stable foundation to reference.

### 3.1 What's confirmed real

| Component | File | Confirmed |
|---|---|---|
| 10-phase list | `harness/pipeline_enforcer.py:43-54` | `RECALL, IMPLEMENT, CONTEXT_GUARD, CRITIQUE, REVIEW, VERIFY, EVAL, RETRO, CONCLUDE, DONE` — exact |
| Transition table | `harness/pipeline_enforcer.py:58-74` | Forward-only, with `BLOCKED`/`DEBUG`/`FAILED` side-states |
| `can_enter()` gate check | `harness/pipeline_enforcer.py:129` | Real, used before every phase |
| `mark_complete()` | `harness/pipeline_enforcer.py:199` | Real, records `agent`, `summary`, `verdict`, `changed_files`, `findings`, etc. |
| Phase dispatch | `harness/orchestrator_loop.py` | `_submit_retro()`, `_submit_conclude()`, etc. — one method per phase, confirmed by reading the actual handlers |
| Test coverage | `tests/*.py` | 34 files, 271 test functions — more than previously documented |

**Why this matters for the rest of the plan:** every new phase or gate added
below (`REFRESH_CONTEXT`, GRPO scoring, graph enrichment) has to be added
*through* this state machine, not around it. `PHASES`, `TRANSITIONS`, and
`mark_complete()` are the only legitimate entry points. Anything that writes
to `.techne/` or `memory/` from outside this flow — a cron job, a separate
script run by a human, a side-channel call — defeats the entire point of
having an enforced pipeline. If REFRESH_CONTEXT becomes a real phase, it has
to be a row in `TRANSITIONS`, gated by `can_enter()`, recorded by
`mark_complete()`. No shortcuts, even though the underlying script
(`refresh_generated_docs.py`) doesn't care who calls it.

### 3.2 Two confirmed flaws, both narrow, both real

**Flaw 1 — HITL re-entry guard.** `pipeline_enforcer.py:148`:

```python
if task.status == "PENDING" and current != "RECALL":
    current = None
```

This is exactly the bandaid Doc 1 flagged. The comment above it in the
source explains the problem honestly: an unblock that resets a task to
`PENDING` used to get stuck at whatever phase it last completed (e.g.
`CONTEXT_GUARD`), unable to re-enter `RECALL`, because the enforcer thought
`RECALL` was already done. The fix resets `current` to `None` — but only
checks `current != "RECALL"` as the trigger, which means the fix itself is a
special case bolted onto a special case. It works for the scenario it was
written for. It is not a general solution, and the next edge case in this
area should be expected.

**Why it matters here:** any new phase logic (REFRESH_CONTEXT,
GRPO-driven retries) that touches task status transitions needs to be aware
this guard exists and is fragile, or a new edge case will be introduced on
top of an old one.

**Flaw 2 — CONCLUDE git-state gate is directory-scoped, not task-scoped.**
`orchestrator_loop.py:824-858`, specifically `_get_uncommitted_context_files()`:

```python
result = subprocess.run(
    ["git", "status", "--porcelain", "--", "."],
    capture_output=True, text=True, cwd=str(repo_root),
)
uncommitted = [l.split(None, 1)[1] for l in result.stdout.strip().split("\n") if l.strip()]
return [f for f in uncommitted if ".techne/context" in f]
```

This is narrower than Doc 1's flaw description implied on first read. It
*does* scope to `.techne/context` already — it is not blocking on every
dirty file in the repo. But it still blocks on **any** uncommitted file
under `.techne/context`, not just the ones relevant to the current task. If
you're concluding a task that touched `auth.CONTEXT.md`, and someone else's
unrelated, half-finished edit to `billing.CONTEXT.md` is sitting uncommitted
in the same checkout, CONCLUDE blocks on a file your task never touched.

**The fix, concretely:** `_get_uncommitted_context_files()` needs an
optional `touched_files: list[str]` parameter. When provided (which it can
be — `CONTEXT_GUARD`'s punch list already records which files were
touched), filter `uncommitted` down to files whose subsystem overlaps with
the touched files' subsystems, using the same `detect_subsystems_for_files()`
helper that `refresh_generated_docs.py` already calls
(`harness/workshop.py:395`). This reuses an existing function rather than
writing new subsystem-matching logic.

---

## 4. Workshop shell — the core of the build

This is where almost all the real work lives. The pipeline is solid; the
workshop shell is half-built, and the half that's missing is exactly the
half that makes the difference between "Techne has a folder of context
docs" and "Techne actually knows this codebase."

### 4.1 What exists today — file by file

```text
.techne/
  config.yaml                          ✅ real, has policy split (generated/proposed/manual)
  context/
    root.CONTEXT.md                    ✅ real
    harness.CONTEXT.md                 ✅ real
    memory.CONTEXT.md                  ✅ real
    scripts.CONTEXT.md                 ✅ real
    file_roles.md                      ✅ real
    risk_boundaries.md                 ✅ real
    project_digest.md                  ✅ real
    context_hash.txt                   ✅ real
    context_packs/                     ✅ exists (subdirectory, not separately audited)
                                        ⚠️ all 7 docs are meta/repo-level, none are
                                           per-subsystem docs in the auth.CONTEXT.md
                                           sense Doc 2 designed
  generated/
    context_index.json                 ✅ real, 27.9 KB, built by context_index.py
    change_log.json                    ✅ real, written by refresh_generated_docs.py
    stale_docs.json                    ✅ real, written by refresh_generated_docs.py
    subsystem_map.json                 ✅ real, written by refresh_generated_docs.py
                                        ❌ missing: file_index.json, symbol_index.json,
                                           route_map.json, api_map.json, schema_map.json,
                                           test_map.json, dependency_graph.json,
                                           ownership_map.json (all named in Doc 2 §1 spec,
                                           none implemented — no adapters exist yet)
  memory/
    wikilinks.json                     ✅ real, 115 KB — contains BOTH the structural
                                           graph (nodes/edges) AND the legacy entries
                                           array (mistakes/decisions/lessons/disciplines),
                                           disconnected from each other (see Section 2)
    wikilinks.md                       ✅ real, human-readable mirror
                                        ❌ missing: ledger.md, mistakes.md (these exist,
                                           but at repo-root memory/, not here — see 4.4),
                                           task_history.jsonl, context_search_cache.json
  proposals/                           ✅ directory exists
                                        ❌ empty — no proposal-writing logic has run yet;
                                           propose_context_updates.py (Doc 2 §1) doesn't exist
  tasks/                               ✅ directory exists
                                        ❌ empty at audit time — no task has gone through
                                           a flow that writes recall_pack.md or
                                           refresh_context.json yet, though
                                           refresh_generated_docs.py is built to write
                                           the latter when given --task
  scripts/
    context_index.py                  ✅ real, 2.5 KB
    context_search.py                 ✅ real, 7.1 KB, wired into RECALL
                                          (orchestrator_loop.py:1042,1078,1094)
    refresh_generated_docs.py         ✅ real, 5.8 KB, matches Doc 2 §5.3 spec closely
                                          — NOT called by anything in harness/
                                          (only by tests/test_workshop_foundation.py,
                                          as a standalone subprocess test)
                                       ❌ missing: propose_context_updates.py,
                                          stale_docs_check.py, touched_subsystems.py
                                          (all named in Doc 2 §1, none exist)
```

**Read this table as the actual state of "is it possible, using a
script?"** — yes, three of the six scripts Doc 2 imagined are written and
working. The other three (proposal-writing, standalone stale-check,
standalone subsystem-detection) don't exist as separate scripts, though
some of their logic (`stale_context_reasons()`, `detect_subsystems_for_files()`)
already lives inside `harness/workshop.py` and is called by
`refresh_generated_docs.py` — so the *capability* exists, just not as its own
CLI entrypoint.

### 4.2 Wiring `REFRESH_CONTEXT` as a real phase — exact steps

This is the highest-leverage piece of work in the whole plan, because the
hard part (writing the script, designing its I/O contract) is already done.
What's missing is glue code, and glue code is cheap relative to design work.

**Why this needs to be a real pipeline phase and not just "call the script
somewhere":** Section 3.1 already made this point, but it's worth repeating
here because it's tempting to take a shortcut. If `refresh_generated_docs.py`
just gets called as a side-effect inside `_submit_conclude()` without going
through `mark_complete()` / `can_enter()`, then:
- there's no record in `task_db` that refresh happened, which breaks
  auditability (you can't ask "did this task's context get refreshed?"
  without parsing logs)
- there's no gate, so a broken refresh run silently does nothing and
  CONCLUDE still passes
- if refresh later needs its own retry logic (e.g. git state is dirty, or
  the script throws), there's no phase to retry *into*

**Step 1 — add the phase to the state machine.**
In `harness/pipeline_enforcer.py`:

```python
PHASES = [
    "RECALL",
    "IMPLEMENT",
    "CONTEXT_GUARD",
    "CRITIQUE",
    "REVIEW",
    "VERIFY",
    "EVAL",
    "RETRO",
    "CONCLUDE",
    "REFRESH_CONTEXT",   # new
    "DONE",
]

TRANSITIONS = {
    # ... existing entries unchanged ...
    "CONCLUDE":        ["REFRESH_CONTEXT", "FAILED"],   # was: ["DONE", "FAILED"]
    "REFRESH_CONTEXT": ["DONE", "FAILED"],               # new
}
```

Also add a `PHASE_DESCRIPTIONS` entry:

```python
"REFRESH_CONTEXT": "Rebuild generated workshop artifacts and flag stale authored docs for the touched subsystems.",
```

**Step 2 — add a handler in `orchestrator_loop.py`.** Model it on
`_submit_conclude()`. The handler doesn't run an LLM call — this phase is
pure script execution, same as Doc 2 §4 specifies ("deterministic, not
theatrical"). Something close to:

```python
def _submit_refresh_context(self, task_id: str) -> LoopOutcome:
    """REFRESH_CONTEXT phase — rebuild generated docs, flag stale authored docs.

    Pure script execution, no model call. Calls the existing
    .techne/scripts/refresh_generated_docs.py with the task's touched files.
    """
    task = self.db.get_task(task_id)
    touched = self._get_touched_files_for_task(task_id)  # from CONTEXT_GUARD's punch list

    result = subprocess.run(
        ["python3", str(self._workshop_script_path("refresh_generated_docs.py")),
         "--task", task_id, "--files", *touched, "--json"],
        capture_output=True, text=True, cwd=str(self._repo_root()),
    )
    if result.returncode != 0:
        return LoopOutcome(
            action=LoopAction.RETRY, phase="REFRESH_CONTEXT", task_id=task_id,
            message=f"REFRESH_CONTEXT script failed: {result.stderr.strip()}",
        )

    payload = json.loads(result.stdout)
    self.enforcer.mark_complete(
        task_id, "REFRESH_CONTEXT", agent="refresh_context",
        summary=f"Refreshed: {len(payload['generated_updated'])} files, "
                f"{len(payload['stale_docs'])} stale docs flagged",
        findings=json.dumps(payload),
    )
    return LoopOutcome(
        action=LoopAction.RUN_PHASE, phase="DONE", task_id=task_id,
        message="Context refreshed — advancing to done",
    )
```

The exact field names (`generated_updated`, `stale_docs`) come straight from
`refresh_generated_docs.py`'s own output contract (lines 134–142 of that
file) — no guessing needed, the script already returns exactly this shape
when called with `--json`.

**Step 3 — change the CONCLUDE transition.** `_submit_conclude()` currently
ends with:

```python
self.enforcer.mark_complete(task_id, "DONE", agent="orchestrator")
self._record_reward(task_id)
```

This needs to become:

```python
return LoopOutcome(
    action=LoopAction.RUN_PHASE, phase="REFRESH_CONTEXT", task_id=task_id,
    message="Conclusion recorded — advancing to context refresh",
)
```

— and the `mark_complete(task_id, "DONE", ...)` plus `_record_reward()` call
moves into the new `_submit_refresh_context()` handler instead, after the
script succeeds. This is a meaningful sequencing decision: it means the RL
reward gets recorded *after* context refresh succeeds, not before. That's
intentional — a task whose context refresh fails shouldn't silently count as
a clean success for reward purposes. If this consequence isn't wanted,
recording reward can stay in `_submit_conclude()` and `REFRESH_CONTEXT`
becomes purely advisory (failures don't block DONE). That's a real design
choice, not a default to wave through — see the open decision in Section 6.

**Step 4 — gate.** Per Doc 2 §4.4, the phase should only pass if:
- generated docs for touched subsystems were actually refreshed (check
  `payload["generated_updated"]` is non-empty when `touched` is non-empty)
- the script didn't error
- proof lines exist in the `findings` field

This can largely be the `result.returncode != 0` check already shown above
in Step 2 — the script's own failure behavior (Doc 2 §5.3: "never partially
write malformed JSON... emit actionable error lines") already does most of
the gate's job. The new gate code mainly needs to translate a script failure
into a `RETRY` outcome, which Step 2's code already does.

**Step 5 — fast-mode behavior.** Per Doc 2 §4.5, fast-mode (review-only)
tasks should still get a cheap refresh, not skip it entirely. Mirror the
existing fast-mode check used elsewhere in `orchestrator_loop.py` (e.g. the
`if task and task.phase_mode == "fast":` block in `_submit_retro()`) — for
fast mode, call the script with `--files` only (skip subsystem-threshold
proposal logic, which doesn't exist yet anyway per Section 4.1's missing
scripts) rather than skipping the phase outright.

**What this step does *not* require:** no new script. No new I/O contract
design. No new JSON schema. The script's contract is already correct and
already tested (`tests/test_workshop_foundation.py:102`). This is
integration work, sized in hours, not days, once someone is working directly
in the code with test coverage as a guide.

### 4.3 Enriching the knowledge graph — the bigger, more important gap

This is the part of the build that actually makes RECALL smart. Wiring
REFRESH_CONTEXT (4.2) keeps the *existing* graph fresh — but the existing
graph is thin. Right now it can answer "which subsystem is this file in?"
It cannot answer "what mistakes have happened in this subsystem before?" or
"what lesson came out of the last task that touched this file?" — and those
are the questions that make a RECALL pack actually useful instead of a
glorified file listing.

**Current state, precisely (confirmed in Section 2's Pass 3):**

- Structural graph: 4 node kinds (`project`, `subsystem`, `context_doc`,
  `file`), 3 edge types (`project_contains`, `subsystem_contains`,
  `context_describes`). Built by `_attach_workshop_graph()` in
  `harness/wikilink.py:170-277`, sourced from `context_index.json`.
- Narrative entries: 4 kinds (`MISTAKE`, `DECISION`, `LESSON`, `DISCIPLINE`),
  24 entries at audit time, parsed from `memory/mistakes.md` and
  `memory/ledger.md` by `parse_mistakes()` / `parse_ledger()`
  (`harness/wikilink.py:53-110`). Zero edges connect any of these 24 entries
  to anything in the structural graph.
- Doc 2 §2 specifies 18 node types and ~25 edge types. 8 of the 18 node
  types exist in some form (`project`, `subsystem`, `context_doc`, `file`,
  plus the 4 narrative kinds, which map roughly onto Doc 2's `lesson`,
  `mistake`, `decision`, `discipline` node types even though they're stored
  separately). The other 10 (`symbol`, `test`, `route`, `schema`, `task`,
  `artifact`, `skill`, `env_var`, `service`) don't exist as nodes anywhere.

**The single highest-value piece of this section: connect what already
exists before adding what doesn't.** The 24 narrative entries already carry
a `phase`, `gate`, and `skill` field (see the sample entry in Section 2).
None of those map directly to a subsystem today, but `gate` values like
`"intent"` correspond to gates that ran during specific phases on specific
files — which means the connecting information exists in `task_db`'s
`TaskEvent` history (mentioned in `task_db.py:76-82`, action types include
`review`, `verify`, `block`, `fix`), just not joined to the wikilink graph.

**Step 1 — add edges from existing entries to existing subsystem nodes.**
In `harness/wikilink.py`, after `_attach_workshop_graph()` builds the
structural nodes (so subsystem node IDs are known), add a pass that:

1. For each entry in `graph["entries"]`, look at its `source` field (which
   today is usually `"AUTO-LOGGED"` — a placeholder, not a file path).
2. Cross-reference against `context_index.json["files"]` using the task ID
   or touched-file data already available in `task_db` for that entry's
   timeframe (entries have a `date` field).
3. Where a match is found, append an edge:
   `{"from": "mistake:<slug>", "type": "mistake_applies_to", "to": "subsystem:<name>", ...}`
   using Doc 2 §2.2's existing edge vocabulary — don't invent new edge type
   names, the spec already has the right ones (`mistake_applies_to`,
   `lesson_applies_to`, `decision_constrains`).

This alone — without adding a single new node type — turns "24 mistakes
sitting in a flat list" into "24 mistakes RECALL can actually retrieve when
working in a given subsystem." That's the highest ratio of value to effort
in this entire section, because it reuses data that's already being
collected (mistakes.md is already being written to by
`harness/mistakes.py`) and just adds the missing edge.

**Step 2 — add `task` nodes.** Every task in `task_db` already has an `id`,
`status`, `tags`, and `created_at`/`updated_at`. Doc 2 §2.1 wants a `task`
node type with edges `task_touched -> file`, `task_changed -> subsystem`,
`task_triggered -> lesson`, `task_triggered -> mistake`. This is mechanically
similar to Step 1 — pull from `task_db`, not from new tracking — but it's
the piece that finally lets RECALL say "the last three tasks that touched
this file all hit the same mistake," which is the single most useful thing
a recall pack can say to a model about to start IMPLEMENT.

**Step 3 — defer `symbol`, `route`, `schema`, `test` node types.** These
require language/framework adapters (Doc 2 §1's "optional repo-language
adapters," Doc 2 §7 Phase 5 "adapters"). None of that exists yet, and it's
real, separate work — parsing TypeScript/Svelte/Next/Convex source to extract
symbols and routes is a different kind of effort than graph wiring. Doc 2
correctly sequences this as its own Phase 5, last. Keep it last here too.
Don't let "the graph needs more node types" turn into "let's build a
TypeScript AST parser" before the cheaper, file/mistake/task-level wiring in
Steps 1–2 is done.

**Step 4 — verify with the existing test.**
`tests/test_workshop_foundation.py:test_wikilink_graph_attaches_workshop_nodes`
already tests the structural-graph side of `_attach_workshop_graph()`. After
Steps 1–2, extend this same test (don't write a parallel one) to assert
that a mistake/task fixture produces the expected new edges. The existing
test's fixture shape (a `context_index` dict with `subsystems`,
`context_docs`, `files`) is the right pattern to extend — add `entries` and
`tasks` fixture keys alongside it rather than building a separate
integration test from scratch.

### 4.4 The two-memory-locations problem

This needs its own callout because it's the kind of thing that's easy to
paper over and hard to clean up later.

There are currently **two separate memory directories**:

- `memory/` at repo root — older, holds `ledger.md`, `mistakes.md`,
  `reward.md`, `eval_history.json`, `run_log.json`, `tasks.db`,
  `wikilinks.json`/`.md`, `harness-state.json`, `SESSION.md`. This is where
  the pipeline's existing reward/mistake/ledger machinery
  (`harness/reward.py`, `harness/mistakes.py`, `harness/wikilink.py`'s
  default paths) actually reads and writes today.
- `.techne/memory/` — newer, holds only `wikilinks.json`/`.md` (the
  workshop-graph copy). This is the location Doc 2 specifies for everything
  (`ledger.md`, `mistakes.md`, `task_history.jsonl`, `context_search_cache.json`).

Right now, `harness/wikilink.py` writes to **both** locations on every
rebuild (`_write_wikilinks()` in `refresh_generated_docs.py` writes the root
copy first, then the `.techne/memory/` copy — lines 32-49 of that file) —
but only the wikilinks files get this dual treatment. `ledger.md` and
`mistakes.md` are still root-only.

**Why this matters:** if REFRESH_CONTEXT (4.2) and graph enrichment (4.3)
both get built without resolving this, you end up with project knowledge
split across two directories with no single source of truth, and future
work (the proposal system in Doc 2 §1, or any tooling that assumes
`.techne/` is the complete shell) will silently miss half the data.

**The fix is a decision, not code:** pick one location as canonical (this
guide recommends `.techne/memory/`, since that's the direction both Doc 2
and the `.techne/` shell convention point, and `config.yaml` already
references `.techne/memory/` for `memory_dir`) and either (a) move
`reward.py`/`mistakes.py`/`wikilink.py`'s default paths to point there, with
a migration script that moves the existing root-`memory/` files over once,
or (b) keep root `memory/` as the source of truth and make `.techne/memory/`
a generated mirror, the same way `.techne/generated/` already mirrors
`harness/`-computed state into the workshop shell. Either is defensible.
What's not defensible is leaving both live and diverging, which is the
current state.

### 4.5 Honcho integration — resolved design (Hermes-hosted, proof-verified)

**Resolved on 2026-06-20.** Honcho runs on the user's VPS alongside Hermes,
the host that drives Techne. The chosen approach is: **Hermes keeps making
the actual Honcho calls — Techne never gets an API key or a client — but
the proof that a call happened becomes a real, checkable artifact instead of
a substring match on model-generated text.**

**Why this is the right fit, not just the easy one.** `SKILL.md` line 241
already documents the intended division of labor: *"CONCLUDE: Host runs
`honcho_conclude`, returns conclusion IDs as proof."* Doc 1 listed
host-driven architecture ("no model API keys required for the pipeline
itself... the host agent supplies every model turn") as a strength worth
preserving. Giving Techne its own Honcho client would quietly undo that
design decision. The fix below closes the verification gap without
reopening that question.

**Confirmed, still true:** `orchestrator_loop.py:297` —

```python
has_honcho = "honcho_context:" in recall_lower or "honcho context:" in recall_lower
```

— checks for a string the model was told to include, not evidence anything
was queried. No `HonchoClient`, no import, no network call anywhere in
`harness/`. This is what's being fixed.

**The pattern to reuse, not reinvent.** `harness/checkpoint.py` already
solves this exact class of problem for VERIFY:

```python
def mark_verified(sha_hash: str) -> None:
    """Mark pipeline as verified — only the SHA gate should call this."""
    ...

def check_verification() -> bool:
    """Returns True if verification has been logged for current session."""
    ...
```

VERIFY isn't trusted because a model says "tests pass" — it's trusted
because `mark_verified()` records a real SHA and `check_verification()`
reads it back. Honcho needs the identical shape: a place Hermes writes a
real conclusion ID after a real Honcho call, and a place Techne's gate
reads it back instead of grepping prose.

There's also an existing cross-process handoff convention already built for
exactly this kind of host→Techne signal: `harness/store.py`'s
`TECHNE_STATE_DIR` env var, set per-worker by a Hermes dispatcher ("Mirrors
how Hermes injects `HERMES_KANBAN_DB` per card" — `store.py:22-24`). Honcho
proof should travel the same way: a file Hermes writes, in the directory
Techne already knows how to find.

**Concrete design:**

1. **New function in `harness/checkpoint.py`**, parallel to `mark_verified()`:

   ```python
   def mark_honcho_concluded(conclusion_id: str, peer: str = "user") -> None:
       """Mark that Hermes completed a real Honcho call for this phase.

       Called by Hermes (the host) immediately after a genuine honcho_search
       or honcho_conclude call returns — not by the model, not from inside
       a phase prompt. Mirrors mark_verified()'s pattern: the gate trusts
       this file, not prose.
       """
       state = read_state()
       if not state:
           state = init_state()
       state["honcho_conclusion_id"] = conclusion_id
       state["honcho_peer"] = peer
       state["honcho_logged_at"] = datetime.now(timezone.utc).isoformat()
       write_state(state)

   def check_honcho_logged() -> str | None:
       """Returns the conclusion ID if Hermes logged a real Honcho call
       this session, else None."""
       state = read_state()
       return state.get("honcho_conclusion_id")
   ```

   This goes in `harness-state.json` (or `TECHNE_STATE_DIR`-scoped
   equivalent for isolated workers), the same file `mark_verified()` already
   writes to — not a new file, not a new convention.

2. **How Hermes writes it.** After Hermes runs the real `honcho_search` or
   `honcho_conclude` call against the VPS-hosted Honcho instance, Hermes
   calls `mark_honcho_concluded(conclusion_id, peer)` — either by shelling
   out to a small Techne CLI wrapper (`python3 harness/checkpoint.py
   --mark-honcho <id>`) if Hermes and Techne are separate processes, or by
   importing `checkpoint.py` directly if Hermes already runs inside the same
   Python process space. Either is fine — this is a one-line call either
   way, the existing module does the actual work.

3. **What the gate checks, replacing the substring match.** In
   `orchestrator_loop.py`, the `has_honcho` check at line 297 (RECALL) and
   the equivalent check around line 774-790 (CONCLUDE) become:

   ```python
   from checkpoint import check_honcho_logged
   conclusion_id = check_honcho_logged()
   has_honcho = conclusion_id is not None
   ```

   The phase output text can still *display* the conclusion ID for human
   readability (Hermes including `HONCHO: <conclusion_id>` in its proof
   text is good practice, matching the existing `CONCLUDE PROOF REQUIRED`
   format at `orchestrator_loop.py:1054`) — but the gate no longer trusts
   that text. It trusts `checkpoint.py`'s state file, written by a real call.

4. **Reset on new run.** `increment_pipeline_run()` already resets
   `verification_logged` to `False` on each new pipeline run
   (`checkpoint.py`, current code). The same reset needs to clear
   `honcho_conclusion_id`, or a stale conclusion ID from task N could pass
   the gate for task N+1 without Hermes ever calling Honcho again.

**What this does *not* require:** no Honcho SDK in Techne's dependencies, no
API key handling in `harness/`, no new file format, no new IPC mechanism —
the env var and state-file conventions already exist and already do this
job for VERIFY. This is the same shape as Section 4.2's REFRESH_CONTEXT
finding: most of what's needed already exists in the codebase under a
different name, doing the same job for a different phase.

**One thing this audit cannot confirm from the code alone:** whether Hermes
currently calls `mark_honcho_concluded()`-equivalent logic anywhere already,
since Hermes' own source isn't part of this repo. If Hermes already has a
post-Honcho-call hook of some kind, step 2 is wiring into an existing hook
rather than adding a new one — worth checking on the Hermes side before
assuming this is greenfield there too.

---

## 5. RL / GRPO — building on the substrate that already exists

You asked for this track to be equal priority with the workshop knowledge
loop, and it can run genuinely in parallel — it touches `reward.py`,
`reward_log.py`, `evaluator.py`, `prompt_evolution.py`, `gate_evolution.py`,
none of which Section 4's work modifies.

### 5.1 What's confirmed real here

| Component | File | What it actually does |
|---|---|---|
| `evaluator.py` | `harness/evaluator.py`, 12.3 KB | Deterministic 100-point score from real signals — no model call |
| `reward_log.py` | `harness/reward_log.py`, 18.9 KB | `_composite_score()` (line 366) — **one run, one number.** `Reward` and `RewardLog` classes (lines 66, 92) |
| `reward.py` | `harness/reward.py`, 7.4 KB | Per-skill CLEAN/SOLVED win counters, append-only log parsing |
| `prompt_evolution.py` | `harness/prompt_evolution.py`, 19 KB | Propose → validate → ratify *logging* for prompt variants — **⚠️ `ratify()` does not write to any skill file; see 5.4** |
| `gate_evolution.py` | `harness/gate_evolution.py`, 22.6 KB | Same propose/validate pattern, but its `ratify`-equivalent step writes a real file — to `harness/plugins/`, a new gate plugin, not to `skills/` |
| `apply_retro.py` | `harness/apply_retro.py` | **The actual skill-write mechanism.** `apply_add()`/`apply_delete()`/`apply_resolve()` write directly into `skills/*.md`. Default path is human-confirmed (`input("Apply? [y/n/q]:")`). Has a dormant `auto_apply_pending()` that bypasses confirmation entirely and is not currently called by `conductor.py` — see 5.4 |
| `mistakes.py` | `harness/mistakes.py`, 5.4 KB | Structured mistake logging, feeds `count_by_skill()` |
| Task classification substrate | `harness/task_db.py:52-67` | `Task.tags: list[str]` and `Task.discipline: str` (values: `tdd \| implement \| review \| debug \| retro`) — already tracked on every task |

Confirmed, with a fresh re-check: zero matches for the string `"GRPO"`
anywhere in `harness/`. No group comparison, no advantage computation, no
policy gradient. This part of the plan really is greenfield — but it
doesn't start from zero, because the scalar reward signal GRPO needs to
compare *already exists and is already being recorded per task*.

### 5.2 Step 1 — task-type classifier, using what's already tracked

Don't design a new taxonomy (the "auth/ui/data/api/infra" grouping Doc 1
imagined) before checking what's already on the `Task` object. `discipline`
(5 values) is coarser than a full task-type taxonomy but already
distinguishes implement-work from review-work from debug-work — which
matters for fair comparison, since an `implement` task and a `review` task
shouldn't be scored against the same baseline. `tags` is freeform and
already populated per task.

Concretely: add a `classify_task_group(task: Task) -> str` function — start
by returning `task.discipline`, which costs nothing and is already correct
information. Layer `tags`-based refinement in only if `discipline` alone
proves too coarse once there's enough run history to tell (e.g. if
`implement` tasks on auth code score very differently from `implement` tasks
on UI code, in a way that's hiding signal). Don't build the finer-grained
classifier speculatively before there's data showing it's needed.

### 5.3 Step 2 — group-based scoring, as a function over what already exists

GRPO's advantage formula is `advantage = score - mean(scores_in_group)`.
The `score` half already exists — it's `_composite_score()`'s output,
already being written to `reward_log.py`'s `RewardLog` on every task. The
work here is:

1. Query `RewardLog` for all completed runs in the same `classify_task_group`
   bucket.
2. Compute `mean(scores)` over that bucket.
3. Compute `advantage = this_run_score - mean`.
4. Store the advantage alongside the existing reward record — extend the
   `Reward` dataclass (`reward_log.py:66`) with an `advantage: float` field
   rather than building a parallel storage structure.

This is genuinely new logic, but it's a query and an arithmetic operation
over data that's already being collected. It does not require touching how
`evaluator.py` computes the underlying 100-point score, and it does not
require a new database — `RewardLog` already exists and already has the
data needed to compute group means.

### 5.4 Step 3 — policy update — **stop here before building this, real gap found**

This section originally recommended reusing `prompt_evolution.py`'s
propose → validate → ratify firewall as GRPO's policy-update path. That
recommendation was wrong, found while checking what "ratify" actually does
on disk. **If the goal is GRPO that actually updates the skill base, this
is the most important finding in the whole document, and it needs to be
resolved before any GRPO scoring work (5.2, 5.3) is worth finishing.**

**What was found, checked directly against the code:**

1. **`prompt_evolution.py`'s `ratify()` never writes to a skill file.** Line
   335: `self.variants.setdefault(proposal.agent, {})[proposal.variant_name]
   = proposal.config`. `self.variants` is a Python dict on the
   `PromptEvolution` instance, initialized fresh from `DEFAULT_VARIANTS` on
   every construction (`self.variants = copy.deepcopy(DEFAULT_VARIANTS)`,
   line 158) and never read back from any persisted state. **A ratified
   prompt variant does not survive process restart, and it never touches
   anything in `skills/`.** The only thing that persists to disk is the
   *proposal record itself* (`proposals.json`, via `_save_proposal()`) — a
   log saying "this was approved," not the approved change taking effect.

2. **`gate_evolution.py` does write a real file** — but to
   `harness/plugins/`, as a new gate plugin (`filepath =
   PLUGINS_DIR / filename`, line 211). That's a different artifact from a
   skill edit and a different mechanism entirely.

3. **There is a real, working skill-write mechanism — `apply_retro.py` —
   and it is completely separate from `prompt_evolution.py` and
   `gate_evolution.py`.** Its `apply_add()` / `apply_delete()` /
   `apply_resolve()` functions write directly into resolved paths under
   `skills/` (line 150, 184: `target_path.write_text(new_content, ...)`).
   This is fed by RETRO phase output, parsed from a different file
   (`retro_proposals.md`, via `parse_proposals()`), not by anything GRPO
   would compute.

4. **`apply_retro.py`'s default path is human-gated** — `review_and_apply()`
   calls Python's `input("Apply? [y/n/q]: ")` per proposal, and
   `conductor.py` only calls `has_pending_proposals()` to print a reminder,
   never `review_and_apply()` or `auto_apply_pending()` itself. So today,
   skill edits only happen when a human runs `apply_retro.py` by hand and
   types `y`.

5. **But `auto_apply_pending()` already exists, and its docstring claims an
   automated caller that doesn't currently exist:** *"Apply all pending
   proposals without confirmation... Used by the conductor's retro phase."*
   `conductor.py` does not actually call it — confirmed by grep, it only
   appears in `apply_retro.py` itself. **This is a dormant, no-confirmation
   bypass of the only human gate this mechanism has**, one function call
   away from being wired in by anyone (including a future GRPO
   implementation) who reads the docstring at face value and assumes it's
   already the conductor's behavior.

**What this means for "I need GRPO to actually update the skill base
correctly":**

GRPO's advantage score (5.3) currently has **no path to a real file at
all**. To make GRPO actually update the skill base, the work is not "wire
GRPO into the existing firewall" (there's no firewall on the write side —
only on the *proposal-logging* side). The real work is:

- **Decide which write path GRPO feeds.** Either (a) extend
  `retro_proposals.md`'s format so a GRPO-generated proposal can be parsed
  by `apply_retro.py`'s existing `parse_proposals()` and applied through its
  existing `apply_add()`/`apply_delete()`/`apply_resolve()` functions — reusing
  real, tested, working write code — or (b) give `prompt_evolution.py`'s
  `ratify()` a real write step for the first time, since right now it has
  none to reuse.
- **Route GRPO's ratification through the same human gate
  `apply_retro.py` already has** (`input("Apply? [y/n/q]: ")` or an
  equivalent explicit confirmation step) — **not** through
  `auto_apply_pending()`. That function should arguably be deleted or
  clearly marked dead/dangerous rather than left as a one-line integration
  away from silently auto-shipping policy changes — which is precisely the
  top risk Doc 1's risk table flagged ("GRPO auto-ships bad policy... Human-
  ratify firewall: propose → validate → ratify"). The firewall Doc 1
  described as already existing does not, in fact, reach the actual skill
  files. Building GRPO against the assumption that it does would recreate
  exactly the failure mode the firewall was supposed to prevent.
- **Persist `prompt_evolution.py`'s variant state if it's going to be part
  of the answer at all.** `self.variants` resetting on every process
  restart is a correctness bug independent of GRPO — any ratified variant
  is already silently lost today, with or without RL. This needs fixing
  regardless of which write path (a) or (b) above gets chosen.

This is real, scoped work — not a redesign — but it's a different and more
foundational piece than "add group scoring," and it should happen *before*
5.2/5.3's scoring math, not after, since scoring something that has nowhere
real to land doesn't get you closer to "GRPO actually works."

### 5.5 Step 4 — multi-trajectory queue (later, depends on Steps 1-3)

Doc 1's Phase 3 table correctly puts this at P1, after the P0 items above.
Nothing here changes that sequencing — it genuinely depends on task-type
classification and group scoring existing first, since "queue N variants of
the same task type and compare" requires knowing what "the same task type"
means (Step 1) and how to compare them (Steps 2-3). No new findings here;
the original sequencing holds — though per 5.4 above, "Steps 2-3" now
includes fixing the write path before this step has anything real to queue
toward.

---

## 6. The build sequence — numbered, with dependencies

Two tracks, equal priority, running in parallel. Within each track, order
matters — the dependencies are real, not just tidiness.

### Track A — Workshop knowledge loop

```
A1. Resolve the memory-location decision (Section 4.4)
    └── no code dependency, but do this FIRST — every later step writes
        to memory/ or .techne/memory/, and doing this after the fact
        means re-touching everything

A2. Wire REFRESH_CONTEXT as a real phase (Section 4.2)
    └── depends on: A1 (so the new phase writes to the right location)
    └── does NOT depend on: A3, A4 — can ship before the graph is enriched,
        it'll just have less to refresh at first

A3. Connect existing entries to existing subsystem nodes (Section 4.3, Step 1)
    └── depends on: A1
    └── this is the highest-value single step in Track A — prioritize it
        even above A2 if forced to choose, since it makes RECALL noticeably
        better with the least amount of new code

A4. Add task nodes + task-triggered edges (Section 4.3, Step 2)
    └── depends on: A3 (reuses the same edge-vocabulary pattern)

A5. CONCLUDE git-gate scoping fix (Section 3.2, Flaw 2)
    └── no dependency on A1-A4, can happen any time, including in parallel
        with all of Track A

A6. HITL re-entry state machine fix (Section 3.2, Flaw 1)
    └── no dependency, can happen any time

A7. Honcho proof-verification (checkpoint.py extension, Section 4.5)
    └── no dependency on A1-A6 — fully parallel
    └── design is now resolved (Hermes calls Honcho, Techne verifies a real
        proof file via checkpoint.py); this is genuinely small, similar
        effort to A2's gate-translation logic. Has a dependency OUTSIDE this
        repo: needs Hermes-side wiring to call mark_honcho_concluded() after
        a real Honcho call — confirm that side before marking this done

A8. Adapters for symbol/route/schema/test node types (Section 4.3, Step 3)
    └── depends on: A4
    └── deliberately last — separate skill set (language parsing), Doc 2
        already sequences this as its own later phase, no reason to disagree
```

### Track B — GRPO

```
B0. Fix the skill-write path BEFORE scoring work (Section 5.4)
    └── no dependency on B1-B4 — do this FIRST, not after
    └── decide: route GRPO proposals through apply_retro.py's existing
        write functions (reuse working code), or give prompt_evolution.py's
        ratify() a real write step for the first time (currently has none)
    └── either way: persist prompt_evolution.py's self.variants (currently
        lost on every restart) and resolve what to do with the dormant
        auto_apply_pending() bypass — do not leave it reachable
    └── THIS IS THE BLOCKER for "GRPO actually updates the skillbase" —
        B1-B3 below produce a number with nowhere real to land until B0
        is done

B1. Task-type classifier from existing discipline/tags (Section 5.2)
    └── no dependency on Track A or B0 — can start in parallel with B0

B2. Group-based scoring / advantage computation (Section 5.3)
    └── depends on: B1

B3. Policy update — write a real proposal through B0's chosen path
    └── depends on: B0, B2
    └── must route through a real human-confirmation step, not
        auto_apply_pending() or any equivalent silent-apply path

B4. Multi-trajectory queue (Section 5.5)
    └── depends on: B1, B2, B3
```

**B0 is the one item in this entire document that changes the answer to
"can we say Techne does X."** Everything else audited so far (REFRESH_CONTEXT,
the knowledge graph, Honcho) was "exists but disconnected, or thin but
real." The skill-write side of GRPO is "the thing that would receive the
update doesn't have a working delivery mechanism connected to it yet,
except for one dormant function that would skip the human gate entirely if
anyone wired it in without noticing." Treat B0 as a prerequisite gate on the
whole track, not a parallel task — scoring math that can't reach a file is
not progress toward "GRPO actually works."

### Recommended first slice, if picking a starting point today

Given everything above, the single best first ticket is **A3** (connect
existing mistake/decision/lesson entries to subsystem nodes), not A2
(wiring the refresh phase), even though A2 looked like the obvious first
move in the earlier draft of this audit. The reasoning: A2 wires a phase
that, on its own, mostly refreshes file/subsystem mappings that are already
fairly current — the *content* that would make a refreshed graph actually
worth having (the mistake/lesson connections) doesn't exist yet. A3 is
cheaper than A2 (no new pipeline phase, no state-machine changes, just new
edges in an existing function) and delivers a more noticeable improvement to
RECALL on its own. A2 becomes much more valuable *after* A3 exists, because
then there's something substantive for the refresh phase to keep fresh.

If two people are available, A3 and B1 can start on the same day with zero
coordination needed between them — but **if "GRPO actually updating the
skillbase" is the priority, B0 outranks B1.** B1 (the task classifier) is
pleasant, low-risk, parallel-friendly work. B0 (fixing the write path) is
the thing that determines whether any of B1-B4 produces a real outcome at
all. Starting B1 before B0 risks ending up with a well-classified,
well-scored GRPO system that still has nowhere real to write its
conclusions — same shape as building REFRESH_CONTEXT before the graph had
anything worth refreshing, but with a sharper downside: a half-wired GRPO
loop is one accidental call to `auto_apply_pending()` away from shipping
unreviewed changes to the skill base, which is the exact failure mode the
human-ratify principle exists to prevent.

---

## 7. Guardrails — specific things this audit found that are easy to break

These aren't generic engineering advice. Each one is tied to something
concrete found while reading the actual code.

0. **Do not wire any GRPO output to `apply_retro.auto_apply_pending()`.**
   This needs to be guardrail zero, not guardrail six, given the explicit
   ask for GRPO that "correctly updates the skillbase." That function
   exists, applies every pending proposal with zero confirmation, and its
   own docstring incorrectly claims it's already used by the conductor's
   retro phase — which makes it easy to assume, while building GRPO's
   policy-update step, that calling it is just "using the existing
   integration" rather than introducing a new one. It is not currently
   called by anything. Keep it that way, or remove it, until there's a
   deliberate decision to have a non-human-gated path — which Doc 1's risk
   table, and this conversation, both say should not exist.

1. **Don't let REFRESH_CONTEXT (A2) silently swallow failures.**
   `_get_uncommitted_context_files()` (Section 3.2) already has an
   `except Exception: return []` pattern — "error → skip the gate rather
   than block." That's a defensible choice for a gate that's meant to be
   conservative about blocking work. It is **not** a defensible pattern for
   a refresh phase whose entire purpose is keeping knowledge from going
   stale — a refresh that fails silently is worse than no refresh phase at
   all, because it creates false confidence that context is current. Fail
   loud here, even where the codebase's existing convention elsewhere fails
   quiet.

2. **Don't duplicate the wikilink rebuild logic.** There are now two
   call sites that rebuild parts of the graph: `_log_retro_learn_trigger()`
   (conditional, mistake-recurrence-triggered, repo-root `memory/`) and the
   new `REFRESH_CONTEXT` phase (Section 4.2, `.techne/memory/`, via
   `refresh_generated_docs.py`). After Section 4.4's memory-location
   decision, one of these two call sites should be retired, not kept as a
   second, slightly-different path to the same data. Two independent
   rebuild triggers that don't know about each other is exactly the kind of
   thing that causes "wait, why does this say something different than that"
   bugs six months from now.

3. **Don't let GRPO's group scoring read from `discipline` values that
   don't actually distinguish much.** Section 5.2 recommends starting with
   `discipline` because it's free, real data — but it's coarse (5 values).
   If the first batch of group-scored runs shows `tdd` and `implement` tasks
   getting near-identical advantage distributions, that's a signal the
   classifier needs `tags`-based refinement before trusting any policy
   update decisions made from it. Check this before B3 (policy update) ships
   anything, not after.

4. **Respect the `entries`/`nodes`-disconnect finding when writing new
   graph code.** `harness/wikilink.py:273-275` overwrites `graph["nodes"]`
   and `graph["edges"]` wholesale on every call to `build_graph()`. Any new
   code that adds edges between entries and subsystems (Section 4.3, Step 1)
   has to happen *inside* `_attach_workshop_graph()` or after it returns,
   not before — otherwise the wholesale overwrite will erase the new edges
   on the next rebuild.

5. **The HITL guard fix (A6) needs a regression test before it ships**, not
   after. Doc 1 already flagged "54 tests is not enough... add phase-ordering
   property tests" — that's now even more true given the actual count is
   271, since a fix to `pipeline_enforcer.py:148` touches code that's almost
   certainly load-bearing for several of those 271 tests already passing for
   the wrong reason (passing because they don't exercise the edge case the
   bandaid was written for, not because the logic is actually correct for
   every case). Write the failing test for the specific edge case first,
   confirm it fails against current code, then fix.

6. **Don't build the missing scripts from Doc 2 §1
   (`propose_context_updates.py`, `stale_docs_check.py`,
   `touched_subsystems.py`) as new standalone CLI tools before checking
   whether their logic already exists inside `harness/workshop.py`.**
   Section 4.1 already found that `stale_context_reasons()` and
   `detect_subsystems_for_files()` exist there and are called by
   `refresh_generated_docs.py`. If a standalone CLI is genuinely wanted
   for human-driven, ad hoc use (separate from the pipeline phase), it
   should be a thin wrapper around those existing functions, not a
   reimplementation.

---

## 8. Definition of done, per milestone

Carried over from Doc 1 §7 where it still applies, sharpened where the
audit found the original criteria too vague to verify against.

| Milestone | Done when |
|---|---|
| **A1 (memory consolidation)** | One memory location is canonical. `config.yaml`'s `memory_dir` and every default path in `reward.py`/`mistakes.py`/`wikilink.py` agree with each other. No script writes to both `memory/` and `.techne/memory/` as independent sources of truth — at most one is a generated mirror of the other |
| **A2 (REFRESH_CONTEXT phase)** | `REFRESH_CONTEXT` appears in `PHASES` and `TRANSITIONS`. A real task run produces a `mark_complete()` record for the phase. A failing script run produces a `RETRY`, not a silent pass. `tests/test_workshop_foundation.py`'s existing standalone test still passes, plus a new test exercises the phase through `orchestrator_loop`, not just the script directly |
| **A3 (entry-to-subsystem edges)** | A mistake or lesson entry, given to `context_search.py` for a subsystem it applies to, shows up in the ranked output — not just the subsystem doc and file list, but the specific lesson/mistake text. Verifiable by running `context_search.py "<subsystem>"` against a fixture with a known mistake entry and asserting it appears in `LESSONS:` or `MISTAKES:` output |
| **A4 (task nodes)** | RECALL on a file that's been touched by 2+ prior tasks surfaces "this file was touched by tasks X, Y" with each task's outcome — not just "this file is in subsystem auth" |
| **A5 (CONCLUDE gate scoping)** | A test reproduces the exact false-block scenario (task touches `auth.CONTEXT.md`, unrelated dirty file is `billing.CONTEXT.md`) and confirms CONCLUDE now passes |
| **A6 (HITL guard)** | The specific edge case the bandaid was patching, plus at least one adjacent edge case the bandaid doesn't cover, both have passing tests against the *general* fix, not just the original case |
| **A7 (Honcho proof)** | `checkpoint.py` has `mark_honcho_concluded()` / `check_honcho_logged()`. The RECALL and CONCLUDE gates check `check_honcho_logged()`, not a substring in model output. A test confirms that a phase with no logged Honcho call is rejected even if its output text contains the string `honcho_context:` — proving the gate no longer trusts prose. `increment_pipeline_run()` resets the Honcho flag alongside `verification_logged`. Confirmed (separately, on the Hermes side) that Hermes calls `mark_honcho_concluded()` after a genuine Honcho call, not just at task setup |
| **B1 (task classifier)** | Two tasks with the same `discipline` and overlapping `tags` are confirmed to land in the same group when queried, and two tasks with different `discipline` values land in different groups |
| **B2 (group scoring)** | A `Reward` record has a non-null `advantage` field, computed against a real group mean, not a placeholder |
| **B0 (skill-write path)** | A test proves that a GRPO-style proposal, once approved through whichever human-confirmation step was chosen (5.4), produces a real, verifiable change to a file under `skills/` — not just a new row in `proposals.json` or a mutation of an in-memory dict that disappears on restart. A separate test proves that an *unapproved* proposal produces no file change, no matter how high its advantage score. `auto_apply_pending()` is either deleted, or has a test proving it is unreachable from any automated path |
| **B3 (policy update)** | A high-advantage prompt variant produces a real, persisted change to a `skills/*.md` file — through B0's chosen path — only after passing the same explicit human-confirmation step `apply_retro.py` already uses for retro proposals. Verifiable by checking the file's content before and after, not just checking that a proposal record exists |
| **Whole plan** | Re-running this same audit process (read the real code, not the planning docs) six months from now finds the claims in this document still accurate, or finds them out of date in ways that are themselves evidence of progress, not drift |

---

## Appendix — file map quick reference

For whoever picks up the first ticket and wants the paths without re-reading
the whole document:

```
harness/pipeline_enforcer.py     — PHASES, TRANSITIONS, can_enter(), mark_complete()
harness/orchestrator_loop.py     — phase handlers (_submit_*), _build_workshop_recall_lines(),
                                    _get_uncommitted_context_files(), _log_retro_learn_trigger()
harness/wikilink.py              — build_graph(), _attach_workshop_graph(), parse_mistakes(),
                                    parse_ledger(), format_markdown()
harness/checkpoint.py            — mark_verified()/check_verification() pattern to extend
                                    for mark_honcho_concluded()/check_honcho_logged()
harness/store.py                 — TECHNE_STATE_DIR env var, the existing Hermes→Techne
                                    handoff convention (read_json/write_json, state_dir())
harness/workshop.py              — find_workshop_paths(), build_context_index(),
                                    detect_subsystems_for_files(), stale_context_reasons(),
                                    touched_files_from_git(), classify_policy()
harness/reward_log.py            — Reward, RewardLog, _composite_score()
harness/reward.py                — log_clean(), log_solved(), count_by_skill()
harness/prompt_evolution.py      — propose/validate/ratify LOGGING only; ratify() does not
                                    write to skills/, and self.variants resets on restart
harness/apply_retro.py           — the REAL skill-write path: apply_add/apply_delete/
                                    apply_resolve write into skills/*.md. Human-confirmed
                                    by default. auto_apply_pending() bypasses confirmation
                                    and is NOT currently called by conductor.py — keep it that way
harness/gate_evolution.py        — same firewall pattern, for gates
harness/task_db.py               — Task dataclass: tags, discipline, phase_mode
.techne/config.yaml              — policy_generated / policy_proposed / policy_manual
.techne/scripts/context_index.py            — builds context_index.json
.techne/scripts/context_search.py           — RECALL retrieval, already wired in
.techne/scripts/refresh_generated_docs.py   — built, NOT wired into any pipeline phase
memory/ledger.md, memory/mistakes.md        — repo-root location, NOT .techne/memory/
.techne/memory/wikilinks.json               — contains BOTH structural graph AND
                                               legacy entries array, currently disconnected
tests/test_workshop_foundation.py           — covers context_index, context_search,
                                               refresh_generated_docs (standalone),
                                               wikilink graph attachment
```

