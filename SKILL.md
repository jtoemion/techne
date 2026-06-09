---
name: techne
description: Harness engineering entry point. Routes to the right sub-skill based on what you're doing. Always read this first — never browse skills/ directly.
---

# Techne — Skill Router

## Quick Route

| You're doing... | Load this |
|---|---|
| Building a feature or fix | `skills/implementer.md` |
| Something is broken | `skills/diagnose.md` |
| Writing tests first | `skills/tdd.md` |
| Stress-testing a plan | `skills/grill.md` |
| Discovering what to build | `skills/persona-brainstorm.md` |
| Prototyping a design question | `skills/prototype.md` |
| Finding refactor/architecture wins | `skills/improve-architecture.md` |
| Checking a pull request (one pass) | `skills/check-pr.md` |
| Iterating a PR to a perfect review | `skills/greploop.md` |
| Writing a new skill | `skills/writing-skill.md` |
| UI design decisions | `skills/ui-grill.md` |
| Prompting LLM for UI | `skills/ui-craft.md` |
| UI specificity standard | `skills/ui-physics.md` |
| Design-to-dev handoff | `skills/ui-handoff.md` |
| Reviewing agent output | `skills/evaluation.md` |
| Next.js specific rules | `skills/nextjs.md` |
| TypeScript type errors | `skills/typescript.md` |
| Svelte/SvelteKit work | `skills/svelte.md` |

## Live Framework Findings

### React 19 + Vite (pastpapr patterns)

#### `useEffect` with React Query mutations — add the mutation object to deps

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

#### `useEffect` with intentional guard — use eslint-disable with rationale

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

### Svelte 5 + IndexedDB

#### `$state` array + helper function mutation

When you pass a `$state` array to a helper that mutates it (e.g. `removeTag` or `addTag`), the helper must receive the updater function, not the array directly:

```ts
// Broken — mutation doesn't propagate to $state
function removeTag(tags: string[], index: number) {
  tags.splice(index, 1); // mutates local copy, not the $state
}

// Correct — functional update form
function removeTag(tags: string[], index: number, setTags: (t: string[]) => void) {
  const updated = [...tags];
  updated.splice(index, 1);
  setTags(updated); // e.g. (t) => myTags = t
}

// In component:
<button onclick={() => removeTag(myTags, i, (t) => myTags = t)}>×</button>
```

#### Schema vs types duality in Dexie projects

In projects with both a public type interface (`lib/types.ts`) and a full Dexie schema (`lib/db/schema.ts`), the two will diverge. Components that call Dexie-backed DB functions must import from `schema.ts`, not `types.ts` — the schema version has the full field set including `_sync`, `stock_qty`, `bpom_number`, etc. The `types.ts` version may be a stripped public interface. Fields exist at runtime but the type won't show them.

#### Dev-only route guard (SvelteKit)

For routes that should not exist in production (debug tools, cosmic graphs, etc.):

```ts
import { dev } from '$app/environment';
import { goto } from '$app/navigation';

if (!dev) goto('/');
```

Place at the very top of `<script>` in `+page.svelte`. SSR=false routes still go through Node.js build — this guard catches production builds.

#### Dynamic import of uninstalled modules

When a module is dynamically imported (`await import('d3')`) and the package is not in `dependencies`/`devDependencies`, Vite fails at transform time with `Failed to resolve import`. Always verify the package is installed before using dynamic import:

```bash
pnpm add -D d3 @types/d3
```

Static `import` fails at build bundling; dynamic `import()` fails at Vite's transform plugin — both require the package to be present.

## Always Loaded

These are injected for every task — do not skip:

- `skills/nextjs.md` — hard gates that will reject your diff (Next.js projects only)
- `skills/typescript.md` — hard gates that will reject your diff

**Scope note:** Techne's gates (`gate_no_redirect_outside_middleware`, `gate_no_router_import`, etc.) and its pipeline phases (IMPLEMENT → VERIFY → REVIEW → RETRO → EVALUATE) are designed for **Next.js full-stack projects**. For React 19 + Vite projects (e.g., pastpapr), the routing and middleware conventions don't apply. Load the skill for its sub-skill routing and ESLint/TypeScript pitfall references, but skip the Next.js-specific gate logic.

## Pipeline Phases

```
IMPLEMENT → VERIFY → REVIEW → RETRO → EVALUATE
```

Each phase is a separate agent. Only the conductor advances phases.
Gates run in Python — agents cannot self-report a pass.

**After every phase: call `p.get_status()` — display the output.**
Shows phase results, checkpoint summary, and live eval preview (scores per dimension + total + trend). This is mandatory every time the pipeline is used.

## Next Steps

- Building something? → `skills/implementer.md`
- Debugging? → `skills/diagnose.md`
- Not sure what to do first? → `skills/grill.md`
- Post-build bug analysis? → `references/bug-analysis-soaperfume.md` (live case study — 13 bugs, H-1 through L-4, with fix patterns)
- SvelteKit deployment issues? → `references/bug-analysis-soaperfume.md` (adapter-hosting mismatch, idempotent migrations, auth guards)
- Bug triage quick-ref? → `references/bug-analysis-soaperfume.md` (symptom → cause table for common SvelteKit/SQLite patterns)
- Replicating an existing UI (vanilla HTML prototype → framework code)? → `references/ui-replication-from-reference.md` (audit-then-extract workflow, atom layer first, token-exact matching)
- Hook-gate bridge (Hermes pre_tool_call → Techne gates.py)? → `references/hook-gate-bridge.md` (plan + architecture for inline gate enforcement via plugin hook)
- Writing a new skill? → `superpowers/writing-skills/SKILL.md` (TDD for documentation — RED-GREEN-REFACTOR applied to process docs)
- UI design decisions? → `superpowers/frontend-avant-garde/SKILL.md` (Senior Frontend Architect — opinionated, output-first)
- Svelte project work? → `skills/svelte.md` (gap-at-bottom fix, $state patterns, dev-only route guard)
