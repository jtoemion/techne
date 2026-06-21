# Techne Workshop Build Guide — Patch 001

Date: 2026-06-21
Patches: `techne-workshop-build-guide.md` (2026-06-20)
Status: Findings from re-auditing the repo after Track B (GRPO) and Track A
(REFRESH_CONTEXT, Honcho proof) were built.

> This is an addendum, not a rewrite. The original guide's diagnosis,
> sequencing, and guardrails still hold — most of what it asked for got
> built, and built well in its individual pieces. This patch exists because
> three things changed since: the build actually happened, running the real
> test suite surfaced two live bugs, and a scoping gap was found in GRPO that
> the original guide didn't anticipate. Read this alongside the original,
> not instead of it.

---

## P0. What got built since the original guide — confirmed, not assumed

Re-extracting and re-diffing the repo against the previous audit found real,
substantial new work, matching the original guide's Track A and Track B
closely:

| Guide item | Built? | File |
|---|---|---|
| A2 — `REFRESH_CONTEXT` as a real phase | ✅ | `pipeline_enforcer.py` — `REFRESH_CONTEXT` now in `PHASES`, between `CONCLUDE` and `DONE` |
| A7 — Honcho proof-verification via `checkpoint.py` | ✅ | `mark_honcho_concluded()` / `check_honcho_logged()` exist, including the run-reset the original guide specifically asked for |
| B0 — disable `auto_apply_pending()` | ✅ | Now raises `RuntimeError` on call instead of silently bypassing confirmation — correct fix, not deletion, so nothing breaks at import time |
| B0 — route GRPO writes through `apply_retro.py` | ✅ | `harness/grpo.py`'s docstring explicitly cites this decision |
| B1 — cheap task classifier from `discipline`/`tags` | ✅ | `harness/classify.py`, docstring cites "build guide §5.2" directly |
| B2 — group-relative advantage scoring | ✅ | `RewardLog.compute_batch_advantages()`, `cnt >= 2` noise filter included unprompted |
| Persist `prompt_evolution.py`'s ratified variants | ✅ | `_save_variants()` / `_load_variants()` added — closes the "lost on restart" bug the original guide flagged |
| B4 — multi-trajectory queue | ✅ (built, but disconnected — see P1) | `harness/trajectory_queue.py`, 416 lines, well-tested in isolation |

