---
name: retro
description: Comprehensive retrospective format. Required sections, gate requirements (100+ chars, must reference completed phases), and what disqualifies a retro as flat/minimal.
triggers:
  - retro phase
  - retrospective
  - 7 questions
  - retro questions
---

# Retro — Structured Retrospective

## When to Use

RETRO runs after every pipeline completion — pass or fail. It is not optional.

## Required Sections

Every retro submission must include all of the following in order:

### 1. Session Overview
- **Goal** — what was the task, in one line
- **Done** — what actually shipped (files changed, tests added, gates passed)
- **Challenges & Constraints** — obstacles + limits (tooling, framework, environment, missing context)

### 2. Key Metrics
- Pipeline score (from EVAL phase, if available)
- Gate violations count
- Retries used
- Phase completion status

### 3. Per-Phase Breakdown
For each completed phase (RECALL → IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → EVAL):
- What the phase was supposed to do
- What it actually produced
- Any violations or issues

### 4. Friction Analysis
- What caused the most friction during this run
- Where the process broke down (not the code — the process)
- What assumptions proved wrong

### 5. Discipline Scorecard
Rate each discipline dimension:
- **Skills loaded** — yes/no, which ones
- **Mistakes consulted** — yes/no
- **Diff focused** — yes/no
- **Scope creep** — yes/no
- **Gate violations** — count and which gates

### 6. Action Items
Concrete, specific next steps:
- What to add to skill files
- What gates to propose
- What to stop doing
- What to start doing

## Gate Requirements

- **Minimum 100 characters** — flat one-liners are rejected
- **Must reference completed phases** — retro must mention which phases ran and what happened in each
- **Must answer all 7 questions** — Q1 (Goal), Q2 (Done), Q3 (Challenges), Q4 (Room), Q5 (Flaws), Q6 (Better), Q7 (How)

## The 7 Questions (answer each in 1–3 sentences)

1. **GOAL** — what was the task, in one line?
2. **DONE** — what actually shipped? (files changed, tests added, gates passed)
3. **CHALLENGES & CONSTRAINTS** — what obstacles + limits did you work within?
4. **ROOM OF IMPROVEMENT** — what would you do differently starting over?
5. **FLAWS TO FLAG** — what was wrong with the process, not the code?
6. **WHAT I DO BETTER** — what behavior improved since last retro?
7. **HOW I DO BETTER** — what specifically changed in the workflow?

Plus two additional questions:
8. **PATTERNS** — what is now a known pattern for future work?
9. **REGRESSION WATCH** — what could silently break later? Name the signal to watch and where.

## Comprehensive Format Required

A retro is **rejected as flat/minimal** if it:
- Provides only a one-line summary
- Fails to mention any completed phases
- Does not include friction analysis or discipline scorecard
- Has fewer than 100 characters of actual content
- Lists only what went right without analyzing what went wrong

The retro must demonstrate genuine reflection. Listing facts without analysis is not a retro.

## Output Format

Write to `harness/memory/retro_proposals.md`:

```
## Retro — <ISO date>

### 7-Question Summary
GOAL: ...
DONE: ...
CHALLENGES: ...
ROOM: ...
FLAWS: ...
BETTER: ...
HOW: ...
PATTERNS: ...
REGRESSION: ...

### Key Metrics
- Score: X/100 (GRADE)
- Gate violations: N
- Retries: N
- Phases completed: ...

### Per-Phase Breakdown
[RECALL] ... | [IMPLEMENT] ... | [CONTEXT_GUARD] ... | ...

### Friction Analysis
...

### Discipline Scorecard
- Skills loaded: yes/no
- Mistakes consulted: yes/no
- Diff focused: yes/no
- Scope creep: yes/no

### Action Items
1. ...
2. ...

### Ledger Entries (if any)
DECISION: ... | WHY: ... | SKILL: ...
LESSON: ... | WHY: ... | SKILL: ...
DISCIPLINE: ... | WHY: ... | SKILL: ...
```

## Ledger Integration

Append durable entries to `memory/ledger.md`:
- **DECISION** — a choice about HOW to work + why
- **LESSON** — something learned about the process, with evidence
- **DISCIPLINE** — a method that worked and should be repeated

## Skill Proposal Integration

After the 7 questions, analyze the routed skill:
- **2+ ACTIVE mistakes on one skill** → PROPOSE ADD to that skill file
- Weight low + not seen in 10 runs → PROPOSE DELETE
- Root cause now gated → PROPOSE RESOLVE

## Hard Constraints

- Retro is mandatory — runs even on clean passes
- Minimum 100 characters of substantive content
- Must reference completed phases by name
- Must answer all 7 (+2) questions
- Flat/minimal retros are rejected by the gate

## Next Steps

- Retro complete? → CONCLUDE phase runs next
- Want to see past retros? → read `harness/memory/retro_proposals.md`
- Apply retro proposals? → `python harness/apply_retro.py` (human review first)
