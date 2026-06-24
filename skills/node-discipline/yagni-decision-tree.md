# YAGNI Decision Tree — When to Split vs When to Hold

The most expensive mistake in node isolation is premature decomposition — splitting a module into 3 files before there's evidence that 3 files are needed.

## The Decision Tree

```
Start: "Should I split this module into separate nodes?"
  │
  ├── Does it have ≥2 consumers with different needs?
  │     NO  → Keep as-is. Mark as "future candidate" in a comment.
  │     YES → Continue.
  │
  ├── Is the branching/merging logic changing independently of the consumer?
  │     NO  → Keep embedded. Extraction pays off when the logic
  │            changes without touching the consumer.
  │     YES → Continue.
  │
  ├── Does the current module have tests?
  │     NO  → Write tests FIRST. Extract AFTER.
  │     YES → Continue.
  │
  ├── Does the split reduce the total number of import lines?
  │     NO  → Three files with one import each is harder to read
  │            than one file with three functions.
  │     YES → Continue (split is justified).
  │
  └── Result: SPLIT is justified. Proceed.
```

## Cost of Premature Split

Three hooks (`useSpacedReviewRaw` → `useSpacedReviewResolved` → `useSpacedReviewItems`) instead of one:

| Cost | Detail |
|------|--------|
| **3× cache entries** | React Query now manages 3 separate cache keys |
| **3× loading states** | Each sub-hook has `isLoading`, `isError`, `data` |
| **3× error boundaries** | Three places something can break independently |
| **3× mock setups in tests** | Three times the test boilerplate |
| **Mental model cost** | "Which hook returns what?" |

For a module with ONE consumer and simple logic: this is pure overhead.

## When Splitting IS Worth It

### Case 1: Multi-source dashboard (MERGE justified)

**`useTutorDashboard`** — 374 lines, 8 parallel queries, ~10 KPIs.
Keep the merge in a thin parent hook, but make each data source a separate hook:

- `useTutorStudents()` — single query, one error boundary
- `useTutorSessions()` — single query, one error boundary
- `useTutorDashboard()` — merges the above

**Why this passes YAGNI:** Each sub-hook can be independently tested, cached, and reused in other views. The student list is useful in other pages; the session list is useful in other pages. The merge is unique to the dashboard.

### Case 2: Role-based query branching (IF justified)

**`sessionService.getAllSessions`** — routes to different Firestore queries based on role.
Extract `buildSessionQuery(role)` as a pure function.

**Why this passes YAGNI:** The query-building logic is independently testable without Firestore mocks. The gateway facade stays thin.

### Case 3: Dual path with different data shapes (SET justified)

**`QuizService.submitAttempt`** — writes to `quiz_attempts` AND `student_activities`.
The two writes have different shapes and error handling needs. A dual-write MERGE is fine; splitting the data shaping into two SET steps is justified if the shapes diverge further.

## Patterns That Look Like Splits But Aren't

| Looks like | Reality |
|-----------|---------|
| "Extract `useAuth` role booleans to `authGateway.ts`" | One consumer (`useAuth`), 3 lines of `role === 'student'`. This is code relocation, not a gateway. `useAuth` IS the gateway. |
| "Extract `AuthContext` retry loop to `sessionGateway.ts`" | One consumer (AuthContext), tightly coupled to React lifecycle. Extraction adds indirection without clarity. |
| "Split `getClassReport` into 3 functions" | One consumer, well-documented merge. Add tests instead of splitting. |

## YAGNI Review Checklist

Before merging any PR that creates a new node file:

```
[ ] Does the new node have ≥1 consumer RIGHT NOW?
[ ] Is the consumer in the same PR? (If no, the file should not exist)
[ ] Could this logic live as a private function in the consumer?
[ ] Does the split reduce LOC in the consumer by ≥20%?
[ ] Would you feel bad deleting this node next week if the consumer changes?
```

If the answer to the last question is "no" or "not really", the node is premature.
