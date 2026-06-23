---
name: preflight
description: Prepares .techne/context files before every Techne task. Creates or refreshes context packs, project digest, and handoff docs.
---
# Preflight — Context Preparation

Runs before every task to ensure the subagent has fresh situational awareness.

## Required Context Files

- `.techne/context/project_digest.md` — architecture, decisions, state
- `.techne/context/handoff.md` — what's in progress, what's blocked
- `.techne/context/file_roles.md` — file-by-file role map
- `.techne/context/context_hash.txt` — checksum for change detection

## Generated Files

Create these under `.techne/context/context_packs/` as needed:
- `database.md` — schema, migrations, indexes
- `frontend.md` — component tree, routing, stores
- `api.md` — endpoints, auth, error handling

## Refresh Protocol

1. Read existing context files
2. Scan filesystem for structural changes since last hash
3. Update affected context packs
4. Recompute context_hash.txt
5. Commit changes
