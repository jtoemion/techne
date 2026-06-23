---
name: critique
description: Use when about to declare a change "good enough" without finding problems. Symptom-based: agent finishes implementation and reaches for "looks good" instead of actively critiquing.
triggers:
  - critique changes
  - analyze findings
  - run critique
---

# Critique

One line: Violating the letter violates the spirit — every change has tradeoffs. Find them.

## Lead — Finding Severity Block

```text
CRITICAL: <blocks pipeline, requires HITL resolution>
WARNING: <advances but tracked, must be addressed or explicitly deferred>
INFO: <advisory, optional to address>
```

CRITICAL blocks the pipeline. WARNING advances but gets tracked. INFO is advisory only.

## Body

```text
1. Actively seek problems. "Looks good" is not a critique.
2. Check: edge cases, error paths, API contracts, dependency side effects.
3. Check: Does this match the Honcho spec exactly? Drift?
4. Check: **YAGNI** — was every line necessary? No speculative code,
   stubs, dead code, or gold-plating.
5. Check: **TDD** — were tests written? In the right order (test first)?
   Do tests validate the actual change?
6. CRITICAL → stop, return to implementer with issues.
7. WARNING → document as deferred, continue.
8. INFO → note and continue.
```

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "This implementation looks fine" | Every change has tradeoffs. Find them or you're not done. |
| "No issues found" | Did you actively look? Name the things you checked. |
| "Everything checks out" | Checked against what? Name the criteria. |
| "It's obvious this works" | Prove it. Name the edge cases you considered. |
| "The extra code doesn't hurt" | YAGNI. Extra code is a liability — it must be maintained, tested, and understood. |
| "I'll add tests later" | TDD says now or it won't happen. Tests are part of the deliverable. |
| "It's just a stub for future use" | YAGNI. Delete the stub. Add it when you need it. |

## Red Flags — STOP

- "looks good" → stop. Find at least one tradeoff.
- "no issues found" → stop. Name what you checked.
- "everything checks out" → stop. List your criteria.
- "I added a stub for later" → stop. Delete it. YAGNI.
- "tests can come in a follow-up" → stop. TDD means now.
- "the code is minimal, no tests needed" → stop. Every change needs tests.
- Skipping critique to save time → critique IS the time. It's not optional.

## Next Steps

- Critique clean → `skills/review/SKILL.md`
- Issues found → return to `skills/implement/SKILL.md`
- Back to `skills/skill-router.yaml`
