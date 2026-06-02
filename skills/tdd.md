---
name: tdd
description: Test-driven development. Vertical slices only — one test, one implementation, repeat. Use when building features or fixing bugs test-first.
---

# TDD

## The Loop

```
RED  → write ONE failing test for ONE behavior
GREEN → write minimal code to pass it
REPEAT
REFACTOR → only after all tests pass, never while RED
```

## Anti-Pattern: Horizontal Slicing

```
WRONG              RIGHT (tracer bullet)
------             -----
RED×5 then         RED→GREEN (test1→impl1)
GREEN×5            RED→GREEN (test2→impl2)
                   RED→GREEN (test3→impl3)
```

Writing all tests first produces tests for *imagined* behavior.
One test at a time responds to what you learned from the last cycle.

## Good vs Bad Test

```typescript
// GOOD — tests behavior through public interface
test('user can checkout with valid cart', async () => {
  const cart = createCart()
  cart.add(product)
  const result = await checkout(cart, paymentMethod)
  expect(result.status).toBe('confirmed')
})

// BAD — tests implementation detail
test('checkout calls paymentService.process', async () => {
  const mockPayment = jest.mock(paymentService)
  await checkout(cart, payment)
  expect(mockPayment.process).toHaveBeenCalled()  // breaks on refactor
})
```

## Red Flags

```
- Mock of internal collaborator
- Test breaks on refactor without behavior change
- Test name describes HOW not WHAT
- Private method tested directly
```

## Checklist Per Cycle

```
[ ] Test uses public interface only
[ ] Test would survive internal refactor
[ ] Code is minimal for this test only
[ ] No speculative features added
```

## Next Steps

- Unsure what interface to test against? → `skills/grill.md` first
- Bug found during TDD? → pause, go to `skills/diagnose.md`
- Tests passing, ready to ship? → conductor runs verification automatically
