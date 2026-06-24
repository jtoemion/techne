# CODE Node — Deep Reference

A CODE node is single-responsibility: pure IO or pure computation. Zero branching. Zero lateral imports.

## Sub-types

### DAL (Data Access Layer)
- Reads/writes one Firestore collection (or a tightly related group)
- Exports `get*`, `set*`, `add*`, `update*`, `delete*` functions
- No data transformation beyond what Firestore requires (serialization/deserialization)
- No `if/else` on user role, session state, or business status
- **VALID imports:** `firebase`, `@google-cloud/firestore`, `@react-native-firebase`, shared DAL primitives (`collection`, `doc`, `query`), constants, utils
- **INVALID:** importing another DAL file, importing a service, importing a hook

```typescript
// GOOD — single responsibility, no branching
import { collection, doc, getDoc, setDoc } from 'firebase/firestore';
import { db } from '../firebase';
import { COLLECTIONS } from '../constants';

export async function getUserProfile(uid: string): Promise<UserProfile | null> {
  const snap = await getDoc(doc(db, COLLECTIONS.USERS, uid));
  return snap.exists() ? (snap.data() as UserProfile) : null;
}
```

### Utility
- Pure functions with zero side effects
- No imports from project modules (only stdlib)
- Testable without mocks
- **Check:** can you `import { fn } from './utils'` in Node.js without a Firestore emulator? If no, it's not a utility.

```typescript
// GOOD — pure function, zero imports
export function xpCalculator(score: number, maxScore: number, timeBonus: number): number {
  const base = (score / maxScore) * 100;
  return Math.round(base + timeBonus);
}
```

### Auth Primitive
- Single auth operation (PIN validation, token management, profile fetch)
- No session orchestration (that's gateway work)
- **Check:** does it decide login method? → belongs in AuthService (gateway)

### LLM Adapter
- Wraps one LLM provider API call
- Input: structured request → Output: structured response
- No prompt engineering logic (that's a gateway)

### PDF / Report Generator
- Template → filled document → file output
- No business logic about WHAT data to include (that's a gateway decision)

## What a CODE Node MUST NOT Do

| Behavior | Example | Why it's wrong |
|----------|---------|----------------|
| Role check | `if (role === 'admin')` | Branching on auth state is gateway logic |
| Status switch | `switch (status) { case 'approved': ... }` | Business flow routing belongs in a gateway |
| Import another CODE node | `import { xpCalculator } from '../utils/xpCalculator'` inside a DAL | Data between CODE nodes flows through gateways |
| Call a service | `import { AuthService } from '../services'` inside a DAL | Services consume DAL, not the other way |
| Combine multiple Firestore collections | Both `users` and `quiz_attempts` in one DAL | Each collection gets its own DAL file |

## Testing Pattern

```typescript
// CODE nodes are the easiest to test — no mocking needed for utils
import { describe, it, expect } from 'vitest';
import { xpCalculator } from '../xpCalculator';

describe('xpCalculator', () => {
  it('returns base score for perfect run', () => {
    expect(xpCalculator(100, 100, 0)).toBe(100);
  });
});
```

For DALs, mock Firestore:
```typescript
import { vi, describe, it, expect } from 'vitest';
vi.mock('firebase/firestore');
// ... test with controlled mock returns
```

## Verification

```
[ ] Does this file do exactly one thing?
[ ] Is there any if/else/switch on role or status?
[ ] Does it import any other CODE node directly?
[ ] Can I test it without setting up 3+ mocks?
[ ] Would removing one collection break this file? (If yes, it's a DAL)
```
