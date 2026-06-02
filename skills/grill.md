---
name: grill
description: Stress-test a plan against the actual codebase before writing code. One question at a time. Use when design is uncertain or the approach could conflict with existing patterns.
---

# Grill

## When to Use

```
- Design touches more than 2 files
- Unsure how something fits the existing data model
- Approach seems right but hasn't been verified against code
- User says "think about this first" or "am I approaching this right?"
```

## Process

Ask ONE question, wait for answer, then ask the next.

```
1. Read the relevant code first — answer from code before asking
2. Challenge terminology: "codebase calls this X, you said Y — which?"
3. Stress-test with edge cases: "what happens when the list is empty?"
4. Cross-reference: "your code does X, but you said Y — which is right?"
5. Lock decisions before moving to implementation
```

## Questions That Always Matter

```
- What is the public interface? (not the implementation)
- Which behaviors are most important to test?
- What existing code does this touch?
- What breaks if this changes?
- What's out of scope?
```

## Output

At the end of grilling, you have:
- Locked interface design
- Known edge cases
- Clear scope boundary
- No ambiguous terms

## Next Steps

- Design locked? → `skills/implementer.md`
- Writing tests for the locked interface? → `skills/tdd.md`
- Something already broken? → `skills/diagnose.md` (don't grill a bug)
