# Techne Project Workshop Redesign

> For Hermes: this document defines the next shape of Techne as a project-attached workshop, not just an agent-prompt pipeline.

**Goal:** Redefine Techne as a framework app that wraps each target codebase with a local workshop shell (`.techne/`), a searchable project knowledge base, and an automatic post-work documentation refresh system.

**Architecture:** Split Techne into two layers: (1) a reusable core framework that provides pipeline, scripts, retrieval, gates, and graph-building; (2) a per-project workshop shell that stores project-specific context, generated indexes, durable lessons, and doc-refresh artifacts. RECALL stops being "search vaguely" and becomes "build a scoped context pack from the project workshop graph."

**Tech Stack:** Python 3.10+, Markdown, JSON, git diff metadata, optional repo-language adapters (TS/Svelte/Next/Convex/etc.), no mandatory external services.

---

## 0. Executive framing

Current Techne is still described mostly as a harness/pipeline.
That is now too small.

The actual direction is:
- execution discipline
- durable project memory
- context retrieval
- generated codebase indexes
- automatic doc maintenance
- project-scoped workshop tools

That is not just a skill.
That is a framework app with a project shell.

Recommended new definition:

"Techne is a project-attached engineering workshop that wraps a codebase with execution discipline, contextual memory, generated knowledge, searchable context, and self-maintaining documentation."

Flat sentence. More useful than inspirational.

---

## 1. `.techne/` project-shell spec

Each target codebase gets a local shell at repo root:

```text
.techne/
  config.yaml
  workshop.json

  context/
    root.CONTEXT.md
    auth.CONTEXT.md
    billing.CONTEXT.md
    frontend.CONTEXT.md
    backend.CONTEXT.md
    deploy.CONTEXT.md
    testing.CONTEXT.md

  generated/
    file_index.json
    symbol_index.json
    route_map.json
    api_map.json
    schema_map.json
    test_map.json
    dependency_graph.json
    context_index.json
    change_log.json
    subsystem_map.json
    ownership_map.json
    stale_docs.json

  memory/
    ledger.md
    mistakes.md
    wikilinks.md
    wikilinks.json
    retro_learn_triggers.md
    task_history.jsonl
    context_search_cache.json

  proposals/
    context_patches/
    adr_patches/
    subsystem_patches/

  tasks/
    <task_id>/
      recall_pack.md
      implement.diff
      verify.txt
      review.txt
      retro.txt
      conclude.txt
      refresh_context.json

  scripts/
    context_index.py
    context_search.py
    refresh_generated_docs.py
    propose_context_updates.py
    stale_docs_check.py
    touched_subsystems.py
```

### 1.1 Shell responsibilities

`config.yaml`
- project metadata
- stack adapters to enable
- directory-to-subsystem mappings
- which docs are generated / proposed / manual
- refresh hooks
- recall weighting knobs

`context/`
- human-authored subsystem context docs
- sparse, curated, high-signal
- not generated

`generated/`
- deterministic indexes derived from code and git state
- safe to rewrite automatically
- machine-first, human-readable where helpful

`memory/`
- durable project lessons and retrieval graph
- artifacts produced by RETRO / CONCLUDE / REFRESH_CONTEXT

`proposals/`
- machine-suggested edits to authored docs
- never silently overwrite human-sensitive docs

`tasks/`
- per-task trace so later recall can connect history to subsystems/files/tests

`scripts/`
- project workshop tools invoked by RECALL and post-work phases

### 1.2 What counts as a subsystem context doc

Do not create a doc for every folder.
Create a `*.CONTEXT.md` only for semantic subsystems with at least one of:
- clear purpose
- recurring edits
- special invariants
- multiple entrypoints
- notable runtime/build/deploy traps
- durable lessons worth surfacing before work

Good candidates:
- auth
- billing
- notifications
- deployment
- frontend shell
- data model
- API layer
- tests/fixtures strategy

Bad candidates:
- one-file utility dirs
- cache dirs
- generated dirs
- tiny folders with no subsystem meaning

### 1.3 Context doc schema

Each context doc should use strict frontmatter:

```md
---
kind: context_doc
subsystem: auth
paths:
  - src/lib/auth
  - src/routes/login
owners: []
tags: [auth, session, better-auth]
related_skills: [diagnose, implementer]
related_docs:
  - docs/adr/ADR-0003-auth-flow.md
related_tests:
  - tests/auth/
refresh_policy: proposed
---

# Auth Context

## Purpose
## Entry points
## Invariants
## External dependencies
## Common failure modes
## If you change X, also inspect Y
## Related lessons
```

