---
name: review
description: Use when about to skip formal code review after critique pass. Symptom-based: agent says "critique already covered this" — critique and review look at different things.
triggers:
  - review code
  - run review
  - check implementation
---

# Review

One line: Violating the letter violates the spirit — critique finds bugs, review finds design violations and security issues.

## Lead — Hard Fail Gate

```text
START of review text: PASS | HARD_FAIL
Gate: HARD_FAIL only counts at START. Mid-review HARD_FAIL is informational.
```

## Body

```text
1. Security: auth, input validation, secrets, permissions.
2. Correctness: logic errors, off-by-one, null handling.
3. Skill rule compliance: does this obey implement/context-guard/verify rules?
4. Diff matches spec: no drift from HonCHO intent.
5. CRITICAL in critique → HARD_FAIL in review if unresolved.
```

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "I already reviewed this in critique" | Critique finds bugs. Review finds design and security. Different eyes. |
| "Critique covered this" | Critique is about correctness. Review is about design and compliance. |
| "The code looks fine" | Have you checked security? Input validation? Auth? Name them. |

## Red Flags — STOP

- "already reviewed" → stop. This is the review step.
- "critique covered this" → stop. Different scope. Do the review.
- Skipping review to save time → review is mandatory, not optional.

## Next Steps

- Review PASS → `skills/verify/SKILL.md`
- Review HARD_FAIL → return to `skills/implement/SKILL.md`
- Back to `skills/skill-router.yaml`
