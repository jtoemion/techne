---
name: kanban-roles
description: Locked spec + reference for Hermes — the verification subagent roles that check Kanban work without becoming the authority. Reviewer + adversarial bug-scout as critics, explorer as an upstream context-provider, over a deterministic floor and under a human anchor. Read when staffing a Kanban board's review panel or wiring these as Hermes profiles. Sub-skill of skills/kanban.md.
---

# Kanban Verification Roles (reference for Hermes)

A subagent can REVIEW another's work, but a model is never the authority — it gives a
second opinion, not ground truth. So roles are NARROW and layered: the panel raises the
quality signal; a deterministic floor and a human keep the regress from bottoming out in
"a model said so." Independence comes from DIFFERENT functions, not more reviewers.

## The locked architecture

```
every deliverable  → DETERMINISTIC FLOOR gate (cheap, authoritative, host-run):
                       exists in a persistent dir · matches the card's contract ·
                       non-stub · grounded (sources if required).         → hard reward/mistake
earned items only  → PANEL (parallel, isolated subagents):
                       reviewer + bug-scout          (+ explorer UPSTREAM, not in panel)
                       consolidate by DISAGREEMENT → soft reward/mistake, PER ROLE
calls that matter  → HUMAN ANCHOR (approve/shelve/modify).                → strong reward/mistake
```

The panel is EARNED: run the floor gate on everything, convene the panel only on items
that clear a cheap value/risk filter (like the triage score threshold). Subagents never
override the floor or replace the human.

## Role cards (each is a Hermes profile + a narrow skill)

```
REVIEWER — critic
  Function : judge the deliverable against the card's contract + quality.
  Scope    : the returned deliverable + the definition-of-done. ONLY judge —
             do not rewrite, do not add context.
  Emits    : PASS | CONCERNS + specific located flags.
  Authority: SOFT signal (advisory), like Techne's REVIEW phase (HARD_FAIL→SOFT_FAIL).

BUG-SCOUT — adversarial critic (the high-value role)
  Function : assume the deliverable is flawed; hunt ONLY for what's broken/wrong/unsafe.
  Scope    : adversarial probing. Do not rate overall quality, do not rewrite.
  Emits    : located suspected bugs/risks; "none found" is a valid result.
  Authority: SOFT, but flags are weighted as SHADOW-GATE signal — catches what the
             reviewer and the floor gate missed. Orthogonal coverage > a 2nd reviewer.

EXPLORER — context-provider (NOT a critic)
  Function : surface prior art / related context the worker lacked.
  Scope    : improves the INPUT, does not judge the OUTPUT. No pass/fail authority.
  Placement: UPSTREAM — before/during the work, or as a "redo with this context" trigger.
             Keep it OUT of the review panel (don't mix "is it done right?" with "do it better").
  Emits    : fresh context / "you may have missed X".
```

## Consolidation — disagreement is the signal

```
The panel's verdict is the UNION of flags, not a majority vote. One credible bug-scout
flag the others missed is the WHOLE point — surface it, don't average it away. Agreement
= higher confidence; divergence = the shadow-gate moment worth a human's attention.
```

## Independence (or the panel is theater)

```
Two critics off the same model + prompt make CORRELATED errors. Decorrelate by:
  - different FUNCTION (reviewer vs adversarial scout) — the main lever, baked in above.
  - different PROMPT/role, and where possible a DIFFERENT MODEL per profile
    (the triage engine runs scouts on different providers on purpose).
Each runs as an isolated dispatched subagent (own KB): hand it ONLY the card + deliverable;
it reports a verdict; consolidation happens HOST-SIDE (a worker can't grade itself).
```

## Reward attribution (per role, into the RL loop)

```
Tag each win/mistake by ROLE in reward.py / mistakes.py:
  bug-scout catches a real escape   → win for bug-scout
  a bug slips past the bug-scout    → mistake against bug-scout
So the loop learns WHICH ROLES earn their tokens (does reviewer #2 pull weight, or is the
bug-scout carrying the panel?). Soft signal only — a model's verdict never auto-steers.
```

## Next Steps

- The gate-free lane these roles check → `skills/kanban.md`
- Isolated-worker contract (each role is one) → `skills/kanban/isolation.md`
- The reward signal this feeds (per-role) → `harness/reward.py`
- The deterministic floor gate (the authoritative anchor) → `harness/worker_gate.py`
  (`Acceptance` = the card's definition-of-done; `check_deliverable` / `enforce`)
- Wire each role as a Hermes profile + skill → see the triage `roles:`→profile pattern