This is worth stating plainly: whoever built this read the guide closely
and got the hard calls right, including the one the guide called the single
most important finding (don't wire GRPO to `auto_apply_pending()`). The
problems below are integration gaps and one scoping miss, not bad
engineering.

---

## P1. Live bug — GRPO's advantage is never computed on the path that matters

**Found by tracing the actual call graph, not by reading docstrings.**

`harness/grpo.py:propose_grpo_edits()` reads `RewardLog.high_advantage_variants()`,
which filters on the `advantage` column. That column is only ever populated
by `RewardLog.compute_batch_advantages()`. Tracing every call site of that
function:

```
harness/trajectory_queue.py:185:   self.reward_log.compute_batch_advantages()
```

**That is the only call site in the entire codebase.** `compute_batch_advantages()`
is never called from `orchestrator_loop.py`, `conductor.py`, or anywhere in
the normal single-task pipeline path. And `TrajectoryQueue` itself — the one
thing that *does* call it — is never instantiated anywhere in
`orchestrator_loop.py` or `conductor.py` either:

```
grep -rln "TrajectoryQueue\b" harness/orchestrator_loop.py harness/conductor.py
→ no matches
```

**What this means concretely:** for any task that runs through the normal
pipeline (RECALL → ... → DONE, the path essentially every real task takes),
`advantage` stays at its default `0.0` forever. `propose_grpo_edits()` *is*
correctly wired into `post_run_evolve()` and *does* run after every batch —
but it's reading a column nothing ever fills in for that path. GRPO will
silently propose nothing, indefinitely, until a task is deliberately routed
through `TrajectoryQueue` — which nothing currently does automatically.

**Where `post_run_evolve()` itself is called, confirmed:**

```python
# harness/driver.py:227
evolution = loop.post_run_evolve() if evolve else {}
```

— `evolve` defaults to `True`, and this fires once per batch (not once per
task) inside the batch driver. So the call chain is intact end to end
*except* for the one missing line inside it.

**The fix is one line, in `post_run_evolve()`, before the existing
`propose_grpo_edits()` call:**

```python
# harness/orchestrator_loop.py, inside post_run_evolve(), B3 block:
if self.reward_log is not None:
    try:
        self.reward_log.compute_batch_advantages()   # ADD THIS — was missing
        grpo_proposals = propose_grpo_edits(self.reward_log)
        result["grpo_proposed"] = grpo_proposals
    except Exception:
        result["grpo_proposed"] = []
```

This was the answer to "is GRPO functioning?" — no, not on the path that
matters, for exactly this reason. Every individual piece (B0-B2) is real
and correctly built. The wire connecting "a batch of tasks finished" to
"advantage gets computed for them" is the one missing line.

---

## P2. Live bug — `prompt_variants.json` is a shared, unparameterized file

**This is not theoretical. Running the test suite during this audit
actually mutated the real, live `.techne/memory/prompt_variants.json`.**
Confirmed directly — the file now contains:

```json
"implementer": {
  "v1_strict": { "...": "..." },
  "v2_pragmatic": { "...": "..." },
  "v3_contextual": { "...": "..." },
  "v1_strict_evolved": {
    "description": "Evolved from v1_strict",
    "temperature": 0.15000000000000002
  }
}
```

`v1_strict_evolved` was written by a test run, not by any real ratification
decision.

**Root cause.** `prompt_evolution.py` added persistence for `ratify()`
(correctly — the original guide flagged the in-memory-only bug and this
closes it):

```python
VARIANTS_FILE = MEMORY_DIR / "prompt_variants.json"   # module-level constant
```

`proposals_path` is already a constructor parameter, correctly isolated to
a temp file by every test (`PromptEvolution(log, proposals_path=proposals.name)`).
`VARIANTS_FILE` has no equivalent parameter — every `PromptEvolution()`
instance, in every test and in production, reads and writes the same real
file. Tests that ratify a variant leave it there permanently; later tests
(and the real pipeline) load it back as if it were always part of the
default set.

**Confirmed effect — running the suite twice in this audit session, the
failure count went from 22 to 24,** because each run adds more accumulated
state to the same file. This will keep growing every time anyone runs the
tests until it's fixed, and it's actively corrupting `.techne/memory/` in
the real project right now — not just in a test sandbox.

**Specific tests broken by this, confirmed by running them:**

- `tests/test_prompt_proposals.py::test_ratify_refuses_unvalidated`
- `tests/test_prompt_proposals.py::test_ratify_reject_path`
- `tests/test_prompt_proposals.py::test_evolve_no_longer_auto_activates`
- `tests/test_trajectory_queue.py::test_variant_dedup` — fails because its
  assumption `"at most 3 variants (implementer has 3 defaults)"` breaks once
  a 4th, leaked variant has accumulated

**The fix, matching the pattern `proposals_path` already uses:**

```python
class PromptEvolution:
    def __init__(self, log, proposals_path=None, variants_path=None):
        self.proposals_path = Path(proposals_path or DEFAULT_PROPOSALS_PATH)
        self.variants_path = Path(variants_path or VARIANTS_FILE)   # NEW
        self.variants = copy.deepcopy(DEFAULT_VARIANTS)
        self._load_variants()   # reads self.variants_path, not the module constant

    def _save_variants(self) -> None:
        self.variants_path.write_text(json.dumps(self.variants, indent=2))

    def _load_variants(self) -> None:
        if self.variants_path.exists():
            # ... existing load logic, against self.variants_path
            pass
```

Then every test that calls `ratify(approved=True)` needs `variants_path=`
passed alongside its existing `proposals_path=` — the same fix shape, just
applied to the field that was missed.

**Immediate cleanup needed regardless of the code fix:** the real
`.techne/memory/prompt_variants.json` already has `v1_strict_evolved` in it
from this audit's test runs. That entry should be removed by hand (or via a
one-off script) once the isolation fix ships — otherwise the first
production pipeline run after the fix will load a variant that was never
legitimately ratified.

