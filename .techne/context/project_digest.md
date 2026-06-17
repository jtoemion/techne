# Project Digest

## Identity

Techne is a host-driven AI agent pipeline harness. It supplies routing, gates,
task state, verification, and structured memory. The host agent runs every LLM
turn; Techne does not call an external model.

## Current Mandatory Flow

```
CONTEXT_PREFLIGHT → IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → DONE
```

`CONTEXT_PREFLIGHT` is mandatory before every task. It creates or refreshes
`.techne/context/` and writes `.techne/context/context_hash.txt`.

## Core Files

```
SKILL.md                         entry point for host agents
harness/skill-router.yaml        skill routing table
harness/router.py                YAML router
harness/orchestrator_loop.py     multi-agent loop runner
harness/pipeline_enforcer.py     phase state machine
harness/task_db.py               SQLite task/event persistence
harness/context_preflight.py     context freshness, hash, pack selection
harness/gate_registry.py         gate registry
harness/plugins/builtin_gates.py built-in gate implementations
agents/*.md                      phase agent definitions
skills/*.md                      compact skill cards
tests/*.py                       deterministic stress tests
```

## Commands

```bash
python tests/evals/run_evals.py
python tests/evals/run_evals.py --suite router
python -X utf8 tests/test_adopted.py
python -X utf8 tests/test_context_amortization.py
python -m py_compile harness/context_preflight.py harness/orchestrator_loop.py harness/pipeline_enforcer.py
git diff --check
```

## Landmines

```
- In-repo skills live under skills/ and must be written with write_file, not skill_manage(action='create').
- Always use skills/writing-skill.md when creating or modifying skills.
- Do not let subagents self-certify completion; the parent/loop submits results.
- Do not skip pipeline phases; PipelineEnforcer rejects out-of-order transitions.
- Create a feature branch before changes; do not commit directly to master/main.
- Commit only intended files when the repo already has unrelated dirty work.
```

## Next Steps

```
- Need file ownership? → .techne/context/file_roles.md
- Need commands? → .techne/context/commands.md
- Need boundaries? → .techne/context/risk_boundaries.md
- Need task pack? → .techne/context/context_packs/*.md