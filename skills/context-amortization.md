---
name: context-amortization
description: Mandatory context preflight for Techne tasks. Use before implementing, debugging, reviewing, or verifying when a task enters the orchestrator loop; it prevents repeated project onboarding by serving a fresh context pack.
triggers:
  - context preflight
  - context pack
  - context amortization
  - project context
  - context hash
  - .techne/context
  - stop rereading the project
---

# Context Amortization

## Mandatory Rule

No agent starts with a blank repo. Every Techne task begins with `CONTEXT_PREFLIGHT` and receives a fresh context pack before `IMPLEMENT`.

```
CONTEXT_PREFLIGHT → IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → DONE
```

The context role pays the broad-read cost once. Worker roles consume targeted packs.

## Required Context Files

```
.techne/context/project_digest.md      ← what the repo is, commands, landmines
.techne/context/file_roles.md          ← file ownership and module map
.techne/context/commands.md            ← build/test/lint commands
.techne/context/risk_boundaries.md     ← HITL and no-go areas
.techne/context/context_hash.txt       ← freshness marker
.techne/context/context_packs/*.md     ← task-specific packs
```

If a base file is missing, `context-preflight` creates it.  
If `context_hash.txt` is stale, `context-preflight` refreshes it.  
If a selected pack is missing, `context-preflight` creates it.

## Pack Selection

```
auth          → auth.md
database      → database.md
frontend      → frontend.md
deployment    → deployment.md
testing       → testing.md
techne/harness→ techne.md
```

Selection uses task title, description, discipline, tags, and changed files.  
No pack selection is allowed to authorize broad repo browsing by worker agents.

## Agent Read Budgets

```
context-preflight  → may read broadly; writes only .techne/context
context-guard      → reads diff and task history; no code edits
implementer        → reads digest + selected pack + directly relevant files
critique/reviewer  → reads diff, touched files, risk boundaries
verifier           → runs commands; does not read source unless a command fails
debugger           → reads failure logs, touched files, selected pack
```

## Mandatory Output Checklist

Every `CONTEXT_PREFLIGHT` report must include:

```
[ ] context status: fresh | missing | stale
[ ] context_hash written
[ ] selected packs
[ ] files written or refreshed
[ ] HITL boundaries that apply to this task
[ ] read budget for the next phase
```

## Next Steps

- Writing/updating this flow? → `skills/writing-skill.md`
- Changing pipeline phases? → `harness/pipeline_enforcer.py` + `harness/orchestrator_loop.py`
- Changing context hashing? → `harness/context_preflight.py` + `tests/test_context_amortization.py`
- Adding a hard gate? → `harness/plugins/*.py` with `register(registry)`
- Done with context preflight? → back to `skills/context-amortization.md`