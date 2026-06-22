# Metaprompt: How I Drive the Techne Pipeline — Worked Through, Task by Task

> This is written in first person, as the worker doing the task — not as
> abstract instructions to follow, but as my actual reasoning, the
> parameters I set up before I touch any code, and why I set them that
> way. Read it the way you'd read someone narrating their own work over
> your shoulder. Copy the *judgment*, not just the steps — the steps
> change per task, the judgment doesn't.
>
> Everything below is grounded in `references/*.md` files that already
> exist in this exact repo — `rl-pipeline-findings-2026-06-21.md`,
> `interactive-pipeline-driving.md`, `tdd-yagni-pipeline-guide.md`,
> `bug-audit-parallel-dispatch.md`, `subagent-scope-pitfalls.md`,
> `improve-architecture-pitfalls.md`, `context-refresh-bookend.md`,
> `file-authorship-convention.md`. These came from 18+ real pipeline
> runs, not theory. Where I say "I do X because Y," the Y is something
> that was actually observed failing or succeeding in those runs — I'll
> cite which doc it came from so you can go check it yourself rather than
> trust me blindly.

---

## Before any task — the parameters I decide first, and why

I never start a task by opening a file. I start by answering five
questions, because every one of them changes how the rest of the work
goes, and getting them wrong costs a retry cycle or worse.

**1. Does this need the full pipeline, or is it read-only?**

If the work will produce zero file changes — an audit, a bug hunt, a
report — it never touches `db.create_task()` at all. It's EXPLORE work
(`bug-audit-parallel-dispatch.md` §Phase 2), dispatched as a read-only
subagent, output written to a file, no pipeline phase involved. I decide
this *before* anything else because getting it wrong either wastes a
pipeline run on something that produces no diff, or — worse — lets a
"just look around" task quietly start editing files with no gates
checking it.

**2. `phase_mode`: `full` or `fast`?**

`fast` skips RECALL, CONCLUDE, and REFRESH_CONTEXT
(`rl-pipeline-findings-2026-06-21.md` Finding 10). I reach for `fast`
only when **all** of these are true: the diff is ≤5 lines, it's a single
file, and there's no `.techne/config.yaml` in this project (which would
make REFRESH_CONTEXT fail outright per Finding 6). If any of those isn't
true, I use `full`, even for a "trivial" fix — the InkForge session
findings are explicit that even 1-line fixes went through full mode and
that was the right call, because the gates caught real format problems
on attempts that *looked* trivial going in.

I set this at task creation, not after:
```python
task = db.create_task(title='fix-trivial-thing', phase_mode='fast')   # or 'full'
```
Changing my mind mid-pipeline about `phase_mode` isn't a thing I can do —
get this right at the start or redo the task.

**3. Is `.techne/config.yaml` present in this project root?**

I check this *before* creating the task, not when REFRESH_CONTEXT fails
on me. `ls .techne/config.yaml` costs one command. If it's missing and
I'm planning `phase_mode=full`, I have two real choices, and I pick
deliberately, not by default:
- Create a minimal one now (`interactive-pipeline-driving.md`'s example:
  `name`, `type`, `framework`, `app_dir`, `build_cmd`, `build_dir`) if
  this project is going to see more than one pipeline task.
- Use `phase_mode=fast` for this one task if it's a one-shot fix and I
  don't want to leave workshop scaffolding behind for a project that
  doesn't otherwise use Techne.

This branch's own code (Patch 3, already applied in
`harness/orchestrator_loop.py:_submit_refresh_context()`) now degrades
gracefully if I forget — REFRESH_CONTEXT skips itself and returns DONE
rather than hard-failing. I still decide this up front rather than
relying on that fallback, because the graceful skip means I silently get
*no* context refresh, which is a real cost on a long-lived project even
though it's not an error.

**4. Honcho discipline — set this up before the first phase, not after.**

`tdd-yagni-pipeline-guide.md`'s "Honcho discipline" section is explicit:
`honcho_context(peer='user')` is the **first action of the turn**, before
`create_task`. And `honcho_conclude()` happens after **every** phase
submit, not just at the end — including for `fast`-mode tasks, where the
parent agent (me) has to do it manually since the pipeline itself doesn't
enforce it in fast mode.

