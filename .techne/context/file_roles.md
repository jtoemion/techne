# File Roles

## Harness

```
harness/orchestrator_loop.py       drives tasks through phases and RL recording
harness/pipeline_enforcer.py       enforces phase order and HITL blocking
harness/task_db.py                 SQLite task/event database
harness/context_preflight.py       context status, hash, pack selection
harness/gate_registry.py           gate discovery/config registry
harness/gates.py                   GateViolation helpers and legacy re-exports
harness/plugins/builtin_gates.py   built-in gate functions
harness/plugins/pipeline_hooks.py  gate hooks for phase enforcement
harness/reward_log.py              reward signal persistence
harness/prompt_evolution.py        prompt variant selection/evolution
harness/gate_evolution.py          recurring-pattern gate generation
```

## Agents

```
agents/context-preflight.md  creates/refreshes .techne/context before IMPLEMENT
agents/implementer.md        writes minimal code diffs
agents/context-guard.md      audits changed files after implementation
agents/critique.md           predicts emergent bugs from diffs
agents/reviewer.md           security/correctness review
agents/verifier.md           runs tests and records real output
agents/debugger.md           escalates after repeated failures
agents/retro.md              post-run learning summary
```

## Skills

```
skills/context-amortization.md mandatory context preflight and pack rules
skills/writing-skill.md        required when creating/modifying skills
skills/orchestrator.md         parent loop protocol
skills/implementer.md          implementation preflight and diff discipline
skills/diagnose.md             debugging feedback loop
skills/tdd.md                  test-first workflow
skills/grill.md                plan stress-test workflow
skills/evaluation.md           agent-output scoring
```

## Context

```
.techne/context/project_digest.md      repo identity, commands, landmines
.techne/context/file_roles.md          this file
.techne/context/commands.md            command recipes
.techne/context/risk_boundaries.md     HITL and no-go areas
.techne/context/context_hash.txt       freshness marker
.techne/context/context_packs/*.md     targeted task packs
```

## Next Steps

```
- Need commands? → .techne/context/commands.md
- Need boundaries? → .techne/context/risk_boundaries.md
- Need Techne pack? → .techne/context/context_packs/techne.md