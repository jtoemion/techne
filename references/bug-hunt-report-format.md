# Structured Bug Hunt Report Format

Use when running per-layer EXPLORE subagents on a codebase to find bugs. This produces consistent, comparable reports that survive across sessions.

## Dispatch Ticket Template

Send to the EXPLORE subagent as the `goal` + `context` pair:

```
**goal**: Bug hunt the {LAYER} layer of {PROJECT} — read every source file in {DIRS}.
Find all bugs. READ ONLY — do not modify any files.
```

**context** block should include:
- Repo path
- Section heading per directory
- Exact file paths to read (one per line)
- Bug categories to scan for
- Output format spec (see below)

## Output Format Spec

Every bug must follow this schema:

```
### Bug #N: {brief title}
**File:** {exact relative path}
**Line(s):** {line numbers}
**Severity:** HIGH / MEDIUM / LOW
**Category:** logic / type / resource-leak / data-integrity / error-handling / test-coverage / edge-case / security / react / api-contract / design
**Description:** {what is wrong, why it matters, who it affects}
**Fix suggestion:** {one paragraph, actionable fix}
```

## Severity Definitions

| Severity | Criteria |
|----------|----------|
| **HIGH** | Causes data loss, crashes, or broken functionality that users hit immediately. Guaranteed 404, silent data drop, guaranteed runtime crash. |
| **MEDIUM** | Causes incorrect behavior in edge cases, partial feature breakage, or maintainability debt that will cause future bugs. Missing validation, test gaps, inconsistent patterns. |
| **LOW** | Cosmetic, naming, style, theoretical edge cases, or non-impacting inconsistencies. Typos, unreachable code, phantom imports, test-quality issues. |

## Layer Classification (for reporting)

Use the **5-layer architecture** slice for structured code review. Every file maps to exactly one layer. This produces consistent reports that slice the codebase cleanly for easy review.

| Layer | What it covers | Typical entry points | Responsibilities |
|-------|---------------|---------------------|-----------------|
| **UI** | Presentational components, screens, layouts, route definitions | `features/`, `app/`, `main.tsx` | Rendering, routing, user-facing structure |
| **Hooks** | State management, custom React hooks, API client, SSE client | `stores/`, `hooks/`, `lib/apiClient.ts`, `lib/sseClient.ts` | State orchestration, data fetching, reactivity |
| **Service** | Business logic, LLM agents, context building, provider adapters | `lib/`, `agents/`, `services/`, `providers/` | Domain rules, AI orchestration, prompt engineering |
| **DAL** | Data access, route handlers, CRUD queries, validation | `routes/`, `db/client.ts` | HTTP endpoints, DB queries, input validation |
| **Database** | Schema definition, migrations, connection management | `db/schema.ts`, `db/migrator.ts` | Table definitions, FK constraints, migration history |

### Dependency direction

```
DATABASE ← DAL ← SERVICE ← (HTTP/SSE) ← HOOKS ← UI
```

Cross-layer rule: never skip a layer. HOOKS talk to SERVICE via HTTP, not directly to DAL. UI never calls DAL directly.

## Workspace-Aware Monorepo Slicing

When the codebase is a monorepo with multiple workspaces (e.g., client/, server/, shared/), each workspace maps to the 5-layer architecture differently. One project workspace may cover multiple architectural layers.

**InkForge example (client/ + server/ + shared/ monorepo):**

| Workspace | Layers it contains |
|-----------|-------------------|
| **client/** | UI + HOOKS |
| **server/** | SERVICE + DAL + DATABASE |
| **shared/** | Shared types, constants — referenced by SERVICE and HOOKS |

**Within client/:**
| Directory | Layer | Responsibility |
|-----------|-------|---------------|
| `features/*.tsx`, `app/`, `main.tsx` | UI | Screens, components, routes |
| `stores/`, `lib/apiClient.ts`, `lib/sseClient.ts` | HOOKS | State, data fetching, SSE |

**Within server/:**
| Directory | Layer | Responsibility |
|-----------|-------|---------------|
| `agents/`, `lib/` (llmService, contextPool, config, wordCount) | SERVICE | Business logic, AI agents |
| `routes/` | DAL | HTTP handlers, CRUD, validation |
| `db/schema.ts`, `db/migrator.ts` | DATABASE | Schema, migrations |

**Bug triage rule of thumb:** When a bug involves client-side request paths, check both the client file (UI/HOOKS) AND the server route (DAL). API prefix mismatches (double /api, wrong path) often span the client/server boundary and belong to both the UI and DAL layers in the bug report.

## For the report summary

```
## Summary
| Severity | Count |
|----------|-------|
| HIGH | N |
| MEDIUM | N |
| LOW | N |
| **Total** | **N** |

### 3 Most Critical

1. **Bug #X — {title}** — {one-liner why it's critical}
...
```
