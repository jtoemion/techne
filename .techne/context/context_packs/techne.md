# Techne Context Pack

## Purpose

Use this pack for Techne harness, agent, skill, routing, gate, and pipeline work.

## Core Model

```
Host agent runs reasoning turns.
Techne supplies deterministic routing, gates, task state, verification, and memory.
No agent self-certifies; the loop/parent submits results.
```

## Current Mandatory Flow

```
CONTEXT_PREFLIGHT → IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → DONE
```

`CONTEXT_PREFLIGHT` must refresh `.techne/context/context_hash.txt` before
`IMPLEMENT`.

## Skill Authoring Rule

Always read `skills/writing-skill.md` before creating or modifying skills.

```
skills/writing-skill.md
skills/writing-skill/template.md
skills/writing-skill/checklist.md
```

In-repo skills live under `skills/` and should be committed on a feature branch.

## Worker Read Budget

```
1. .techne/context/project_digest.md
2. .techne/context/file_roles.md
3. .techne/context/commands.md
4. .techne/context/risk_boundaries.md
5. selected .techne/context/context_packs/*.md
6. task files found by targeted Glob/Grep
```

Do not browse the whole repository as a substitute for context.

## Known Pitfalls

```
- Router first-match behavior can hide broader matches; use distinctive keywords.
- Always_loaded skills are injected for every task; keep them compact.
- Gate changes require tests/evals and usually baseline review.
- Existing worktrees/dirty files may be unrelated; stage only intended files.
```

## Next Steps

```
- Need full context rules? → .techne/context/project_digest.md
- Need boundaries? → .techne/context/risk_boundaries.md
- Need file ownership? → .techne/context/file_roles.md
- Done? → back to skills/context-amortization.md