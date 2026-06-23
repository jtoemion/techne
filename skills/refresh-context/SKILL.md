---
name: refresh-context
description: Context amortization refresh — when to skip (fast mode), what files to update (context_hash.txt, project_digest.md, file_roles.md), and how to avoid silent failures.
triggers:
  - refresh context
  - context amortization
  - context refresh
  - context hash
  - .techne/context
---

# Refresh Context — Context Amortization Phase

## When to Use

REFRESH_CONTEXT runs after CONCLUDE in the pipeline. It updates the durable context files so the next recall is accurate.

## Fast Mode (Skip Conditions)

If `.techne/config.yaml` does not exist, run in **fast mode** — skip the full refresh and only update `context_hash.txt` if it is stale.

Fast mode skips:
- Full project digest rebuild
- File roles scan
- Risk boundaries update

```
if not Path(".techne/config.yaml").exists():
    # fast mode: hash-only refresh
    update_context_hash_if_stale()
    return
```

## What to Update

### 1. `context_hash.txt`

The freshness marker. Updated by `harness/context_build.conclude_context()`.

```
# Computed from all .techne/context/* files
# Stale if any context file modified after context_hash.txt
# Pattern: <hash> — <timestamp>
```

If `context_hash.txt` is missing or older than any context file, it is stale — refresh it.

### 2. `project_digest.md`

What the repo is, build commands, landmines.

Updated when:
- New landmines discovered during the run
- Build/test commands changed
- Project structure was modified

### 3. `file_roles.md`

File ownership and module map.

Updated when:
- New modules created
- File ownership changed
- New files introduced that affect the module map

## Context Amortization Contract

The context role pays the broad-read cost once (recall). At conclude, context-guard keeps `docs/` + `.techne/context` HOT:

```
RECALL → IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → EVAL → RETRO → CONCLUDE → REFRESH_CONTEXT
```

## Required Context Files

```
.techne/context/project_digest.md      ← what the repo is, commands, landmines
.techne/context/file_roles.md          ← file ownership and module map
.techne/context/commands.md            ← build/test/lint commands
.techne/context/risk_boundaries.md     ← HITL and no-go areas
.techne/context/context_hash.txt       ← freshness marker
.techne/context/context_packs/*.md     ← task-specific packs
```

## Avoiding Silent Failures

### Check context_hash freshness before every recall

```python
def is_context_stale() -> bool:
    hash_file = Path(".techne/context/context_hash.txt")
    if not hash_file.exists():
        return True
    hash_mtime = hash_file.stat().st_mtime
    for ctx_file in Path(".techne/context").glob("*.md"):
        if ctx_file.stat().st_mtime > hash_mtime:
            return True
    return False
```

If stale, refresh before proceeding to IMPLEMENT.

### Verify pack existence before selecting

If a context pack is referenced in the task spec but missing, do not skip — create it.

### Log what was refreshed

REFRESH_CONTEXT output must include:
```
[ ] context_hash updated: yes/no
[ ] project_digest updated: yes/no
[ ] file_roles updated: yes/no
[ ] context packs refreshed: <list or "none">
[ ] stale before: yes/no
[ ] stale after: yes/no
```

Omitting this checklist means the refresh was silent — the gate rejects silent refreshes.

## Mandatory Output Checklist

Every REFRESH_CONTEXT report must include:

```
[ ] context status: fresh | stale
[ ] context_hash written: yes/no
[ ] project_digest updated: yes/no
[ ] file_roles updated: yes/no
[ ] context packs refreshed: <list or none>
[ ] SHA of committed context: sha:<hex>
```

## Git Commit Discipline

After updating context files, commit them:

```bash
git add .techne/context/
git commit -m "context: refresh after <task_id>"
```

The SHA of this commit is passed to CONCLUDE as proof of context freshness.

## Connection to Context Amortization Skill

This phase is the second half of the context amortization bookend:
- **RECALL** — pays the broad-read cost once, produces a hot context pack
- **REFRESH_CONTEXT** — after the change, refreshes the source files so next recall is accurate

See `skills/context-amortization/SKILL.md` for the full contract.

## Hard Constraints

- `context_hash.txt` must reflect the actual state of all context files
- Silent refreshes (no output logged) are rejected
- If `.techne/config.yaml` exists, full refresh is required — cannot skip to fast mode
- Context files must be committed before CONCLUDE claims they were updated
- If any context file is modified during the run, `context_hash.txt` is stale until refreshed

## Next Steps

- After REFRESH_CONTEXT? → Pipeline complete
- Context preflight? → `skills/context-amortization/SKILL.md`
- Creating a context pack? → see `context-amortization.md` pack selection section
