---
name: nextjs
description: Next.js App Router rules. Hard gates reject diffs that violate these. Loaded automatically for every task.
---

# Next.js Rules

## Hard Gates (diff rejected on violation)

```
# weight: high | gate: yes
redirect()        → only in middleware.ts, nowhere else
next/router       → never. Use next/navigation
getServerSideProps → removed. Use async server components
@ts-ignore        → never. Fix the type
console.log       → never in production paths (+ lines only)
```

## Soft Rules (no gate, but retro flags violations)

```
# weight: medium
metadata export   → only from page.tsx or layout.tsx, not client components
next/image        → remote domains must be in next.config.js remotePatterns
params (Next 15)  → await params before destructuring: const { slug } = await params
```

## Quick Patterns

```typescript
// redirect: middleware.ts ONLY
export function middleware(req: NextRequest) {
  if (!req.cookies.get('token')) return NextResponse.redirect(new URL('/login', req.url))
}

// router: next/navigation, never next/router
import { useRouter } from 'next/navigation'

// params: await before destructuring (Next 15)
export default async function Page({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
}
```

## Next Steps

- Gate firing on redirect? → check you're in `middleware.ts`
- Router import error? → replace `next/router` with `next/navigation`
- TypeScript errors? → `skills/typescript.md`
