---
name: react
description: React 19 + Vite pitfalls learned in the field — useEffect dependency rules with React Query mutations, and when to suppress exhaustive-deps with a documented guard. Load when working in a React/Vite project (e.g. pastpapr).
triggers:
  - react
  - vite
  - useeffect
  - react query
  - exhaustive-deps
---

# React 19 + Vite Rules

Field-tested patterns from React 19 + Vite projects (pastpapr). The Next.js gates in `skills/nextjs.md` do **not** apply here — routing and middleware conventions differ.

## `useEffect` with React Query mutations — add the mutation object to deps

```tsx
// Wrong — ESLint will flag missing resetMutation
useEffect(() => {
  if (isOpen) {
    resetMutation.reset();
  }
}, [isOpen]);

// Correct
useEffect(() => {
  if (isOpen) {
    resetMutation.reset();
  }
}, [isOpen, resetMutation]);
```

**Why:** React Query's `useMutation()` returns a new object reference every render. A closure that omits it from deps captures a stale ref. The effect fires on `isOpen` change, but if the mutation object itself changes between renders (it will), the effect may not see the latest state. Always include mutation objects in effect deps.

## `useEffect` with intentional guard — use eslint-disable with rationale

```tsx
// Wrong — warning fires even though the guard is intentional
useEffect(() => {
  if (isOpen && messages.length === 0) {
    setMessages([{ role: 'assistant', content: WELCOME_MESSAGE }]);
  }
}, [isOpen]);

// Correct — suppress with inline disable + reason
useEffect(() => {
  if (isOpen && messages.length === 0) {
    setMessages([{ role: 'assistant', content: WELCOME_MESSAGE }]);
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [isOpen]); // intentionally omit messages — guard by length check prevents re-init
```

**Why:** Adding `messages` to deps would cause the effect to re-run every time `messages` changes, defeating the `length === 0` guard. The lint warning is technically correct but the guard is intentional — suppress with comment so future agents understand the intent.

## Next Steps

- TypeScript errors? → `skills/typescript.md`
- Building a feature? → `skills/implementer.md`
- Why the Next.js gates don't apply → see scope note in `SKILL.md`

## RL-Proposed Additions

<!-- New RL-generated entries appear here. Reviewed and confirmed
     before being promoted to the main body above. -->

<!-- Entry template:
### [YYYY-MM-DD] Pitfall title
- **Source:** GRPO proposal from task <task_id>
- **Evidence:** Review finding repeated N times across M tasks
- **Advantage:** X.XXX
- **Pattern:** Description of the pitfall
- **Fix:** How to avoid it
- **Example:** Code snippet showing wrong vs correct
-->