`refresh_policy` values:
- `manual`
- `proposed`
- `generated-link-only`

---

## 2. Context-graph node/edge schema

The current wikilink graph should expand from memory-only links into a project workshop graph.

### 2.1 Node types

Required node types:

1. `project`
- repo root, stack, workshop config

2. `subsystem`
- semantic project area: auth, billing, deploy, etc.

3. `context_doc`
- authored `*.CONTEXT.md`

4. `generated_doc`
- generated indexes/maps under `.techne/generated/`

5. `file`
- source/config/test/doc files

6. `symbol`
- function/class/route/action/schema/export

7. `test`
- test file or test case grouping

8. `route`
- app route or endpoint

9. `schema`
- db table/model/Convex collection/etc.

10. `task`
- Techne task ID + status + timestamps

11. `lesson`
- durable method or project lesson from ledger

12. `mistake`
- recurring failure pattern from mistakes log

13. `decision`
- durable project decision from ledger / ADR

14. `discipline`
- enforced working rule

15. `artifact`
- verify output, review text, conclude proof, diff summary

16. `skill`
- Techne/core skill or project-local helper skill

17. `env_var`
- important config variable

18. `service`
- external/local dependency (Netlify, Convex, Postgres, S3, etc.)

### 2.2 Edge types

Required edge vocabulary:

- `project_contains -> subsystem`
- `subsystem_contains -> file`
- `file_defines -> symbol`
- `file_exercises -> test`
- `route_uses -> symbol`
- `symbol_reads -> schema`
- `symbol_calls -> symbol`
- `context_describes -> subsystem`
- `context_points_to -> file`
- `context_mentions -> decision`
- `context_mentions -> lesson`
- `generated_describes -> subsystem`
- `task_touched -> file`
- `task_changed -> subsystem`
- `task_produced -> artifact`
- `task_triggered -> lesson`
- `task_triggered -> mistake`
- `lesson_applies_to -> subsystem`
- `mistake_applies_to -> file`
- `decision_constrains -> subsystem`
- `discipline_constrains -> task`
- `skill_supports -> subsystem`
- `env_var_affects -> service`
- `env_var_required_by -> file`
- `test_protects -> file`
- `test_protects -> route`

### 2.3 Graph storage shape

Primary store: `.techne/memory/wikilinks.json`

Recommended top-level schema:

```json
{
  "project": {
    "name": "ms-ellen-project",
    "repo_root": "/abs/path",
    "generated_at": "2026-06-20T00:00:00Z",
    "version": 2
  },
  "nodes": [
    {
      "id": "subsystem:auth",
      "kind": "subsystem",
      "title": "Authentication",
      "path": "src/lib/auth",
      "tags": ["auth", "session"],
      "metadata": {}
    }
  ],
  "edges": [
    {
      "from": "context:auth",
      "type": "context_describes",
      "to": "subsystem:auth",
      "weight": 1.0,
      "source": "context_index"
    }
  ],
  "inverted_indexes": {
    "by_kind": {},
    "by_path": {},
    "by_tag": {},
    "by_subsystem": {}
  }
}
```

### 2.4 Retrieval ranking hints

Each node can carry:
- `recency_score`
- `stability_score`
- `failure_weight`
- `decision_weight`
- `touch_count`
- `verified_count`

Each edge can carry:
- `weight`
- `source` (`generated`, `manual`, `retro`, `task_trace`)
- `confidence`

That lets RECALL rank:
- recent but unstable
- old but critical
- repeated failures
- high-confidence authored subsystem docs

---

## 3. Doc classification: generated vs proposed vs manual

This is where automatic updates stop being dangerous.

### 3.1 Generated docs: safe to rewrite

These are deterministic outputs derived from code, tests, routes, schemas, or git changes.
They may be overwritten by scripts without review.

Examples:
- `.techne/generated/file_index.json`
- `.techne/generated/symbol_index.json`
- `.techne/generated/route_map.json`
- `.techne/generated/schema_map.json`
- `.techne/generated/test_map.json`
- `.techne/generated/dependency_graph.json`
- `.techne/generated/change_log.json`
- `.techne/generated/context_index.json`
- `.techne/generated/stale_docs.json`
- `.techne/memory/wikilinks.json`
- `.techne/memory/wikilinks.md`

