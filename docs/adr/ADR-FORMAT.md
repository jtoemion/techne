# ADR Format

Only create an ADR when ALL THREE are true:
1. **Hard to reverse** — cost of changing later is meaningful
2. **Surprising without context** — future reader will wonder "why?"
3. **Real trade-off** — genuine alternatives existed, one was chosen

If any is missing, skip the ADR.

## File naming: `NNNN-short-slug.md`

## Template

```markdown
# ADR-NNNN: [Decision Title]

Date: YYYY-MM-DD
Status: Accepted | Superseded by ADR-XXXX

## Context

What situation forced this decision? What constraints existed?

## Decision

What was decided? One clear sentence.

## Rationale

Why this option over the alternatives? Be specific — what would have
gone wrong with the rejected options?

## Alternatives Considered

- **Option A**: why rejected
- **Option B**: why rejected

## Consequences

What becomes easier? What becomes harder?
What must future developers know because of this decision?
```
