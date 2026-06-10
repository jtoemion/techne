---
name: writing-skill/discipline
description: Harden a discipline/rule/gate skill so the model obeys it under pressure. A strong model already drafts rationalization tables and loophole lists on its own — spend your effort where it's weak: honest RED-first proof, real (not faked) enforcement, and when-to-use-only descriptions. Load when the skill enforces a rule a smart model will rationalize past — gates, TDD, verification, required workflows.
---

# Hardening a Discipline Skill

A technique skill fails by being unclear. A discipline skill fails when a SMART
model, under pressure, talks itself out of obeying. Your adversary is the reader's
own rationalization.

## Spend Effort Where the Model Is Weak

A strong model, told to write a discipline skill, will ALREADY produce a
rationalization table and a thorough loophole list unprompted. Don't pad the skill
re-teaching that. The three things it skips — and where your hardening actually
pays — are below. (This was measured: a baseline agent nailed the table and
loopholes on its own, but faked enforcement, declared itself done, and wrote a
what-it-does description.)

```
1. HONEST PROOF      → it declares "done" after a format check. Force RED-first.
2. REAL ENFORCEMENT  → it stamps gate: yes on rules the gate can't catch. Force a check.
3. WHEN-TO-USE DESC  → it summarizes the workflow. Force symptom-only triggers.
```

## 1. Honest Proof — RED First

```
NO DISCIPLINE SKILL WITHOUT A WATCHED FAILING BASELINE.
```

Run the rule's pressure on a subagent WITHOUT the skill. Log the exact
rationalizations it reaches for — verbatim. A rationalization table you IMAGINED is
worthless; agents rationalize in ways you won't predict. Until you've watched the
baseline fail, every table and red-flags list is PROVISIONAL — label it so, and do
not call the skill done.

```
RED      → pressure scenario, no skill. Log every excuse verbatim.
GREEN    → counter THOSE excuses. No hypothetical extras.
REFACTOR → new loophole appears? Add an explicit counter. Re-run til clean.
```

Pressure = stacked forces: time + sunk cost + authority + exhaustion. One rarely
breaks compliance; three usually do. Test the stack, not a single nudge.

## 2. Real Enforcement — A Gate That Can't Fire Is a Lie

Before you write `# gate: yes`, open `harness/gates.py` and confirm the gate can
ACTUALLY catch the violation. Techne's gates read the **diff** — so a rule about a
*command* (`git commit --no-verify`, `--force`) or a runtime act never shows up in a
diff and CANNOT be gated there. Stamping `gate: yes` anyway ships a skill that lies
about being enforced — worse than no gate, because reviewers trust it.

```
Diff-visible (@ts-ignore, redirect outside middleware) → write the gate. Done.
Not diff-visible (command flags, env vars, runtime)    → say so, name the real layer
  (pre-commit wrapper / CI check), keep the prose honest about being advisory.
```

A real gate beats a MUST. A fake gate is worse than a MUST.

## 3. When-to-Use Description ONLY

Do NOT summarize the workflow in the description — for a discipline skill the body
IS the enforcement, and a step-summary becomes a shortcut the model follows instead
of reading it. Trigger on the symptom of being ABOUT to violate:

```yaml
description: Use when about to commit or push, when a hook is slow or failing, or when reaching for --no-verify
```

## The Artifacts (the model drafts these — you make them REAL)

Keep all three; the discipline is that they come from the watched RED, not imagination:

- **Rationalization table** — every baseline excuse + the reality that defeats it.
- **Red flags list** — self-deception phrases the model can catch itself using mid-rationalization.
- **"Violating the letter of the rule is violating the spirit."** — one line that
  kills the whole "I followed the spirit" loophole class. Always include it.

## When It's Hard Enough

```
[ ] Baseline watched WITHOUT the skill; rationalizations logged verbatim (RED)
[ ] Table + red flags built from that RED, not imagined (no longer "provisional")
[ ] Agent complies under 3 stacked pressures (GREEN); new loopholes closed (REFACTOR)
[ ] gates.py checked: gate written if diff-visible, honest "advisory" note if not
[ ] Description = when-to-use only, no workflow summary
```

## Next Steps

- Hardened, ready to review? → `skills/writing-skill/checklist.md`
- Turns out it's a technique, no adversary? → `skills/writing-skill/evaluation.md`
- The TDD discipline this rests on → `skills/tdd.md`
- Back to the type choice → `skills/writing-skill.md`
