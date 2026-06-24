---
name: svelte
description: Svelte 5 + SvelteKit pitfalls learned in the field — $state mutation through helpers, schema-vs-types duality in Dexie projects, dev-only route guards, dynamic imports of uninstalled modules. Load when working in a Svelte/SvelteKit project.
triggers:
  - svelte
  - sveltekit
  - "$state"
  - dexie
  - runes
---

# Svelte 5 + SvelteKit Rules

Field-tested patterns. Each one cost a debugging session — don't relearn them.

## `$state` array + helper function mutation

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

## Schema vs types duality in Dexie projects

In projects with both a public type interface (`lib/types.ts`) and a full Dexie schema (`lib/db/schema.ts`), the two will diverge. Components that call Dexie-backed DB functions must import from `schema.ts`, not `types.ts` — the schema version has the full field set including `_sync`, `stock_qty`, `bpom_number`, etc. The `types.ts` version may be a stripped public interface. Fields exist at runtime but the type won't show them.

## Dev-only route guard (SvelteKit)

For routes that should not exist in production (debug tools, cosmic graphs, etc.):

```ts
import { dev } from '$app/environment';
import { goto } from '$app/navigation';

if (!dev) goto('/');
```

Place at the very top of `<script>` in `+page.svelte`. SSR=false routes still go through Node.js build — this guard catches production builds.

## Dynamic import of uninstalled modules

When a module is dynamically imported (`await import('d3')`) and the package is not in `dependencies`/`devDependencies`, Vite fails at transform time with `Failed to resolve import`. Always verify the package is installed before using dynamic import:

```bash
pnpm add -D d3 @types/d3
```

Static `import` fails at build bundling; dynamic `import()` fails at Vite's transform plugin — both require the package to be present.

## Next Steps

- TypeScript errors? → `skills/typescript.md`
- Building a feature? → `skills/implementer.md`
- Something broken at runtime? → `skills/diagnose.md`

## RL-Proposed Additions
### [2026-06-24] GRPO skill improvement for ui
- **Source:** GRPO proposal; 2 runs observed
- **Evidence:** avg score 0.900, advantage 0.400
- **Advantage:** 0.400
- **Pattern:** High-advantage (task_type=ui, skill=svelte) pair
- **Fix:** Review and promote this pattern to the skill body if stable

### [2026-06-24] GRPO skill improvement for ui
- **Source:** GRPO proposal; 2 runs observed
- **Evidence:** avg score 0.900, advantage 0.400
- **Advantage:** 0.400
- **Pattern:** High-advantage (task_type=ui, skill=svelte) pair
- **Fix:** Review and promote this pattern to the skill body if stable

### [2026-06-24] GRPO skill improvement for ui
- **Source:** GRPO proposal; 2 runs observed
- **Evidence:** avg score 0.900, advantage 0.400
- **Advantage:** 0.400
- **Pattern:** High-advantage (task_type=ui, skill=svelte) pair
- **Fix:** Review and promote this pattern to the skill body if stable

### [2026-06-24] GRPO skill improvement for ui
- **Source:** GRPO proposal; 2 runs observed
- **Evidence:** avg score 0.900, advantage 0.400
- **Advantage:** 0.400
- **Pattern:** High-advantage (task_type=ui, skill=svelte) pair
- **Fix:** Review and promote this pattern to the skill body if stable

### [2026-06-23] GRPO skill improvement for ui
- **Source:** GRPO proposal; 2 runs observed
- **Evidence:** avg score 0.900, advantage 0.400
- **Advantage:** 0.400
- **Pattern:** High-advantage (task_type=ui, skill=svelte) pair
- **Fix:** Review and promote this pattern to the skill body if stable

### [2026-06-23] GRPO skill improvement for ui
- **Source:** GRPO proposal; 2 runs observed
- **Evidence:** avg score 0.900, advantage 0.400
- **Advantage:** 0.400
- **Pattern:** High-advantage (task_type=ui, skill=svelte) pair
- **Fix:** Review and promote this pattern to the skill body if stable

### [2026-06-23] GRPO skill improvement for ui
- **Source:** GRPO proposal; 2 runs observed
- **Evidence:** avg score 0.900, advantage 0.400
- **Advantage:** 0.400
- **Pattern:** High-advantage (task_type=ui, skill=svelte) pair
- **Fix:** Review and promote this pattern to the skill body if stable

### [2026-06-23] GRPO skill improvement for ui
- **Source:** GRPO proposal; 2 runs observed
- **Evidence:** avg score 0.900, advantage 0.400
- **Advantage:** 0.400
- **Pattern:** High-advantage (task_type=ui, skill=svelte) pair
- **Fix:** Review and promote this pattern to the skill body if stable

### [2026-06-23] GRPO skill improvement for ui
- **Source:** GRPO proposal; 2 runs observed
- **Evidence:** avg score 0.900, advantage 0.400
- **Advantage:** 0.400
- **Pattern:** High-advantage (task_type=ui, skill=svelte) pair
- **Fix:** Review and promote this pattern to the skill body if stable

### [2026-06-23] GRPO skill improvement for ui
- **Source:** GRPO proposal; 2 runs observed
- **Evidence:** avg score 0.900, advantage 0.400
- **Advantage:** 0.400
- **Pattern:** High-advantage (task_type=ui, skill=svelte) pair
- **Fix:** Review and promote this pattern to the skill body if stable

### [2026-06-23] GRPO skill improvement for ui
- **Source:** GRPO proposal; 2 runs observed
- **Evidence:** avg score 0.900, advantage 0.400
- **Advantage:** 0.400
- **Pattern:** High-advantage (task_type=ui, skill=svelte) pair
- **Fix:** Review and promote this pattern to the skill body if stable

### [2026-06-23] GRPO skill improvement for ui
- **Source:** GRPO proposal; 2 runs observed
- **Evidence:** avg score 0.900, advantage 0.400
- **Advantage:** 0.400
- **Pattern:** High-advantage (task_type=ui, skill=svelte) pair
- **Fix:** Review and promote this pattern to the skill body if stable

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
