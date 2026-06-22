# InkForge — Architecture Improve Candidates (Worked Example)

> Generated 2026-06-22. Updated 2026-06-22 with implementation outcomes.
> Demonstrates the improve-architecture process (EXPLORE → CANDIDATES → PICK ONE)
> on a real codebase — InkForge (React 19 + Hono monorepo).

## Candidate 1 — wordCount.ts: 2-line module earning nothing ✅ COMPLETED

| Column | Detail |
|--------|--------|
| **Files** | `server/src/lib/wordCount.ts`, `server/src/routes/scenes.ts`, `server/src/routes/revisions.ts` |
| **Problem** | 2-line utility (`content.split(/\s+/).filter(Boolean).length`) in its own file, own test. Interface = implementation. |
| **Solution** | Inline into callers — replace 5 `countWords(x)` calls with the inline expression. Delete wordCount.ts. |
| **Implementation** | 5 call sites inlined across scenes.ts (3) and revisions.ts (2). wordCount.ts deleted. -4 lines, -1 file, 0 regression. |
| **Before/After** | 1 export, 1 file, 1 test file → 0 files; callers grew 0 lines (expression replaced function call). |
| **Strength** | **Strong** — zero ambiguity this was shallow. |

## Candidate 2 — SSE orchestration triplicated ✅ COMPLETED

| Column | Detail |
|--------|--------|
| **Files** | `client/src/lib/sseClient.ts`, `server/src/routes/ai.ts`, `server/src/routes/brainstorm.ts`, `server/src/lib/providers/streamUtils.ts` |
| **Problem** | `makeSSEStream` re-implemented identically in `ai.ts` and `brainstorm.ts`. `streamScribe`/`streamArchitect` near-clones in `sseClient.ts`. Only `readLines` (the hard part) was centralized in `streamUtils.ts`. |
| **Solution** | Extract `makeSSEStream` into `streamUtils.ts`. Consolidate SSE client via shared `createSSEStream` helper. |
| **Implementation** | Server: `makeSSEStream` moved to `streamUtils.ts`, -43 lines from `ai.ts`. Client: shared `createSSEStream(url, body, onToken, signal?)` collapses ~80 lines of near-identical `processStream` read loop. `streamScribe`/`streamArchitect` unchanged API, each ~10 lines now. |
| **Before/After** | Server: 2 independent ~35-line implementations → 1 shared 28-line utility. Client: 2 near-clone ~80-line functions → 1 shared helper + 2 x 10-line wrappers. |
| **Strength** | **Strong** — triplication was undeniable. |

## Candidate 3 — SQL query logic scattered across prompt-building agents

| Column | Detail |
|--------|--------|
| **Files** | `server/src/agents/scribe.ts`, `server/src/agents/architect.ts`, `server/src/lib/contextPool.ts`, `server/src/lib/projectContext.ts` |
| **Problem** | Every agent and context builder embeds its own raw SQL for the same entities (scenes, characters, beats, etc.). Schema changes require updating 3-4 places. |
| **Solution** | `ProjectDataRepository` with typed methods: `getScenes()`, `getCharacters()`, `getBeats()`, etc. |
| **Benefit** | Schema changes = single-location fixes. Consistent row shape. Agents focus on prompt construction. |
| **Before/After** | ~15 raw SQL strings across 4 files → 1 repository with 8-10 methods. |
| **Strength** | **Strong** — duplication is structural. |

## Candidate 4 — leaky llmService provider routing

| Column | Detail |
|--------|--------|
| **Files** | `server/src/lib/llmService.ts`, `server/src/lib/config.ts`, `server/src/lib/providers/` |
| **Problem** | `getProviderForModel()` uses fragile `startsWith('gemini-')` prefix matching. `getDefaultModel()` calls SQLite directly, violating service boundary. |
| **Solution** | `ModelRouter` class encapsulating model→provider mapping, API key resolution, base URLs. |
| **Benefit** | Routing policy centralized and testable. New provider = one class change. |
| **Before/After** | Routing implicit in 3 functions + 3 provider files → explicit typed registry. |
| **Strength** | **Worth exploring** — works today, fragility is the risk. |

## Candidate 5 — shared types duplication

| Column | Detail |
|--------|--------|
| **Files** | `shared/src/types.ts`, `shared/src/constants.ts`, `shared/src/schemas.ts` |
| **Problem** | `ModelId`, `Genre`, `SceneType` defined in BOTH files — union type in `types.ts`, `as const` array in `constants.ts`. Two authorities that can drift. |
| **Solution** | Consolidate domain primitives into `constants.ts`. `types.ts` becomes pure interface/struct types only. |
| **Benefit** | Single source of truth for each domain primitive. No silent divergence. |
| **Before/After** | 4 primitives duplicated across 2 files → each defined once. |
| **Strength** | **Speculative** — structural typing masks the breakage risk. |

## Session Statistics

| Metric | Value |
|--------|-------|
| Candidates identified | 5 |
| Implemented (this session) | 2 (wordCount inline, SSE dedup) |
| Pipeline tasks | 2 (fast mode) |
| Total lines removed | ~120 (-4 wordCount, -43 server SSE, -80 client SSE) |
| Tests | 391 passed, 0 regressions |