Rule:
- scripts own them entirely
- never hand-edit
- rebuild from source state

### 3.2 Proposed docs: machine writes patch proposals, not final truth

These are human-readable but partially inferential.
Scripts can generate patches or proposed rewrites.
A phase or reviewer adopts them.

Examples:
- `.techne/context/auth.CONTEXT.md`
- `.techne/context/deploy.CONTEXT.md`
- `docs/architecture/*.md`
- runbooks that summarize stable behavior

Rule:
- auto-generate patch proposals under `.techne/proposals/`
- attach reason + evidence + touched files
- do not overwrite in place unless explicitly allowed by policy

### 3.3 Manual docs: detect drift only

These are intent-heavy or business-sensitive.
Techne may flag drift, but should not write them automatically.

Examples:
- ADRs
- product requirements
- policy docs
- pricing/business rules
- client-facing docs

Rule:
- produce warnings and proposed snippets only
- no direct modification by default

### 3.4 Refresh policy table

| Policy | Meaning | Script action |
|---|---|---|
| `generated` | fully script-owned | rewrite directly |
| `proposed` | inference acceptable but needs review | write patch proposal |
| `manual` | human-owned narrative | emit drift warning only |
| `off` | ignored by workshop | no action |

### 3.5 Why this split matters

Without the split, auto-doc update becomes fiction production.
With the split, generated truth stays fresh while narrative truth stays accountable.

---

## 4. New phase sketch: `REFRESH_CONTEXT`

Current ending:

```text
RECALL → IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → EVAL → RETRO → CONCLUDE → DONE
```

Proposed ending:

```text
RECALL → IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → EVAL → RETRO → CONCLUDE → REFRESH_CONTEXT → DONE
```

### 4.1 Why this should be a real phase

Today, document/knowledge maintenance is incidental.
That means it is forgotten exactly when it matters most: after real code movement.

`REFRESH_CONTEXT` makes workshop maintenance explicit and testable.

### 4.2 Inputs to `REFRESH_CONTEXT`

Required inputs:
- task ID
- touched files from git diff or task artifact
- subsystem matches for touched files
- verify output
- review output
- retro output / ledger entries
- conclude proof
- project-shell config
- current context graph

### 4.3 Responsibilities

`REFRESH_CONTEXT` must:

1. rebuild deterministic generated docs for touched subsystems
2. rebuild or incrementally patch `.techne/memory/wikilinks.{md,json}`
3. update `.techne/generated/change_log.json`
4. run stale-doc detection on impacted context docs
5. write proposal patches for `proposed` docs
6. attach refresh artifact under `.techne/tasks/<task_id>/refresh_context.json`
7. return a proof block summarizing:
   - generated files updated
   - proposal files created
   - manual docs flagged for review

### 4.4 Suggested gate for `REFRESH_CONTEXT`

Phase passes only if:
- generated docs for touched subsystems were refreshed
- context graph rebuilt successfully
- no required generated index is missing
- proposal files exist for any stale `proposed` docs
- phase output includes proof lines

Suggested proof format:

```text
GENERATED:
- .techne/generated/context_index.json
- .techne/generated/change_log.json
- .techne/memory/wikilinks.json

PROPOSED:
- .techne/proposals/context_patches/auth.patch.md

MANUAL_REVIEW:
- docs/adr/ADR-0003-auth-flow.md

SUBSYSTEMS:
- auth
- deploy
```

### 4.5 Fast-mode behavior

For `phase_mode=fast` or review-only tasks:
- skip authored-doc proposals unless touched files cross a subsystem threshold
- still rebuild minimal generated indexes and task history
- keep refresh cheap, not theatrical

### 4.6 Failure modes to guard

- no touched files detected because repo root lookup is wrong
- proposal files written but not linked into task artifact
- stale doc detector too noisy, causing alert fatigue
- generated docs rewritten globally on every run, making diffs useless
- context graph rebuild failure silently swallowed

### 4.7 Long-term effect

Adding `REFRESH_CONTEXT` turns the workshop into a self-maintaining system.
Without it, knowledge quality still depends on luck and attention span.

---

## 5. First three scripts + I/O contracts

These three scripts form the first useful slice.
Not glamorous. Useful.

### 5.1 `scripts/context_index.py`

**Purpose:** Build deterministic indexes from project structure and authored context docs.

**Reads:**
- `.techne/config.yaml`
- `.techne/context/*.md`
- repo file tree
- optional adapter outputs (route/schema/test extractors)