---

## P3. Live bug — the Honcho gate shipped without updating its blast radius

**Confirmed by running each affected test file in isolation, not just the
full suite.** `test_bake_pipeline.py`, run completely on its own, fails
with:

```
"RECALL phase required: run honcho_search or honcho_context first
 to recall durable context."
```

This is the gate from the original guide's Section 4.5 (Honcho
proof-verification) working exactly as designed — `check_honcho_logged()`
correctly rejects a RECALL that never called `mark_honcho_concluded()`. The
problem is that **three pre-existing test files were never updated to
satisfy the new gate**, confirmed by checking each for any Honcho
reference at all:

```
grep -n "honcho" tests/test_bake_pipeline.py     → 0 matches
grep -n "honcho" tests/test_enforcement.py       → 0 matches
grep -n "honcho" tests/test_hitl_recovery.py     → 0 matches
```

These three files account for roughly 20 of the 24 current failures. The
gate logic itself is not the bug — it's doing its job correctly. The bug is
that shipping a stricter gate without updating (or adding a shared fixture
for) the tests that exercise the phase it gates left a known-good test
suite in a broken state.

**The fix — not a design change, a test-fixture addition.** Either:

- add a `conftest.py` fixture that calls
  `checkpoint.mark_honcho_concluded("test-fixture-id")` before any test that
  drives a task through RECALL, or
- have each of the three affected files call it explicitly in their setup,
  matching whatever pattern they already use for other phase preconditions.

**Also still missing, called out in the original guide and still true:**
no test exists that proves `check_honcho_logged()` correctly *rejects* a
phase when nothing was logged — every current test either satisfies the
gate or hits it by accident (as these three now do). A deliberate
"gate blocks when Honcho wasn't actually called" test is still owed.

---

## P4. Scoping gap — GRPO targets prompt variants only; it needs to target skills too

**This is not a bug — it's a real scope correction, found while checking
whether GRPO could already do something it was assumed to do.**

GRPO's entire comparison axis today is `prompt_variant`. Confirmed by
checking the `Reward` dataclass directly: there is no `skill` field on it
at all.

```
grep -n "skill" harness/reward_log.py   → no matches
```

And `harness/grpo.py`'s proposal target is hardcoded, not derived from the
task that earned the advantage:

```python
DEFAULT_SKILL_FILE = "skills/implementer.md"   # every proposal goes here, always
```

So today, GRPO can answer *"which prompt variant scores better for this
task type"* — but it cannot answer *"is `skills/svelte.md` actually helping
or hurting, compared to other skills handling similar tasks"* — because the
reward log never records which skill was routed for a given task in the
first place. This is a missing dimension, not a misconfigured one.

**What's needed, in order:**

1. **Add a `skill` field to `Reward`,** with the matching `ALTER TABLE`
   migration (same pattern already used for the `group`/`advantage`
   migration). Whatever code writes a `Reward` record after a task
   completes needs to pass the skill that `router.route()` returned for
   that task — confirmed that `route()` already returns a real skill dict
   with a score, so the data exists at routing time, it's just never
   threaded through to the reward record.

2. **Decide what `group` means now that there are two comparison axes.**
   This is a real design decision, not a default to assume:
   - **Option A:** keep `group`/`advantage` as prompt-variant-only, and add
     a second, independent pair (`skill_group`/`skill_advantage`) for the
     skill axis. A task can be simultaneously "good prompt variant, weak
     skill" or vice versa — collapsing both into one number would erase
     that distinction.
   - **Option B:** make `group` polymorphic depending on which proposal
     path is running (group by `prompt_variant` for prompt comparisons,
     group by `skill` for skill comparisons), storing whichever grouping
     was active per record.
   - This patch recommends **Option A** — two separate, clearly-named
     columns — because Option B makes a single `advantage` value ambiguous
     about which axis it's crediting, which defeats the purpose of having
     group-relative scoring in the first place.

3. **Add `high_advantage_skills()` to `RewardLog`,** sibling to the
   existing `high_advantage_variants()`, grouping by `(task_type, skill)`
   instead of `(task_type, prompt_variant)`, with the same `cnt >= 2` noise
   floor already used elsewhere.

