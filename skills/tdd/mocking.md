---
name: tdd/mocking
description: When to mock and when not to. Load this when a test requires isolating a dependency — before reaching for jest.mock() or unittest.mock.
---

# Mocking

## The Core Rule

Mock **external** things. Never mock **internal** things.

```
MOCK:                         DON'T MOCK:
  Third-party APIs              Internal functions
  Databases (in unit tests)     Private methods
  File system (in unit tests)   Collaborators you own
  Time (Date.now, datetime)     Implementation details
  Random number generators
  External services (email, SMS)
```

## Decision Tree

```
Is the dependency external to your codebase?
  YES → mock it
  NO  → is the test slow without mocking? (>1s per test)
    YES → consider a fake (not a mock — see below)
    NO  → don't mock, test through the real thing
```

## Mock vs Fake vs Stub

```
MOCK    → verifies interactions ("was this called?")
          Use rarely — couples test to implementation

FAKE    → real behavior, simplified implementation
          e.g. in-memory database instead of Postgres
          Use for: slow deps you own (DB, file system)

STUB    → returns fixed values, no verification
          e.g. fetch() that always returns { status: 200 }
          Use for: external APIs, time, randomness
```

## Time Mocking (common case)

```typescript
// Jest
jest.useFakeTimers()
jest.setSystemTime(new Date('2026-01-01'))

// Python
from unittest.mock import patch
with patch('module.datetime') as mock_dt:
    mock_dt.now.return_value = datetime(2026, 1, 1)
```

## When a Mock Smells Wrong

```
Red flags:
  - You're mocking something you wrote
  - The mock setup is longer than the test
  - Changing internal structure breaks the mock
  - You're asserting on call order or argument details

Fix: redesign the interface so the test doesn't need the mock.
The need to mock internal things is a seam design problem.
```

## Next Steps

- Mock making test fragile? → `skills/tdd/interface.md`
- Testing async code? → back to `skills/tdd.md`
- External API returning inconsistent data? → `skills/diagnose/feedback-loop.md` (strategy 5: trace replay)