**Writes:**
- `.techne/generated/context_index.json`
- optional `.techne/generated/subsystem_map.json`

**CLI:**
```bash
python3 .techne/scripts/context_index.py
python3 .techne/scripts/context_index.py --subsystem auth
python3 .techne/scripts/context_index.py --json
```

**Input contract:**
- repo root contains `.techne/config.yaml`
- context docs use valid frontmatter
- script may run from repo root or any child dir

**Output contract (`context_index.json`):**
```json
{
  "generated_at": "...",
  "repo_root": "...",
  "subsystems": [
    {
      "name": "auth",
      "paths": ["src/lib/auth"],
      "context_doc": ".techne/context/auth.CONTEXT.md",
      "tags": ["auth", "session"],
      "related_tests": ["tests/auth"],
      "refresh_policy": "proposed"
    }
  ],
  "files": [
    {
      "path": "src/lib/auth/session.ts",
      "subsystem": "auth"
    }
  ]
}
```

**Failure behavior:**
- non-zero exit if config missing or invalid frontmatter
- never partially write malformed JSON
- emit actionable error lines with file path

**Why it exists:**
- gives RECALL a deterministic map before any LLM reasoning
- gives refresh jobs a path→subsystem mapping

---

### 5.2 `scripts/context_search.py`

**Purpose:** Search the project workshop graph and return a ranked context pack for RECALL or debugging.

**Reads:**
- `.techne/generated/context_index.json`
- `.techne/memory/wikilinks.json`
- `.techne/memory/ledger.md`
- `.techne/memory/mistakes.md`
- `.techne/context/*.md`
- optionally task history and recent diffs

**Writes:**
- nothing by default
- optional cache: `.techne/memory/context_search_cache.json`

**CLI:**
```bash
python3 .techne/scripts/context_search.py "conclude sha gate"
python3 .techne/scripts/context_search.py "auth redirect loop" --kind subsystem
python3 .techne/scripts/context_search.py "guardian evidence learnerIds" --json
python3 .techne/scripts/context_search.py --task "Fix auth SSR"
```

**Input contract:**
- at least one of `query` or `--task`
- required generated indexes exist

**Search pipeline:**
1. detect explicit path/subsystem hits
2. search subsystem tags/frontmatter
3. search graph neighbors in wikilinks
4. search lessons/mistakes/decisions
5. score by recency, subsystem overlap, failure weight, authored-doc confidence
6. emit a ranked context pack

**Output contract (human mode):**
```text
QUERY: auth redirect loop
LIKELY_SUBSYSTEMS:
- auth (0.93)

CONTEXT_DOCS:
- .techne/context/auth.CONTEXT.md

FILES:
- src/lib/auth/session.ts
- src/routes/login/+page.server.ts

LESSONS:
- Session cookies must be checked in server load before redirect

MISTAKES:
- Redirect gate false-positive outside middleware

TESTS:
- tests/auth/session.spec.ts
```

**Output contract (`--json`):**
```json
{
  "query": "auth redirect loop",
  "subsystems": [{"name": "auth", "score": 0.93}],
  "context_docs": [],
  "files": [],
  "lessons": [],
  "mistakes": [],
  "tests": []
}
```

**Failure behavior:**
- non-zero exit if workshop indexes missing
- helpful hint: run `context_index.py` or `refresh_generated_docs.py`

**Why it exists:**
- makes RECALL concrete
- gives humans and agents the same retrieval entrypoint

---

### 5.3 `scripts/refresh_generated_docs.py`

**Purpose:** Given a task or a touched-file set, rebuild deterministic generated artifacts and produce refresh metadata.

**Reads:**
- git diff / task artifact touched files
- `.techne/config.yaml`
- `.techne/generated/context_index.json`
- adapters for routes/schema/tests
- existing `.techne/memory/wikilinks.json`

**Writes:**
- `.techne/generated/change_log.json`
- updated generated indexes for impacted subsystems
- `.techne/memory/wikilinks.{md,json}`
- `.techne/generated/stale_docs.json`
- optional `.techne/tasks/<task_id>/refresh_context.json`

**CLI:**
```bash
python3 .techne/scripts/refresh_generated_docs.py --task a21abf5b
python3 .techne/scripts/refresh_generated_docs.py --files src/lib/auth/session.ts src/routes/login/+page.server.ts
python3 .techne/scripts/refresh_generated_docs.py --since HEAD~1
```