I also know, from `interactive-pipeline-driving.md`'s pitfalls section,
that calling the Honcho tool alone does **not** satisfy RECALL's gate —
`checkpoint.check_honcho_logged()` reads a state file, and a real
`honcho_conclude()` call doesn't automatically write to it in every
environment. If RECALL rejects me with a Honcho-related message despite
having called the tool, I write the state directly:
```python
from checkpoint import read_state, write_state
state = read_state()
state['honcho_conclusion_id'] = 'my-id'
write_state(state)
```
I check for this failure mode *before* assuming the gate is broken —
it's a documented, known pitfall, not a new bug to chase.

**5. If this is a multi-file or multi-subagent task: scope it before dispatching, not after a timeout.**

`subagent-scope-pitfalls.md` has real, measured numbers I take seriously:
a single-file schema audit timed out at 8 tool calls; a 10-file auth-guard
task timed out at 37 calls, twice, even after retrying. The pattern isn't
file count alone — it's **read→edit→verify cycles**, and MiniMax-M2.7
(the model actually in use here) doesn't parallelize across files, so
cost scales roughly linearly with file count and roughly nonlinearly with
how many times each file gets touched (read, then patch, then test, then
maybe re-patch).

My rule, before I write a single `delegate_task` call: **if the change
touches more than ~6-8 files, I split it into multiple subagents along
real boundaries** — by dependency (tests with the code they test) or by
layer (auth-guard backend changes separate from the test-file fixes for
them), never an arbitrary chunk. I decide the split *before* dispatching
the first one, not after the first one times out.

---

## Task type 1 — A single, well-defined bug fix (TDD + YAGNI)

**What "done" should look like before I start:** a 2-10 line diff, one
failing test that now passes, the full suite still green, and a CONCLUDE
submission with a committed SHA. If I'm imagining anything bigger than
that before I've even looked at the bug, I'm already over-scoping it.

**How I actually do it**, following `tdd-yagni-pipeline-guide.md`
exactly, because this is the most battle-tested single doc in the set:

1. **RED first.** If the existing test encodes the bug (asserts the
   broken behavior), I fix the *assertion* first and run it to confirm it
   now fails. I do not skip this — `tdd-yagni-pipeline-guide.md`'s
   "Common pitfalls" is blunt about it: if I didn't watch the test fail,
   I don't actually know it detects the bug, I'm just assuming.

2. **GREEN with the minimum diff.** I count lines before I submit. The
   real example in that doc — a phantom-import bug that should have been
   a 1-line fix — got over-built into 90 lines (new state, a `useEffect`,
   a 129-line test file with MSW setup) by a subagent that defaulted to
   "build a complete solution" instead of "fix the line that's wrong."
   The actual fix, once reverted and redone correctly, was 3 lines. My
   personal check before I submit IMPLEMENT: **if my diff adds
   infrastructure (new state, new hooks, new test scaffolding) that the
   bug itself didn't have, I've over-built — I throw it away and redo it
   smaller**, the same call that doc's author made.

3. **If I'm dispatching this to a subagent rather than fixing it myself**,
   the prompt gets this exact block appended, verbatim, not paraphrased —
   this isn't decoration, it's the thing that was missing the time a
   subagent added three extra server tests nobody asked for:
   ```
   YAGNI RULES:
   - Change ONLY the minimum to fix the bug
   - Do NOT add new endpoints unless the bug requires it
   - Do NOT add new tests beyond what's needed for the fix
   - Do NOT refactor nearby code that isn't part of the bug
   - Do NOT add error handling beyond the minimal fix
   - Count the lines you changed before submitting — if >10 source lines, reconsider
   ```

4. **Drive the phases**, submitting real content each gate actually
   checks for — not what seems reasonable, what's *documented as
   required*, because guessing here is exactly what cost 2-3 retries per
   task in the InkForge session:
   - RECALL: must start with a literal `WORKSHOP_CONTEXT:` line naming
     real paths I actually read. ("RECALL missing WORKSHOP_CONTEXT line"
     is the gate's own rejection message if I forget — I don't treat
     that as a mysterious failure, I know exactly what it wants.)
   - IMPLEMENT: must contain real `@@` or `--- `/`+++ ` diff markers
     somewhere in the text — a prose description of the fix, no matter
     how accurate, gets rejected. If I'm relaying a subagent's summary, I
     check it has the actual diff before I submit it, not just a
     description of one.
   - CONTEXT_GUARD: a `CONCLUDE PUNCH LIST` section with `DOCS:`,
     `CONTEXT:`, `HONCHO:` lines — each either real content or
     `NOT_NEEDED` with a one-line reason.
   - RETRO: ≥100 characters, and it has to *name* a completed phase
     (IMPLEMENT, REVIEW, VERIFY, etc.) somewhere in the text, not just be
     long. "Retro: all good" is 13 characters and names nothing — it
     fails on both counts, not by accident.
   - CONCLUDE: the CONTEXT line needs the literal `sha:` prefix followed
     by the **committed** SHA — and the commit has to happen *before* I
     submit, not after. I update `.techne/context/context_hash.txt`
     (commit count, test count, timestamp), commit that, run
     `git rev-parse HEAD`, and only then write the CONCLUDE text with
     `sha:<that-hash>`. Getting the order backwards (submit, then commit)
     is the single most repeated friction point in the whole session log
     — 3/3 full-phase runs hit it on the first attempt.

