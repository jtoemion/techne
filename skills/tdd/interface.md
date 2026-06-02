---
name: tdd/interface
description: Designing interfaces that are testable and deep. Load this when you're not sure what to test against, or when tests keep breaking on refactors.
---

# Interface Design for Testability

## The Core Principle

The interface is the test surface.
A good interface makes good tests automatic.
A bad interface makes tests either impossible or fragile.

## Deep vs Shallow Modules

```
DEEP (good):
  ┌─────────────┐
  │ small API   │  ← few methods, simple params
  ├─────────────┤
  │             │
  │  lots of    │  ← complex logic hidden inside
  │  behavior   │
  └─────────────┘

SHALLOW (bad):
  ┌─────────────────────────┐
  │  large, complex API     │  ← many params, many methods
  ├─────────────────────────┤
  │  thin implementation    │  ← just passes through
  └─────────────────────────┘
```

**Deletion test**: If you deleted the module, would complexity vanish (pass-through) or reappear across N callers (earning its keep)? Only keep it if it earns its keep.

## Signs Your Interface Needs Redesign

```
Tests mock your own code         → seam is in the wrong place
Tests break on refactor          → testing implementation, not behavior
Setup takes longer than the test → interface is too wide
You need to test private methods → they should be behind a deeper interface
10 parameters to construct       → split or use a config object
```

## Design Moves

```
1. HIDE THE DETAIL
   Move complex logic behind a simpler method name.
   Callers don't need to know how — just what.

2. RAISE THE SEAM
   If a seam exists at unit level but the bug lives at integration level,
   raise the seam. One seam at the right level beats five seams at wrong levels.

3. CONFIG OBJECT
   Replace N boolean params with a typed config object.
   Easier to test, easier to extend without breaking callers.

4. SEPARATE PURE FROM EFFECTFUL
   Pure functions (no I/O) are trivially testable.
   Isolate I/O at the edges. Test the pure core.

5. ONE ADAPTER RULE
   One adapter = hypothetical seam (maybe useful)
   Two adapters = real seam (worth the abstraction)
   Don't abstract until you have two concrete implementations.
```

## Example Refactor

```typescript
// BEFORE: shallow, hard to test
class OrderProcessor {
  processOrder(id, userId, items, coupon, shippingMethod, priority, notify) { ... }
}

// AFTER: deep, easy to test
class OrderProcessor {
  process(order: Order): ProcessResult { ... }
}
// Order is a typed value object — easy to construct in tests
// ProcessResult is assertable without mocking internals
```

## Next Steps

- Interface looks right but test still brittle? → `skills/tdd/mocking.md`
- Unsure where the seam should be? → `skills/grill.md` (stress-test the design)
- Ready to write tests? → back to `skills/tdd.md`
