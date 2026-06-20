# Vite 8 + SvelteKit Adapter Trap

## Symptom

Build output contains `No adapter specified` even though `@sveltejs/adapter-netlify` (or `adapter-vercel`, etc.) is installed and imported in `svelte.config.js`.

## Root cause

Vite 8's `sveltekit()` plugin function (`@sveltejs/kit/src/exports/vite/index.js:149-169`) has this logic:

```js
if (config !== undefined) {
    // ...process config from vite.config.ts...
    const config_file = ['svelte.config.js', 'svelte.config.ts'].find((file) =>
        fs.existsSync(file)
    );
    if (config_file) {
        console.warn(`${config_file} is ignored when options are passed via your Vite config`);
    }
} else {
    svelte_config = await load_svelte_config();  // reads svelte.config.js
}
```

When ANY options are passed to `sveltekit()` in `vite.config.ts` (even just `compilerOptions: { runes: ... }`), `svelte.config.js` is silently ignored — including the adapter.

The fix: move the adapter config into `vite.config.ts` as a sibling of `compilerOptions`:

```ts
// vite.config.ts
import { sveltekit } from '@sveltejs/kit/vite';
import adapter from '@sveltejs/adapter-netlify';
import { defineConfig } from 'vite';

export default defineConfig({
    plugins: [
        sveltekit({
            compilerOptions: {
                runes: ({ filename }) =>
                    filename.split(/[/\\]/).includes('node_modules') ? undefined : true
            },
            adapter: adapter({})    // <-- moved here, not in svelte.config.js
        })
    ]
});
```

The `sveltekit(config)` function destructures known fields (`extensions`, `compilerOptions`, `vitePlugin`, `preprocess`) and puts everything else into `kit`. So `adapter: adapter({})` correctly ends up as `kit.adapter`.

## `_headers` requirement

`@sveltejs/adapter-netlify` calls `builder.copy('_headers', ...)` during `adapt()` — this copies a `_headers` file from the project root to the publish directory. If the file doesn't exist, the build crashes with:

```
Error: ENOENT: no such file or directory, open '.svelte-kit/output/_headers'
```

Create `_headers` at the project root with standard security headers:

```
/*
  X-Frame-Options: DENY
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
```

## Verification

Successful adapter invocation looks like:

```
> Using @sveltejs/adapter-netlify
  ✔ done
```

And produces:

```
.netlify/
├── functions-internal/
│   ├── sveltekit-render.json
│   └── sveltekit-render.mjs
├── serverless.js
├── edge.js
└── shims.js
```

Failed adapter (when svelte.config.js is ignored) shows only:

```
No adapter specified
See https://svelte.dev/docs/kit/adapters to learn how to configure your app
```

With no `.netlify/` directory created.

## Scope

This affects all adapters, not just `adapter-netlify`. `adapter-vercel`, `adapter-node`, etc. have the same issue when `svelte.config.js` is ignored. The fix is the same: import and pass the adapter in `vite.config.ts`.

## See also

- `svelte.config.js` can be kept for dev tooling (VS Code, svelte-check standalone) but is not read by `vite build` when options are passed
- `svelte.config.js` should retain `preprocess: vitePreprocess()` for dev tools that read it directly
