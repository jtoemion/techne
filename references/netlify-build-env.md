# Netlify Build Environment Variables

> For the BnB/Stage project (`stage/app`), the SvelteKit frontend reads env vars at build time via `$env/static/public`. Missing vars cause a hard `[MISSING_EXPORT]` build failure.

## Required vars (all must be set in Netlify dashboard)

| Variable | Required by | Typical value |
|----------|------------|--------------|
| `PUBLIC_CONVEX_URL` | Convex client (`$env/static/public`) | `https://<deployment>.convex.cloud` |
| `PUBLIC_CONVEX_SITE_URL` | `@mmailaender/convex-better-auth-svelte` | `https://<deployment>.convex.site` |
| `VITE_BETTER_AUTH_URL` | Better Auth client (`$env/static/public`) | `https://<site>.netlify.app` |

## How to detect missing vars

The build fails with:

```
[MISSING_EXPORT] "<VAR_NAME>" is not exported by "\0virtual:env/static/public".
```

The error points to which file imports the missing var. Trace back to find which package needs it.

To audit proactively, search for `$env/static/public` imports:

```bash
grep -r "\$env/static/public" src node_modules --include="*.{ts,svelte,js}" | grep -v "node_modules/\.cache"
```

## Where to set them

**Netlify dashboard** → Site settings → Environment variables → Add variable.

Do NOT commit them to `netlify.toml` or `.env` (they contain no secrets, but the build system injects them from the dashboard).

### Env var trimming trap

Netlify env var values can accumulate trailing whitespace, backslashes, or stray characters from copy-paste. When inlined at build time by `$env/static/public`, these become part of the JS string literal, causing errors like `Invalid deployment address: "https://x.convex.cloud \""`.

**If the user says they cleaned the env var but the error persists**, the value in the DEPLOYED BUILD is baked in — a rebuild with the clean value is required. Verify the actual inlined value in the deployed HTML:

```bash
curl -s https://your-site.netlify.app | grep -o 'PUBLIC_CONVEX_URL":"[^"]*"'
```

If trimming is impossible (user can't get the env var clean), add a runtime fallback in the consuming code:

```ts
const url = (raw ?? '').replace(/[\s"']+$/g, '').trim();
```

This should be a last resort — the real fix is cleaning the env var and rebuilding.

## Node version

Set `NODE_VERSION` in `netlify.toml` `[build.environment]` to match the highest `engines.node` requirement across all npm packages:

```toml
[build]
  command = "NODE_ENV=production npm run build"
  publish = ".svelte-kit/output"

[build.environment]
  NODE_VERSION = "22"
```

**`NODE_ENV=production` is required in the build command.** Without it, the SvelteKit server may inject the Vite HMR client import (`import('/@vite/client')`) into the production HTML, which causes a blank page when the dynamic import fails. This happens even with `vite build` (which should default to production mode) because the `esm-env` package checks `process.env.NODE_ENV` at module load time. Explicitly setting it in the build command ensures the correct mode. The `import('/@vite/client')` artifact blocks hydration because it's part of the `Promise.all()` bootstrap — if the Vite client import fails, the entire `Promise.all` rejects and the app never starts.

If too low, `npm install` fails with:

```
npm error code EBADENGINE
npm error engine Unsupported engine
npm error notsup Required: {"node":"22 || >=24.0.0"}
npm error notsup Actual:   {"npm":"10.8.2","node":"v20.20.2"}
```

To find the highest engine requirement:

```bash
grep -r '"node"' package.json 2>/dev/null
```

## Branch configuration

Netlify builds from a specific branch (default: `master`). If that branch doesn't exist on the remote:

```
Failed during stage 'preparing repo': git ref refs/heads/master does not exist
```

Fix: either create the branch from your deploy-ready HEAD or update Netlify → Site settings → Build & deploy → Branches → Production branch.

**Important**: Netlify's configured production branch may differ from your active dev branch. For BnB/Stage, Netlify builds from `master` while active development is on `bnb/stage-hardening`. After merging fixes to the dev branch, they must also be merged to whatever branch Netlify actually deploys. Check by looking at the deployed HTML artifact hash (e.g. `sveltekit_10o5j3q`) and comparing with local builds.

## Root vs subdirectory netlify.toml

If your repo has a `netlify.toml` at the project root AND a nested one (e.g. `stage/app/netlify.toml`), the **root-level one takes precedence** for all settings. Netlify reads `netlify.toml` from the repo root; a nested file in the `base` directory is NOT merged or consulted.

For BnB/Stage, this means:
- Root `netlify.toml` controls `NODE_VERSION`, `publish`, and `command`
- The nested `stage/app/netlify.toml` is effectively ignored by Netlify
- Both must be kept in sync — the root file is the source of truth

## Detecting old/debug builds on Netlify

If the deployed page is blank, check the rendered HTML for dev-only artifacts:

```bash
# Check for Vite HMR client import (should NOT be in production)
curl -s https://your-site.netlify.app | grep -c '/@vite/client'
# Returns 1 → dev/build artifact present → wrong build mode or missing NODE_ENV=production

# Check for CSP nonce headers
curl -sI https://your-site.netlify.app | grep -c 'content-security-policy'
# Returns 0 → hooks.server.ts CSP fix not deployed

# Check for nonce on script tag
curl -s https://your-site.netlify.app | grep -c 'nonce='
# Returns 0 → transformPageChunk not working or fix not deployed

# Check CSP connect-src includes wss://*.convex.cloud (needed for Convex WebSocket sync)
curl -sI https://your-site.netlify.app | grep -o 'connect-src[^;]*'
# Must include: wss://*.convex.cloud — if missing, Convex realtime sync is blocked

# Compare HTML hash (cache-busting string) between builds
curl -s https://your-site.netlify.app | grep -o 'sveltekit_[a-z0-9]*'
# Same hash = same build, even if you pushed
```

Combined diagnosis for blank page on Netlify:
| HTML artifact | CSP headers | Root cause |
|---|---|---|
| `@vite/client` present | Present, with nonce | Old dev build deployed to branch that HAS CSP fix. Fix deployed but build was in dev mode. Deploy production build. |
| `@vite/client` absent | Missing | Old production build from branch that lacks hooks.server.ts CSP fix. Merge fixes to Netlify's build branch. |
| `@vite/client` absent | Present, with nonce | CSP fix IS deployed but script tag has no nonce (transformPageChunk regex not matching). Check regex against actual HTML. |

## Build output verification

Successful Netlify build should show:

```
> Using @sveltejs/adapter-netlify
  ✔ done
```

And produce:

```
.netlify/functions-internal/sveltekit-render.json
.netlify/functions-internal/sveltekit-render.mjs
```

If it says `No adapter specified`, the adapter is being ignored (see `references/vite8-adapter-trap.md`).
