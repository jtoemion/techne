# Svelte Loading States & Skeleton Loaders

Two data-loading patterns in SvelteKit, each needing a different skeleton strategy.

## Pattern 1: `onMount` fetch (explicit loading state)

```svelte
<script lang="ts">
  let loading = $state(true);
  let data = $state([]);

  onMount(async () => {
    try {
      data = await fetchData();
    } finally {
      loading = false;
    }
  });
</script>

{#if loading}
  <SkeletonCard />
{:else}
  {#each data as item}
    <Card {item} />
  {/each}
{/if}
```

Key: `loading = false` MUST be in `finally` or after the try/catch — not just in the success path.

## Pattern 2: Convex `useQuery` (reactive null check)

```svelte
<script lang="ts">
  import { useQuery } from 'convex-svelte';
  const result = useQuery(api.views.myQuery, {});
</script>

{#if $result}
  <Content data={$result} />
{:else}
  <SkeletonCard />
{/if}
```

Key: `useQuery` returns a store — `$result` is `undefined` while loading. No explicit loading state needed.

## Skeleton component pattern

CSS-only shimmer animation, no JS runtime cost:

```svelte
<!-- Skeleton.svelte -->
<div class="skeleton" style="width:{width}; height:{height}; border-radius:{radius}"></div>

<style>
  .skeleton {
    background: linear-gradient(90deg, var(--ink-100, #e5e5e5) 25%, var(--ink-50, #f0f0f0) 50%, var(--ink-100, #e5e5e5) 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
  }
  @keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
  @media (prefers-reduced-motion: reduce) { .skeleton { animation: none; } }
</style>
```

Use `var(--token, fallback)` for theme compatibility. Always include `prefers-reduced-motion` guard.

## Common mistakes

1. **Forgetting `finally`**: If `loading = false` is only in the success path, errors leave the skeleton stuck on screen.
2. **Using `loading` with Convex `useQuery`**: Unnecessary — the query's undefined state IS the loading indicator. Adding a separate `loading` variable creates a race condition.
3. **Missing `prefers-reduced-motion`**: Accessibility violation. Users with motion sensitivity see endless shimmer.
4. **Missing ARIA attributes on skeleton containers**: Screen readers can't announce loading state. Every skeleton container must have `role="status"`, `aria-busy="true"`, and a descriptive `aria-label`:
   ```svelte
   <div class="skeleton-grid" role="status" aria-busy="true" aria-label="Loading dashboard data">
     <SkeletonCard lines={5} />
   </div>
   ```
