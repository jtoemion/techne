---
name: react-vite
description: >
  Use when implementing, debugging, reviewing, or testing a React 19 + Vite client app,
  especially with hooks, TanStack Query/React Query, Vitest/jsdom, Tailwind via Vite,
  Firebase browser boundaries, or layered frontend architecture. Even if the user says
  "frontend", "component", "hook", "Vite build", or "React app" without naming this skill.
  Not for Next.js App Router work; use nextjs.md for that.
triggers:
  - React app
  - Vite build
  - React component
  - React hook
  - Vitest jsdom
---

# React + Vite

## First Move

```
1. Confirm `vite.config.*` + React deps + no Next.js app router.
2. Read project instructions before framework defaults.
3. Preserve DAL -> Services -> Hooks -> Components/Pages boundaries.
4. Verify with the repo's full build/lint/test commands, not bare `vite build`.
```

React/Vite work fails most often from skipped TypeScript project refs, wrong layer imports, or hook dependency shortcuts.

## Verification

```
Build changed?      -> npm run build       # includes tsc -b in pastpapr
Imports/layers?     -> npm run lint        # ESLint + project checks
Behavior changed?   -> npm run test:run    # focused run first if available
UI changed?         -> npm run dev + browser verification
Package subdir?     -> use that package's own package.json commands
```

## Hook Rules

```tsx
// React Query mutation used in an effect: include the mutation object.
useEffect(() => {
  if (isOpen) resetMutation.reset();
}, [isOpen, resetMutation]);

// Intentional guard: suppress with rationale, not silence by habit.
useEffect(() => {
  if (isOpen && messages.length === 0) {
    setMessages([{ role: 'assistant', content: WELCOME_MESSAGE }]);
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [isOpen]); // intentionally omit messages: guard prevents re-init
```

## Vite Rules

```
Dynamic import      -> package must still be installed; Vite resolves import() targets
Tailwind v4         -> prefer @tailwindcss/vite when the project already uses it
Browser-only APIs   -> keep out of Node config/test setup unless guarded
Firebase clients    -> use existing mocks in tests; do not hit live Firebase
```

## Pastpapr Layer Rules

```
src/hooks/       -> no imports from src/components/, src/lib/db, src/lib/dal/
src/components/  -> no imports from src/lib/db or src/lib/dal/
src/pages/       -> no imports from src/lib/db or src/lib/dal/
src/services/    -> no imports from src/components/, src/hooks/, src/pages/
```

## Gotchas

```
- `npm run build` must include `tsc -b`; do not replace it with plain Vite.
- Root tests use jsdom; packages/league-core uses its own Node Vitest setup.
- functions/ is independent, not a root workspace package.
- Tailwind v4 is a Vite plugin here; do not add a legacy tailwind.config.js by reflex.
```

## Next Steps

- Type errors or unsafe casts? -> `skills/typescript.md`
- Building or fixing after framework orientation? -> `skills/implementer.md`
- Something is broken and root cause is unclear? -> `skills/diagnose.md`
- Next.js route, middleware, server component, or metadata work? -> `skills/nextjs.md`
