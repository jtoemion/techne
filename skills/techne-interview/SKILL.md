---
name: techne-interview
description: Socratic planning interview that produces a Decision-Complete ticket before techne init. Fills OBJECTIVE/CONSTRAINTS/DONE_WHEN until no choices remain for the implementer. Chains to grill for adversarial validation. Inspired by OMO's Prometheus + OMH's omh-deep-interview.
triggers:
  - techne plan
  - plan a task
  - interview before implementing
  - decision-complete ticket
  - what should I build
  - planning interview
---

# Techne Interview — Decision-Complete Ticket

## One Line

You are not done until DONE_WHEN is concrete, CONSTRAINTS are hard, and the implementer has **zero choices left**.

## Why This Exists

The most common failure mode in Techne is a vague RECALL. Vague RECALL → wrong IMPLEMENT → VERIFY fails → expensive retry. This skill runs BEFORE `techne init` and eliminates that failure mode at the source.

Reference design: OMO's Prometheus (Tab → interview → Metis gap-analysis → Momus validation → `/start-work`) + OMH's `omh-deep-interview` (Socratic coverage tracking).

---

## Pre-Read (do before asking a single question)

```
1. CONTEXT.md           — resolved terms and domain glossary
2. docs/adr/            — existing decisions (don't re-litigate them)
3. .techne/config.yaml  — project_name, stack, active constraints
4. Relevant source files — read the code, don't assume
```

Anything answerable from these → answer it yourself. Do not ask the user for information you can derive.

---

## The Ticket Schema (fill every field before closing)

```
TASK_ID:      <short-slug>
OBJECTIVE:    <one sentence: what changes and why>
CONSTRAINTS:  <hard limits: no new deps, must not touch X, etc.>
DONE_WHEN:    <concrete test: "pytest passes", "page renders X", "output contains Y">
OUT_OF_SCOPE: <explicit list of what is NOT being built>
CONTEXT_FILES: <list of files the implementer must read>
```

A ticket is Decision-Complete when:
- [ ] OBJECTIVE is a single sentence with one verb
- [ ] CONSTRAINTS rules out at least one design that would otherwise be tempting
- [ ] DONE_WHEN is a condition a machine (or a careful human) can evaluate without judgment
- [ ] OUT_OF_SCOPE names at least one thing that was explicitly discussed and rejected
- [ ] CONTEXT_FILES lists every file the implementer needs — not "relevant files", exact paths

---

## Interview Process

### Phase 1 — Scope (2–4 questions max)

Ask about:
- What is the minimum deliverable? (surfaces scope creep risk early)
- What is NOT in scope? (surfaces assumed dependencies)
- What already exists that the implementer can reuse?

One question at a time. Wait for each answer.

### Phase 2 — Constraints (1–3 questions)

Ask about:
- What must not change? (APIs, contracts, files, packages)
- What is the performance / compatibility / security boundary?
- What's the budget? (lines of diff, complexity ceiling)

### Phase 3 — DONE_WHEN (1–2 questions)

The most important phase. Ask:
- "How will we know it works?" — push until the answer is a specific test or observable
- "If I wrote a script to check DONE_WHEN, what would it do?" — forces concreteness

Reject vague DONE_WHEN: "works correctly" → NOT a criterion. "pytest returns 0 errors and output contains 'sale' badge in HTML" → criterion.

### Phase 4 — Coverage Check

Before closing, verify:

| Field | Status |
|---|---|
| OBJECTIVE | [ ] one sentence, one verb |
| CONSTRAINTS | [ ] rules out ≥1 design |
| DONE_WHEN | [ ] machine-evaluable |
| OUT_OF_SCOPE | [ ] ≥1 explicit exclusion |
| CONTEXT_FILES | [ ] exact paths listed |

Any uncovered field → ask ONE targeted question to close it.

---

## Adversarial Pass (chain to grill)

After the ticket is filled, run a grill pass BEFORE handing to `techne init`:

```
Simulate the implementer reading the ticket cold.
Ask:
  "What would they have to guess?"
  "What term is ambiguous?"
  "What edge case is unhandled?"
  "What would they be tempted to build that's out of scope?"
```

Each gap → one follow-up question → close the gap → update ticket.

Stop when grill produces no new questions.

---

## Output — the Decision-Complete Ticket

Write to `.techne/loop/ticket.md`:

```markdown
# Decision-Complete Ticket

**TASK_ID:** <slug>
**OBJECTIVE:** <one sentence>
**CONSTRAINTS:**
- <constraint 1>
- <constraint 2>
**DONE_WHEN:** <concrete condition>
**OUT_OF_SCOPE:**
- <exclusion 1>
- <exclusion 2>
**CONTEXT_FILES:**
- <exact/path/to/file.py>
- <exact/path/to/file.md>

---
*Produced by techne-interview + grill. Ready for `techne init`.*
```

Then run:
```bash
techne init <TASK_ID>
```

---

## Red Flags — STOP

- Implementer has choices left → not done, keep interviewing
- DONE_WHEN contains "works" or "correct" without a measurable qualifier → push for the test
- More than 5 questions total asked without a ticket draft → you are stalling; draft what you have, then grill the gaps
- User says "just get started" → acknowledge, but write at least a minimal ticket first (OBJECTIVE + DONE_WHEN + 1 constraint)

---

## Next Steps

- Ticket produced → run `techne init <TASK_ID>` and proceed to RECALL phase
- Need to stress-test the ticket further? → `skills/grill.md` (one more adversarial pass)
- Persona discovery first (no direction yet)? → `skills/persona-brainstorm.md` before interviewing
- Already have a ticket and just want to start? → `techne init <TASK_ID>` directly
