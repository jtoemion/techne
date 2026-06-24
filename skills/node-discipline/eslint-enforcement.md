# ESLint Enforcement — Node-Discipline Import Rules

The most reliable way to enforce node discipline is at CI via ESLint's `no-restricted-imports`.
This file documents the exact config snippets per project type.

## React 19 + Vite (student-portal)

The target codebase already has *some* import restrictions in `eslint.config.js` but the hook→DAL rule is missing. Here's the complete set:

```js
// eslint.config.js — add to the rules array

// Prevent hooks from importing DAL/db directly (MISSING — see §5e)
{
  files: ['src/hooks/**/*.ts', 'src/hooks/**/*.tsx'],
  rules: {
    'no-restricted-imports': ['error', {
      patterns: [
        { group: ['../lib/db*', '../lib/dal*', '../../lib/db*', '../../lib/dal*'],
          message: 'Hooks must not import from DAL or db. Route through services layer.' },
      ],
    }],
  },
},

// Prevent components/pages from importing DAL/db (already exists)
{
  files: ['src/components/**/*.ts', 'src/components/**/*.tsx',
           'src/pages/**/*.ts', 'src/pages/**/*.tsx'],
  rules: {
    'no-restricted-imports': ['error', {
      patterns: [
        { group: ['../lib/db*', '../lib/dal*'],
          message: 'Components must not import from DAL or db. Route through services/hooks layer.' },
      ],
    }],
  },
},

// Prevent services from importing components/hooks/pages (exists)
{
  files: ['src/services/**/*.ts'],
  rules: {
    'no-restricted-imports': ['error', {
      patterns: [
        { group: ['../components/**', '../hooks/**', '../pages/**'],
          message: 'Services must not import from components, hooks, or pages.' },
      ],
    }],
  },
},

// Optional: Prevent DAL→DAL imports (defense in depth)
{
  files: ['src/lib/dal/**/*.ts'],
  rules: {
    'no-restricted-imports': ['warn', {
      patterns: [
        { group: ['../dal/**', './*DAL'],
          message: 'DAL files should not import other DAL files. Use the services layer.' },
      ],
    }],
  },
},
```

## Insertion point

Find the existing `no-restricted-imports` rules in `eslint.config.js` and add the hooks block:

- If the file uses the array-of-config-objects format → add the hooks object to the array
- If it uses the flat config format → add the hooks config block before the ignores

## Next.js (server components)

```js
// Next.js: prevent server components from importing client-only modules
{
  files: ['src/app/**/*.ts', 'src/app/**/*.tsx'],
  rules: {
    'no-restricted-imports': ['error', {
      patterns: [
        { group: ['../components/client/**', '../hooks/**'],
          message: 'Server components must not import client-only modules.' },
      ],
    }],
  },
},
```

## Testing the rule

After adding, verify:

```bash
# Should fail: hook importing DAL
echo "import { getUserAttempts } from '../lib/dal';" > /tmp/test-violation.ts
npx eslint /tmp/test-violation.ts
# Expected: error — Hooks must not import from DAL or db

# Should pass: hook importing service
echo "import { getUserAttempts } from '../services';" > /tmp/test-pass.ts
npx eslint /tmp/test-pass.ts
# Expected: no errors
```
