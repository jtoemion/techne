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
4. Check: Are there tradeoffs? Name them explicitly.
5. CRITICAL → stop, return to implementer with issues.
6. WARNING → document as deferred, continue.
7. INFO → note and continue.
```

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "This implementation looks fine" | Every change has tradeoffs. Find them or you're not done. |
| "No issues found" | Did you actively look? Name the things you checked. |
| "Everything checks out" | Checked against what? Name the criteria. |
| "It's obvious this works" | Prove it. Name the edge cases you considered. |

## Red Flags — STOP

- "looks good" → stop. Find at least one tradeoff.
- "no issues found" → stop. Name what you checked.
- "everything checks out" → stop. List your criteria.
- Skipping critique to save time → critique IS the time. It's not optional.

## Next Steps

- Critique clean → `skills/review/SKILL.md`
- Issues found → return to `skills/implement/SKILL.md`
- Back to `skills/skill-router.yaml`
