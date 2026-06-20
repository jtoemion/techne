# Maintainability audit + context refresh pattern

This note captures a reusable workflow from a full repo audit and `.techne/context` refresh.

## When to use
Use this pattern when the user asks for an end-to-end maintainability audit, architecture refresh, or repository re-orientation before making changes.

## Reusable workflow
1. Re-explore the checkout from first principles.
   - `git branch --show-current`
   - `git status --short`
   - `git rev-parse --short HEAD`
   - read package scripts, repo docs, and key source directories directly
2. Consult Honcho early.
   - Use it to recover prior decisions, regressions, and constraints.
   - Verify the recovered facts against the current checkout before acting.
3. Inspect the current architecture surfaces.
   - app package scripts
   - route tree
   - domain/backend modules
   - test footprint
   - repo-local handoff/context files
4. Critique with evidence only.
   - Look for duplicated transport/bootstrap logic
   - dead UI state / unused branches
   - large mixed-responsibility modules
   - brittle or missing tests around important workflows
   - stale docs or handoff claims
5. Make small, low-risk fixes first.
   - Prefer shared helpers over copy-pasted bootstrapping
   - remove dead state only when you can verify it’s unused
   - keep behavior identical unless the evidence strongly supports a change
6. Verify with real commands.
   - app typecheck/check
   - tests
   - production build when route/runtime code changed
   - record the actual output, including warnings that remain
7. Refresh `.techne/context` after changes.
   - Update architecture map, workflows, constraints, and risks
   - Recompute the context hash after the bundle content changes

## Session-specific lesson
A useful maintainability win was adding a shared browser-side Convex HTTP helper for `stage/app` and moving route pages to it instead of repeating `ConvexHttpClient` + `PUBLIC_CONVEX_URL` setup in each page.

## Pitfalls
- Don’t trust historical docs or old handoff files as current truth.
- Don’t invent defects; if the evidence is weak, record it as a risk or leave it alone.
- If `.techne/context` changes during the audit, update the checksum marker after the final content settles.
- Build/test verification should come from the real checkout, not from assumptions about the script set.

## Outcome shape
Good outputs from this workflow usually include:
- a concise audit summary
- a list of concrete flaws/regressions found
- any focused fixes made
- verification commands and outputs
- remaining risks
- durable lessons worth saving in Honcho or a support reference