4. **Add `propose_skill_edits()` to `grpo.py`,** sibling to
   `propose_grpo_edits()`, targeting `f"skills/{skill}.md"` per row from
   `high_advantage_skills()` — never the current hardcoded
   `DEFAULT_SKILL_FILE`. This is the function that actually closes the gap
   named in this patch's title: GRPO proposing real edits to the skill that
   earned (or lost) the advantage, not always the same one file.

**How this connects to the separately-discussed dedup/lessons mechanism:**
`propose_skill_edits()` (comparative — *this skill scores worse than its
peers*) and the dedup/lessons mechanism (count-based — *this mistake keeps
recurring*) are complementary, not redundant. Recurrence tells you
something is wrong; group-relative advantage tells you whether a specific
skill is the actual cause, versus the task type just being hard. Both
should be able to write to `retro_proposals.md` through the same human-gated
`apply_retro.py` path — this patch doesn't change that part of the design.

---

## P5. Gap closed — the Receptionist→Orchestrator handoff had no trigger rule

**This was raised as "pipeline switch from receptionist to orchestrator is
automatic" — confirmed on follow-up this was a request, not a claim about
existing behavior.** Checked directly: the handoff *mechanism* already
exists in spec form (`delegate_task` with `MODE: IMPLEMENT` is what starts
Techne's RECALL→...→DONE pipeline — confirmed in
`docs/host-integration-guide.md` §3.3, §3.4). What's missing is the
**decision rule for when the host fires it automatically**, rather than
relying on in-the-moment judgment at the "CLASSIFY" step.

**Confirmed gap:** `receptionist/SKILL.md` §2 names "Classify" as a loop
step — *"does this need EXPLORE first... or can you ticket straight to
BUILD/IMPLEMENT/DEBUGGING?"* — but gives no concrete trigger conditions.
`docs/host-integration-guide.md` §4.1 repeats the same loop with the same
gap. Both treat the EXPLORE-vs-IMPLEMENT decision as host judgment, every
time, which is the opposite of automatic.

**One existing rule already points the right direction, just isn't phrased
as a trigger.** §3.4 of the host guide: *"a typo fix does not get a
shortcut... There is no `phase_mode='fast'` escape for code changes."* That
rule is already absolute — any code change goes through the full pipeline,
no exceptions, no judgment call needed. The fix here is to state that as
the actual classify-time rule, not just as a footnote about typos.

**The rule, stated as something the host can apply instantly, without
deliberating per-request:**

> **If the request will result in any file being created, edited, or
> deleted in the target codebase, dispatch `MODE: IMPLEMENT` (or
> `MODE: DEBUGGING` for a reproducible-failure fix — both produce a diff,
> both go through the full pipeline, no carve-out). EXPLORE runs first,
> automatically and immediately followed by IMPLEMENT/DEBUGGING in the same
> turn — never as a separate, judgment-gated dispatch — only when the host
> doesn't yet have enough context to write the ticket itself (unfamiliar
> file layout, unclear current implementation). SCOUT applies the same way,
> for external/API unfamiliarity rather than codebase unfamiliarity. The
> only work that stays outside Techne's pipeline entirely is read-only
> analysis, research, or planning that will never produce a diff.**

This resolves both follow-up questions directly:

- **EXPLORE/SCOUT before IMPLEMENT:** confirmed — always run EXPLORE first
  when the codebase area is unfamiliar, but it chains automatically into
  IMPLEMENT once it returns. It's a prerequisite step inside one automatic
  sequence, not a separate triage gate the host pauses at to decide
  whether to continue.
- **DEBUGGING and the pipeline:** confirmed — DEBUGGING also auto-triggers
  the full pipeline. This was already implied by the existing "no
  `phase_mode=fast` escape for code changes" rule (§3.5 confirms `fast`
  mode is valid only for review-only tasks with zero file modifications,
  and a debugging fix is, by definition, a file modification) — this patch
  just makes the implication explicit rather than leaving it to be
  inferred.