**Input contract:**
- one of `--task`, `--files`, or `--since`
- repo is a git worktree unless explicit `--files` is used

**Output contract:**
```json
{
  "task_id": "a21abf5b",
  "touched_files": ["src/lib/auth/session.ts"],
  "subsystems": ["auth"],
  "generated_updated": [
    ".techne/generated/context_index.json",
    ".techne/generated/change_log.json",
    ".techne/memory/wikilinks.json"
  ],
  "stale_docs": [
    {
      "path": ".techne/context/auth.CONTEXT.md",
      "reason": "new entrypoint file touched but not mentioned"
    }
  ]
}
```

**Failure behavior:**
- non-zero exit if repo root or task artifacts cannot be resolved
- no silent partial success
- always print which generated file failed to build

**Why it exists:**
- this is the engine behind `REFRESH_CONTEXT`
- it keeps project knowledge synchronized with real code movement

---

## 6. Proposed RECALL contract after redesign

RECALL should no longer be a vague research phase.
It should consume the workshop.

### 6.1 RECALL algorithm

1. classify the task
- bugfix / feature / review-only / deploy / debug

2. detect likely subsystem(s)
- user prompt
- task tags
- touched files if known
- path hints

3. call `context_search.py`
- get ranked context pack

4. attach top artifacts
- context docs
- top files
- tests
- lessons
- mistakes
- decisions
- runtime notes

5. emit `recall_pack.md`
- saved under `.techne/tasks/<task_id>/`

### 6.2 Minimum recall pack shape

```md
# RECALL PACK — task a21abf5b

## Likely subsystems
- auth
- deploy

## Read first
- .techne/context/auth.CONTEXT.md
- docs/adr/ADR-0003-auth-flow.md

## Files to inspect
- src/lib/auth/session.ts
- src/routes/login/+page.server.ts

## Known lessons
- ...

## Known mistakes
- ...

## Tests to run first
- ...
```

---

## 7. Adoption plan

### Phase 1 — workshop foundation
- add `.techne/config.yaml`
- add `.techne/context/root.CONTEXT.md`
- add 3–5 subsystem context docs
- implement `context_index.py`
- extend wikilink schema to project nodes/edges

### Phase 2 — retrieval
- implement `context_search.py`
- wire RECALL to use it
- save `recall_pack.md` under each task

### Phase 3 — refresh
- implement `refresh_generated_docs.py`
- add `REFRESH_CONTEXT` phase
- emit stale-doc warnings + proposal patch stubs

### Phase 4 — proposal system
- implement `propose_context_updates.py`
- generate patches for `proposed` docs
- add adoption workflow / gate

### Phase 5 — adapters
- language/framework extractors for SvelteKit, React/Vite, Next.js, Convex, Firestore
- better file→subsystem heuristics
- symbol/test/route enrichment

---

## 8. Guardrails

1. Do not overwrite authored docs with low-confidence inference.
2. Prefer touched-subsystem incremental refresh over full-repo rebuild.
3. Keep deterministic indexes as the substrate; LLM prose is downstream, not foundational.
4. Track provenance on graph edges (`manual`, `generated`, `retro`, `task_trace`).
5. If retrieval confidence is low, RECALL should say so explicitly.
6. Generated docs must be reproducible from repo state.
7. Proposal patches must cite evidence: touched files, diff snippets, or generated index deltas.

---

## 9. Decision summary

Decision 1: Techne should be redefined as a project workshop framework, not merely a pipeline skill.

Decision 2: Each project should get a `.techne/` shell that holds context docs, generated indexes, memory graph, proposals, scripts, and task artifacts.

Decision 3: RECALL should run through a project workshop search entrypoint (`context_search.py`) instead of ad hoc memory/doc search.

Decision 4: Automatic documentation maintenance is feasible, but only with a strict split between generated, proposed, and manual docs.

Decision 5: `REFRESH_CONTEXT` should be a real phase after CONCLUDE so code work leaves the project workshop in a fresher state than it found it.

---

## 10. Immediate next implementation slice

If building this next, the first practical batch should be:

1. `.techne/config.yaml` schema
2. 3 sample `*.CONTEXT.md` files
3. `context_index.py`
4. `context_search.py`
5. `refresh_generated_docs.py`
6. wikilink schema v2 upgrade
7. RECALL integration stub
8. `REFRESH_CONTEXT` phase scaffold

That is enough to prove the workshop shape without pretending the full system already exists.

The rest can grow around it. Like a workshop usually does.