---
name: typescript
description: TypeScript rules. Hard gates reject diffs with suppressions. Loaded automatically for every task.
---

# TypeScript Rules

## Hard Gates (diff rejected on violation)

```
# weight: high | gate: yes
@ts-ignore   → never. Fix the type error instead
@ts-nocheck  → never
```

## Soft Rules (no gate)

```
# weight: medium
as any        → avoid. Use unknown + type narrowing
             → exception: third-party lib interop, add comment explaining why
async params  → await params before destructuring (Next.js 15+)
arr?.[0]      → use optional chaining before index when value may be undefined
```

## Quick Patterns

```typescript
// unknown + narrowing (instead of any)
function process(input: unknown) {
  if (typeof input === 'string') return input.toUpperCase()
  throw new Error('Expected string')
}

// optional chaining
const first = items?.[0]        // safe
const name = user?.profile?.name // safe

// type assertion with comment (last resort)
const config = rawData as Config  // third-party API, no types available
```

## Next Steps

- Type errors from Next.js params? → `skills/nextjs.md` (params section)
- Test types broken? → `skills/tdd.md` (interface-based testing)