**Where this should be written, concretely:** add a numbered "§2.1
Automatic dispatch rule" to `receptionist/SKILL.md`, directly under the
existing "Classify" bullet in §2, stating the rule above verbatim rather
than leaving Classify undefined. Mirror it in
`docs/host-integration-guide.md` §4.1, since both files currently repeat
the same loop and would otherwise drift if only one is updated. No code
changes are required for this fix — it's a documentation/protocol gap, not
a missing function, since the actual dispatch mechanism (`delegate_task`
→ `MODE: IMPLEMENT` → Techne's pipeline) already works exactly as
intended once it's called.

### P5.1 — Going further: collapse three of five modes into Techne directly

**Raised as a follow-up: "can't we just make Receptionist just another
door to Techne's pipeline, instead of a parallel system?"** Checked this
against both protocol files precisely before answering, because the honest
answer is "partially" — two of the five modes genuinely can't collapse, but
three can, and that's a bigger simplification than it first sounds.

**Why EXPLORE and SCOUT can't become Techne phases.** Checked Techne's
actual phase list (`pipeline_enforcer.py:43-54`) — there is no read-only,
no-diff phase anywhere in it. RECALL was the closest candidate, but its
actual scope (confirmed in `orchestrator_loop.py:_submit_recall()`) is
narrow and assumes a task already exists with a clear objective — it
grounds IMPLEMENT, it doesn't build open-ended situational awareness when
no ticket can be written yet. EXPLORE and SCOUT's entire purpose is the
step *before* that — deciding a Techne task is even needed and gathering
what's required to write its ticket. They're structurally upstream of
Techne's pipeline, not a competing parallel pipeline to it.

**Why BUILD, IMPLEMENT, and DEBUGGING already overlap almost entirely.**
All three produce a diff. Checked their actual output contracts
(`references/receptionist-protocol.md` §"The Five Modes") — BUILD's diff
goes through the same kind of validation IMPLEMENT's would, just for
net-new files instead of edits to existing ones; DEBUGGING's diff is the
same shape too, with one addition (a root-cause statement and regression
risk note) that IMPLEMENT's ticket schema doesn't currently ask for. None
of these three needs its own mode — Techne's CONTEXT_GUARD / CRITIQUE /
REVIEW / VERIFY phases don't care *why* a diff exists, only whether it's
correct, scoped, and tested. Maintaining three separate ticket schemas for
"new code," "wiring," and "a fix" is drift waiting to happen, when one
schema with a conditional field covers all three.

**Resolved: fold DEBUGGING's root-cause discipline into the merged ticket
schema, rather than keeping it as a separate type.** This was an open
design choice — discussed and settled in favor of one schema over a
CRITIQUE-phase-absorbs-it alternative, since CRITIQUE already has its own
job (risk analysis, BLOCK_HITL judgment) and overloading it with
root-cause bookkeeping would blur what CRITIQUE is for.

**The collapsed mode set — two outside Techne, one door into it:**

```
Any request
   │
   ▼
Will this produce a diff? ──NO──→ EXPLORE / SCOUT (stays outside Techne —
   │                                the only legitimate parallel work left)
   │ YES
   ▼
delegate_task MODE: IMPLEMENT  (BUILD and DEBUGGING absorbed into this —
   │                             see merged schema below)
   ▼
Techne pipeline: RECALL → ... → DONE
```

**The merged ticket schema — one schema, one new conditional field:**

```yaml
MODE: IMPLEMENT
OBJECTIVE: <1-2 sentences, single outcome>
CONTEXT: <curated file paths/excerpts from prior EXPLORE — never the whole repo>
CONSTRAINTS: <architecture rules, layer boundaries, "do not touch X">
DONE_WHEN: <concrete, checkable verification criteria>
OUTPUT_FORMAT: <diff | report | both>
FIX_OF: <optional — fill this in for any ticket that fixes a reproducible
         failure rather than building something new. When present, the
         subagent's report MUST include: root cause statement, the
         specific failure being fixed (error text / failing test name),
         and a regression-risk note. Omit entirely for net-new work.>
```

`FIX_OF` is the one new field. Everything DEBUGGING used to require
(root cause, minimal diff, verification output, regression risk) becomes a
conditional requirement on IMPLEMENT instead of a separate mode definition
— present and enforced when `FIX_OF` is filled in, absent otherwise. BUILD
disappears with no replacement field needed, since "construct net-new
code" and "wire it into the live system" were always going to go through
the same CONTEXT_GUARD/CRITIQUE/REVIEW/VERIFY validation regardless of
which mode produced the diff — the distinction was about *staging* (new
files vs. wiring), which the diff itself already shows without needing a
separate ticket type to declare it.

**What this changes concretely, in the actual files:**

- `receptionist/SKILL.md` §3 ("The Five Modes") becomes **three modes**:
  EXPLORE, SCOUT, IMPLEMENT (with the conditional `FIX_OF` field absorbing
  BUILD and DEBUGGING's old jobs).
- `references/receptionist-protocol.md`'s "Ticket Schema" section gets the
  `FIX_OF` field added, and its "The Five Modes" section drops BUILD and
  DEBUGGING's separate write-ups, folding their "Allowed/Forbidden/Output
  contract" content into IMPLEMENT's entry as the `FIX_OF`-present case.
  `docs/host-integration-guide.md` §4.2's schema needs the same addition,
  since it currently repeats the same five-field schema and would drift if
  only one file is updated — same risk P5 already flagged for the dispatch
  rule itself.
- No change needed to Techne's own code (`pipeline_enforcer.py`,
  `orchestrator_loop.py`) — this collapse happens entirely on the
  Receptionist side, one layer above where Techne's phases live. Techne
  was never the thing that needed three modes; it's IMPLEMENT's ticket
  schema that did.

**What this does not solve, flagged honestly:** this still leaves
Receptionist's own "gates" — Verification Gate, One retry max, "never
blend modes" — as prose instructions with nothing underneath enforcing
them, the same gap raised in conversation just before this one. Collapsing
five modes to three doesn't fix that; it just means there are fewer
unenforced mode boundaries to potentially violate. Whether Receptionist's
prose-only gates need actual code enforcement (something closer to
`pipeline_enforcer.py`'s `can_enter()`, at the Receptionist layer instead
of just Techne's) is still open and not addressed by this collapse.

---

### P5.2 — Built: `harness/receptionist_enforcer.py`

**Resolves the open question above for the parts of Receptionist's
protocol that can be checked mechanically.** Built and tested against the
real `TaskDB`, not just written as a design sketch — 12 tests in
`tests/test_receptionist_enforcer.py`, all passing, run against the actual
repo. One real bug was found and fixed in the process (see below), which
is worth noting precisely because it's the same standard this whole audit
has held the rest of the codebase to.

**What it gates, mapped directly to the prose rules it replaces:**

| Protocol rule (prose) | Enforced by |
|---|---|
| "Don't blend EXPLORE+BUILD in a single dispatch. Modes don't mix." | `can_dispatch()` rejects a ticket being dispatched under a second, different mode once one is already recorded |
| "One subagent = one mode = one ticket" | Same check — a ticket's mode is fixed at first dispatch |
| "A delegation isn't done until you've read and accepted its report. No fire-and-forget." | `close_ticket()` requires a `VERIFIED(accepted=True)` event in history; there is no path from DISPATCHED straight to CLOSED |
| "One retry max... if the second attempt also fails, stop and flag to the user" | `mark_retry()` raises on a second retry attempt; `can_dispatch()` blocks a third dispatch after one retry has already been re-dispatched once |
| FIX_OF's root-cause/regression-risk requirement (P5.1's absorption of DEBUGGING) | `mark_verified()` refuses to accept a `FIX_OF`-tagged ticket unless both fields are supplied |
| Unknown/retired modes (BUILD, DEBUGGING) | `can_dispatch()` rejects them outright, with the rejection message pointing to `IMPLEMENT` + `FIX_OF` instead of silently accepting a stale mode name |

**Not gated, deliberately, stated rather than glossed over:** "Never
execute work yourself" — the Receptionist's own prime directive not to
write code directly. No per-ticket check can observe what the Receptionist
itself did outside any ticket; this is a property of the host's behavior,
not the ticket lifecycle. The module's docstring says this explicitly
rather than implying broader coverage than it has.

**The bug found while building this, worth noting as a pattern, not just
a footnote.** The first version of `can_dispatch()`'s retry-exhaustion
check blocked a dispatch immediately after one `mark_retry()` call — one
attempt too early. The actual protocol rule is "original dispatch + one
re-dispatch is allowed; a third is blocked," not "any dispatch after any
retry is blocked." Running the test suite against the first draft caught
this immediately (`test_same_mode_redispatch_allowed_for_retry` failed),
and the fix was to count dispatch attempts directly rather than inferring
exhaustion from the presence of a retry marker. This is the same category
of bug the broader audit kept finding elsewhere in the codebase — a gate
that's *almost* right, off by one step in its own enforcement boundary —
and it's worth treating as a reminder that writing a gate doesn't
guarantee the gate is correct; it still needs a test that would fail if
the boundary were wrong, which is what caught this one.

**Where this needs to actually get used, for it to matter:** same caveat
as every other piece of code in this patch — building the gate doesn't
enforce anything by itself. `receptionist/SKILL.md` and
`docs/host-integration-guide.md` would need to instruct whoever drives the
Receptionist (the host model, each session) to actually call
`can_dispatch()` before every `delegate_task` call and `mark_verified()`
before every ticket close, the same way Techne's own phase handlers call
`pipeline_enforcer.can_enter()` before every phase. Without that
instruction, this is a correct, tested module sitting unused — exactly the
shape of gap P1 found for GRPO's `compute_batch_advantages()`.

---

## P6. Open questions carried over, not yet resolved

These came up in conversation and are real, but don't yet have enough
information to spec precisely — flagging them here so they aren't lost.

- **Receptionist's own gates had no code enforcement — now resolved by
  P5.2 above.** `harness/receptionist_enforcer.py` closes this for the parts of
  the protocol that can be checked mechanically (mode-blending, retry
  limits, verify-before-close, FIX_OF's conditional requirements). Still
  open: whether "never execute work yourself" needs — or even can have —
  any enforcement beyond the prose instruction, since that's a property of
  what the host does outside any ticket, not something a per-ticket check
  can observe.

- **`delegate_task` model routing.** Confirmed this is a Hermes/Receptionist
  concept (`receptionist/references/model-routing.md`), a layer above
  Techne's own phases, currently pinned to one free-tier model
  (`deepseek-v4-flash:free`) with no fallback chain at all. The ask is for
  a `minimax.io minimax-m2.7` fallback when free-tier capacity is
  exhausted, but it's still undecided whether this fallback applies at the
  Receptionist-mode layer (EXPLORE/BUILD/etc.) or should also reach into
  which model handles specific Techne phases (CRITIQUE/REVIEW are the
  strongest candidates for a smarter model, since their entire job is
  catching what a cheaper model missed). Needs its own design pass once
  P1-P4 are settled.

- **Framework-specific skill files don't exist yet.** `skills/svelte.md`,
  `skills/react.md`, `skills/typescript.md` aren't in the repo —
  `propose_skill_edits()` (P4) and the dedup/lessons mechanism both need
  somewhere correct to target once a relevant mistake or low-advantage
  pattern is detected for one of these stacks. Whether to create these
  files now (as empty scaffolding) or let the first real proposal create
  them on demand is still open.

---

## Priority order for this patch

1. **P2 first** — it's actively corrupting the real project file on every
   test run, including ones run for unrelated reasons. Cheapest fix in this
   document, highest ongoing cost if left alone.
2. **P3 next** — restores the test suite to a state where P1/P4 work can be
   verified by tests that actually pass, rather than against a suite that's
   already red for unrelated reasons.
3. **P1** — the one-line fix that makes GRPO's existing, correctly-built
   pieces actually reachable from the path real tasks take.
4. **P5** — documentation-only, zero code risk, can happen in parallel with
   anything else in this list. Worth doing early simply because it's free
   and immediately changes how every future ticket gets dispatched.
5. **P4** — the larger piece. Genuinely new schema and logic, not a
   one-line fix, and should happen after P1-P3 so it's built and tested
   against a clean, green baseline.
