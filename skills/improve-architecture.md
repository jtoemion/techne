---
name: improve-architecture
description: Find deepening opportunities — refactors that turn shallow modules into deep ones, for testability and AI-navigability. Informed by CONTEXT.md domain language and docs/adr decisions. Use to improve architecture, find refactoring opportunities, or consolidate tightly-coupled modules.
triggers:
  - improve architecture
  - refactoring opportunities
  - deepen the module
  - more testable
  - consolidate coupling
  - architecture review
---

# Improve Architecture

> Adapted from mattpocock/skills. Pairs with the code-structure service-layer pattern.

## The One Rule

**Make shallow modules deep.** A deep module hides a lot of behavior behind a
small interface (high leverage). A shallow one has an interface nearly as complex
as its implementation — it earns nothing. Hunt the shallow ones.

## Glossary (use these words exactly)

```
Module        anything with an interface + an implementation
Interface     everything a caller must know: types, invariants, error modes, ordering
Depth         leverage at the interface. Deep = lots behind a little. Shallow = the opposite
Seam          where an interface lives — alter behavior without editing in place
Deletion test imagine deleting the module. Complexity vanishes → it was a pass-through.
              Complexity reappears across N callers → it was earning its keep.
```

The interface is the test surface. One adapter = a hypothetical seam; two
adapters = a real one.

## Process

```
1. EXPLORE    read CONTEXT.md + docs/adr first, then walk the code. Note friction:
              - understanding one concept means bouncing between many small modules
              - shallow modules (interface ~ implementation complexity)
              - pure functions extracted only for testability, bugs hide in the calls
              - tightly-coupled modules leaking across seams
2. CANDIDATES for each: Files | Problem | Solution | Benefit (locality+leverage) |
              Before/After | Strength (Strong | Worth exploring | Speculative)
              Apply the deletion test to anything you suspect is shallow.
3. PICK ONE   present candidates, ask which to pursue. Do NOT design interfaces yet.
4. GRILL      drop into skills/grill.md on the chosen one — constraints, the shape
              of the deepened module, what sits behind the seam, which tests survive.
```

## Inline side effects (as decisions crystallize)

```
New module named after a concept not in CONTEXT.md  → add the term to CONTEXT.md
Sharpened a fuzzy term while grilling               → update CONTEXT.md there
User rejects a candidate with a load-bearing reason → offer an ADR (docs/adr/)
Candidate contradicts an existing ADR               → only raise it if friction is real;
                                                       mark it "contradicts ADR-NNNN — but…"
```

Use CONTEXT.md vocabulary for the domain ("the Order intake module", not
"FooBarHandler"). Don't re-litigate decided ADRs.

## Next Steps

- Picked a candidate, ready to pressure-test it? → `skills/grill.md`
- Design locked, ready to refactor? → `skills/implementer.md` (minimal diffs, gates apply)
- Recording why a refactor was chosen or rejected? → `docs/adr/ADR-FORMAT.md`
- Don't know which problem matters most yet? → `skills/persona-brainstorm.md`
