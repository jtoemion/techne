# Student Portal Architecture

**pastpapr/student-portal** — React 19 SPA, Vite, Tailwind CSS v4, Firebase backend.

## Layering (enforced by ESLint import rules)

```
Components/Pages  →  Hooks  →  Services  →  DAL
   (UI)             (state)    (logic)     (data)
```

Each layer may only import from the layer directly below it (or transitively
below). Never import upward.

### Layer responsibilities

| Layer | Job | Can import |
|-------|-----|-----------|
| DAL | Firestore queries, raw data access | (nothing beyond shared types) |
| Services | Validation, orchestration, business rules | DAL only |
| Hooks | React state, React Query wrappers | Services (transitively DAL) |
| Components/Pages | JSX rendering, layout | Hooks (transitively Services/DAL) |

### Rule: composition over inheritance

Always compose, never extend.

```typescript
// ❌ Inheritance — don't
class SessionService extends SessionDAL { ... }

// ✅ Composition — do
class SessionService {
  constructor(private dal: SessionDAL) {}
  // or simply: import { getSessions } from '../dal/sessionDAL'
}
```

A Service has a DAL (composition), not is a specialised DAL (inheritance).
This keeps layers decoupled, independently testable, and swappable. React's own
design guidance says the same — compose, don't extend.

### Shallow module detection

Apply the deletion test: if deleting a module removes complexity without
reappearing across N callers, it's a pass-through — inline or delete it.

**Real example:** `src/config/featureFlags.ts` was a 6-line re-export barrel
(just re-exporting from `lib/featureFlags.ts`). Zero importers. Deleted with
zero side effects. All callers already imported directly from `lib/featureFlags`.

### Note on barrel files

Standard barrel files (`src/lib/dal/index.ts`, `src/services/index.ts`,
`src/hooks/index.ts`) are acceptable at established boundaries — they provide
a stable import surface. The danger is redundant pass-through barrels at the
same depth (e.g. `config/` re-exporting `lib/`).

## Related

- `CONTEXT.md` in the repo — domain vocabulary for the student portal
- `docs/adr/` — architecture decision records for this project
- `AGENTS.md` at project root — build commands and quick reference