5. **REVIEW will hit BLOCK_HITL. Expect it, don't fight it, prepare for
   it.** Every full-phase run in the session log hit this, even 4-line
   fixes — it's the gate working as intended, not a bug to route around.
   What I do differently because of this: I have the test output *ready*
   before I submit REVIEW, not after the human asks for it.
   `tdd-yagni-pipeline-guide.md`'s lesson is specific: the user's first
   question at BLOCK_HITL is "tests need to be green" — so my unblock
   message is "All N tests pass across all workspaces. Here's the diff.
   Proceed?", not a bare summary that makes them ask the obvious question
   themselves.

---

## Task type 2 — A multi-layer bug audit (find many, fix one at a time)

**What "done" should look like before I start:** a single consolidated
report with every bug classified by layer and severity, a status table
that gets checked off bug-by-bug as fixes land, and zero bugs fixed
*during* the audit phase — finding and fixing are separate phases on
purpose.

**How I actually do it**, per `bug-audit-parallel-dispatch.md` and
`bug-hunt-report-format.md`:

1. **Classify into layers before dispatching anything.** Five layers,
   fixed taxonomy, not improvised per project: UI, State/Stores,
   Service/Data, Backend, Schema/Database (or the UI/Hooks/Service/DAL/
   Database variant if the project's architecture maps better to that —
   I pick whichever the project's actual directory structure matches,
   I don't force a layer model that doesn't fit). The point of fixing the
   taxonomy in advance is that reports stay comparable across sessions —
   if I invent new layer names every audit, nothing accumulates.

