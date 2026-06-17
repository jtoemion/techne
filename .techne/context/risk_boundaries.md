# Risk Boundaries

## HITL Required Before Mutation

```
auth/session logic
database schema or migrations
secrets or credentials
deployment configuration
DNS/TLS/certificates
production environment variables
contracts with external services
anything that changes data residency assumptions
```

If a task touches one of these, name the boundary in the context-preflight
report and do not proceed automatically.

## No-Go Areas for Worker Agents

```
- Do not let worker agents browse the entire repo for orientation.
- Do not skip CONTEXT_PREFLIGHT.
- Do not treat subagent self-reports as proof of completion.
- Do not skip VERIFY.
- Do not modify unrelated dirty files already present in the working tree.
- Do not commit directly to master/main.
```

## Context-Preflight Permissions

```
May write:
  .techne/context/project_digest.md
  .techne/context/file_roles.md
  .techne/context/commands.md
  .techne/context/risk_boundaries.md
  .techne/context/context_hash.txt
  .techne/context/context_packs/*.md

May not write:
  source code
  tests
  memory run state
  skill-router.yaml
  harness code
```

## Next Steps

```
- Task touches HITL area? → block and ask Judah before IMPLEMENT
- Need commands? → .techne/context/commands.md
- Need file ownership? → .techne/context/file_roles.md
- Need Techne pack? → .techne/context/context_packs/techne.md