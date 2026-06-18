---
name: diagnose-netlify
description: Netlify-specific debugging patterns — redirect/rewrite precedence, function cold-starts and timeouts, env-var scoping between build and runtime, and SPA-fallback traps. Loaded automatically when stack_detect finds netlify in the project. Use when a bug appears only on the deployed Netlify site, not locally.
triggers:
  - netlify
  - netlify functions
  - redirects
  - _redirects
---

# Netlify — field-tested debugging patterns

Load these on top of the generic `skills/diagnose.md` loop. The tell for a Netlify
bug: it works locally and breaks only on the deploy. Build the loop against the
**deployed** URL (or `netlify dev`), not just localhost.

## "Works locally, 404/redirect on deploy" → routing precedence

```
- _redirects / netlify.toml rules apply TOP-TO-BOTTOM, first match wins.
- A catch-all SPA fallback (/* /index.html 200) ABOVE a real rule swallows it.
- 200 = rewrite (URL stays), 301/302 = redirect (URL changes). Mixing them up
  breaks deep links and API proxies. Check the actual status in the Network tab.
- Trailing-slash + case sensitivity differ from local dev — match paths exactly.
```

## Functions: cold start, timeout, path

```
- First hit after idle is a COLD START — a "slow once, fast after" bug is not
  your code. Measure a warm call before optimizing.
- Default function timeout is short (10s background-free) — long work times out
  with a 502, not an app error. Check the function log, not the response body.
- Functions live at /.netlify/functions/<name> — a 404 is usually the path or a
  missing redirect alias, not a broken handler.
```

## Env vars: build-time vs runtime is the #1 trap

```
- VITE_*/PUBLIC_* are INLINED AT BUILD — changing them in the UI needs a REBUILD,
  not just a redeploy-of-same-build. A stale value = old build artifact.
- Server/function secrets are runtime — present in functions, absent in client
  bundles. "undefined in the browser" is correct for a non-public var.
- Branch/deploy-preview contexts can have DIFFERENT env scopes than production.
```

## Deploy-context drift

```
- Deploy previews use preview env + preview URLs — auth callbacks / CORS allow-
  lists keyed to the prod domain will fail on a preview. Verify the context.
- A bug "only in production" is often a prod-only env var or redirect rule —
  diff the netlify.toml [context.production] block against [context.deploy-preview].
```

## Next Steps

- Build the pass/fail loop first → `skills/diagnose.md` (Phase 1)
- Bug is in Firestore reads/rules behind the function → `skills/diagnose/firestore.md`
- App-layer (SvelteKit) routing vs Netlify routing → `skills/svelte.md`
- Root cause found, ready to fix → `skills/implementer.md`
