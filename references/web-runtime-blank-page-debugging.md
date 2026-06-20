# Web runtime blank-page debugging

Use this when a web app builds/tests green but the browser shows a white page, stuck shell, or hydration never starts.

## Fast triage order

1. Reproduce in a production-style preview first.
   - Build the app with the real production env shape.
   - Run the framework preview/server output locally.
   - Confirm whether the blank page reproduces before chasing deploy-platform specifics.

2. Inspect the browser console before reading app code.
   - Look for CSP violations.
   - Look for hydration/bootstrap failures.
   - Look for top-level runtime exceptions in stores, singleton modules, and layout code.

3. Capture the rendered HTML and script tags.
   - Check whether inline bootstrap scripts have the expected nonce.
   - Compare CSP header requirements vs actual `<script>` attributes.
   - If `strict-dynamic` is present, treat missing nonces as fatal until proven otherwise.

4. Only after console/HTML inspection, read the app code paths.
   - `hooks.server.*`, document shell/app template, root layout, shared stores, startup utilities.

## Durable failure patterns seen

### 1) CSP nonce mismatch blocks SvelteKit/bootstrap hydration
Symptoms:
- Browser console reports inline script blocked by `script-src` / `script-src-elem`.
- HTML loads but the page stays visually blank or unhydrated.
- The app's inline bootstrap script exists but has empty/missing `nonce`.

Pattern:
- Server generates a nonce/header.
- Rendered script tags do not receive that nonce.
- `strict-dynamic` makes the missing nonce fatal.

Fix shape:
- Ensure rendered inline script tags receive the request nonce.
- Re-check browser console after preview/deploy.

### 2) Plain `.ts` module ships framework macro syntax to the browser
Symptoms:
- Console shows runtime exceptions like `ReferenceError: $state is not defined`.
- Build can still pass because the invalid construct was not executed until hydration/runtime.
- Often comes from stores/utilities imported very early by layout or shared shell components.

Pattern:
- Framework-specific macros/runes are used in plain TypeScript modules where they are not compiled away safely.

Fix shape:
- Replace with standard framework-supported store/state primitives for plain modules.
- Re-test the first page load in preview, not just unit tests.

## Verification checklist

A web-runtime fix is not done until all are true:
- `check` / type checks pass
- tests pass
- production build passes
- preview or deployed page renders real content
- browser console is clean of CSP/bootstrap/runtime exceptions on first load

## Communication note

If build/tests are green but browser runtime is broken, report that explicitly. Do not call it fixed on build evidence alone.