2. **One read-only EXPLORE subagent per layer, dispatched together.**
   Each one gets an exact, bounded file list (not "look around
   `src/`") and a fixed output schema — `bug-hunt-report-format.md`'s
   `### Bug #N` template, with File/Line/Severity/Category/Description/
   Fix-suggestion, every field, every time, because a report I can't
   compare to the last one isn't actually durable. I tell every subagent
   explicitly: **READ ONLY, do not modify any files** — this phase
   produces a report, not a diff, and I don't blur that line even when a
   subagent could technically fix what it found while it's already
   looking at the file.

3. **Collate, don't fix, while collating.** One consolidated doc, severity
   table at the top, three most-critical bugs called out by name. I
   resist the pull to fix the obvious one-liner I notice while reading
   the reports — that's scope creep into the next phase, and
   `tdd-yagni-pipeline-guide.md`'s P0-first ordering exists precisely
   because skipping ahead on the bug that looks easiest, before the
   priority order is even settled, wastes the prioritization step.

4. **Fix in priority order, one pipeline task per bug, no exceptions.**
   Critical → High → Medium → Low. Every fix is Task Type 1's full
   discipline (RED→GREEN→pipeline), not a shortcut because it came from
   an audit instead of a bug report. I do **not** critique-and-review the
   fixes as I go — `tdd-yagni-pipeline-guide.md`'s session-discipline
   note is specific about this, and it came from a real mid-session
   correction: fix all of one priority tier first, *then* do critique and
   review of that whole batch together, because the priority order can
   shift as new things surface mid-fix, and reviewing piecemeal wastes
   the review pass when that happens.

5. **Parallelize fixes only across different files and different
   layers, never more than 3 at once, never the same file twice in
   parallel.** If bug A is in `Service/` and bug B is in `UI/` and they
   share no files, I dispatch both `delegate_task` calls together. If
   they touch the same file, or I already have 3 in flight, I queue it
   instead — merge conflicts and rate limits are real, measured costs
   here, not theoretical ones.

---

## Task type 3 — Architecture deepening (shallow → deep modules)

**What "done" should look like before I start:** one candidate, picked
and pressure-tested, with a before/after that's measurable — not a list
of five things that "could be better" with nothing actually decided.

**How I actually do it**, per `skills/improve-architecture.md` plus the
session correction in `improve-architecture-pitfalls.md`:

1. **Bugs before architecture, always, no exceptions.** If there's a
   known defect in a module I'm about to call "shallow," I fix the
   defect first. A module that looks shallow because it's *broken* reads
   completely differently once it's *correct* — I don't want to deepen
   the interface around a bug I haven't fixed yet, since I'd likely be
   designing around the wrong problem.

2. **EXPLORE → CANDIDATES → PICK ONE → GRILL, in that order, and I
   don't skip PICK ONE even under time pressure.** CANDIDATES gets
   presented as the six-column table (Files | Problem | Solution |
   Benefit | Before/After | Strength), and I genuinely wait for a human
   pick rather than just running with the one I personally find most
   interesting — unless the human has already told me to decide.

3. **If the human says "fix remaining issues" or "decide with best for
   the app in mind," I make the call myself, on every remaining
   candidate, and report pass/skip with the reasoning** — I don't re-ask
   per candidate once that instruction's been given, since that defeats
   the point of delegating the decision. My triage, per candidate:
   - **Strong** → do it. Clear before/after, I can point to the
     measurable improvement.
   - **Worth exploring** → real merit, not urgent — I do it only if
     explicitly told "fix all remaining," otherwise I document it and
     move on.
   - **Speculative** → I don't write code for this. I write down *why*
     it's speculative (what would have to be true for it to matter) and
     skip it. Documenting the reasoning is the deliverable here, not a
     placeholder for future work.

4. **GRILL only the picked candidate** — constraints, the shape of the
   deepened module, what sits behind the new seam, which tests survive
   the change unmodified (the ones that don't survive unmodified are a
   signal the interface change was bigger than intended).

---

## A standing rule that applies to every task type above: file authorship

Per `file-authorship-convention.md` — if I'm adding my own take on
something that already has a document (a session retro, a report, a
prior agent's analysis), I do **not** edit that document to add my
perspective into it. I restore the original if I touched it, and write
my own file, my own name, sitting alongside it. The pattern is
`docs/retro/2026-06-22-session.md` (left alone) +
`docs/retro/2026-06-22-inkforge.md` (mine). This doesn't apply to scratch
files I created myself, or to a file the user explicitly handed me to
edit — only to documents that already represent someone else's (or a
prior session's) perspective. The reasoning: different perspectives
belong in different files, not blended into different sections of the
same one, because blending makes it impossible to tell later who said
what and when.

---

## The bookend I never skip: context refresh

Per `context-refresh-bookend.md` — context gets built at session start
and refreshed after *every* completed change, not just at the end of a
big batch. After a task reaches DONE, I check (don't blindly regenerate)
which of `project_digest.md`, `file_roles.md`, `commands.md`,
`risk_boundaries.md`, the relevant `context_packs/*.md`, and always
`context_hash.txt` actually need updating given what changed. A read-only
task (an audit, a report) still updates `context_hash.txt` and adds a
findings pack — "nothing changed" is not the same as "nothing to record."
What I don't do: rebuild every context file from scratch on every task,
or let drift accumulate because updating "felt unnecessary" for a small
change. `context-refresh-bookend.md`'s own line is the one I hold myself
to: a stale context pack is worse than no context pack, because stale
context is trusted and wrong, while no context is at least honestly
empty.

---

## Definition of done, for whoever's checking this work

Not "I did the steps." Specifically:

- [ ] The test that encodes the bug was watched failing (RED), not assumed.
- [ ] The diff is the minimum needed — if it's bigger than the bug's own
      complexity, it was reverted and redone smaller, with the before/after
      line counts stated.
- [ ] Every gate's exact documented format was used on the first
      submission attempt where the format was already known (RECALL's
      `WORKSHOP_CONTEXT:`, CONCLUDE's `sha:` prefix, RETRO's ≥100 chars +
      phase name) — retries from guessing the format are a sign this
      metaprompt wasn't actually followed, not a normal cost of doing
      business.
- [ ] `honcho_context` ran first, `honcho_conclude` ran after every
      submit, including for fast-mode tasks.
- [ ] Context files were checked for relevance and updated where they
      were actually stale — not regenerated wholesale, not skipped because
      it felt like a small change.
- [ ] If a subagent's output looked over-built relative to the bug's
      actual complexity, it was reverted and redone, not accepted because
      it "technically worked."
- [ ] The full test suite was run at the end, not just the changed test —
      and the actual pass/fail count is reported, not a summary claiming
      success without the numbers behind it.
