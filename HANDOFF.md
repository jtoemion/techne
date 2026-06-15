# Techne RL Pipeline — Handoff Document

**Purpose**: Give this to any agent (Claude, Hermes, Codex, etc.) so they can
pick up development immediately. Everything they need is here.

**Last updated**: 2026-06-15

---

## What This Is

Techne is a host-driven AI agent harness. It never calls a model — the host
agent IS the model. Techne provides the deterministic spine: skill routing,
hard gates, pipeline enforcement, task tracking, and now reinforcement learning.

The RL mechanism learns from each pipeline run to:
1. Select better prompts for each task type (prompt evolution)
2. Generate new gates from recurring failure patterns (gate evolution)
3. Score critique vs reviewer accuracy (cross-agent feedback)

## Architecture

```
techne/
  SKILL.md              ← entry point (router)
  skills/               ← skill cards (orchestrator, tdd, diagnose, etc.)
  agents/               ← agent definitions (implementer, reviewer, etc.)
  harness/              ← the engine
    enforcement.py      ← SHARED deterministic core (gates/scope/SHA) — both drivers use it
    conductor.py        ← Pipeline driver: single-task, turn-by-turn (delegates to enforcement)
    orchestrator_loop.py ← Pipeline driver: multi-task loop + RL (delegates to enforcement)
    task_db.py          ← SQLite task + event database
    pipeline_enforcer.py ← phase transition state machine
    reward_log.py       ← composite reward tracking (real signals from enforcement)
    prompt_evolution.py ← prompt variant selection
    gate_evolution.py   ← auto-gate from patterns
    gate_registry.py    ← extensible gate registry
    gates.py            ← GateViolation, built-in gates
    plugins/            ← gate plugins (builtin, security, pipeline_hooks)
    ...
  memory/               ← runtime state
    tasks.db            ← task database (task_db.py)
    rewards.db          ← reward log (reward_log.py)
    mistakes.md         ← structured failure log
    eval_history.json   ← score trend
```

## The Pipeline

```
IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → DONE
                                              ↘ BLOCKED → HITL → resume
                                              ↘ DEBUG → IMPLEMENT (retry)
```

Enforced by `pipeline_enforcer.py` — you can't skip phases.

## The RL Loop

```
Per task:
  1. Select best prompt variant (prompt_evolution.py)
  2. Run implementation
  3. Record critique predictions
  4. Record review findings
  5. Compute composite reward (reward_log.py)
  6. Score critique vs review (cross-agent)

Per run (after all tasks):
  7. Evolve prompts (keep winners, retire losers)
  8. Check gate candidates (pattern count >= 3?)
  9. Auto-approve gates with evidence
  10. Update skill files with reinforced rules
```

## What's Built

| Module | Status | What it does |
|--------|--------|--------------|
| enforcement.py | ✓ solid | Shared core: run_gates / measure_scope / verify_tests (both drivers) |
| task_db.py | ✓ solid | SQLite task + event tracking |
| pipeline_enforcer.py | ✓ solid | Phase state machine, HITL blocking |
| conductor.py | ✓ solid | Single-task driver, delegates to enforcement.py |
| orchestrator_loop.py | ✓ solid | Multi-task loop + RL, real gate/SHA signals via enforcement.py |
| reward_log.py | ✓ solid | Composite scoring, cross-agent, real signals |
| prompt_evolution.py | ✓ works | Variant selection, basic evolution |
| gate_evolution.py | ✓ works | Pattern → regex → gate generation |
| pipeline_hooks.py | ✓ solid | Gate hooks for enforcement |

### The merge (2026-06-15)

conductor and orchestrator_loop were two drivers over the same pipeline, but
only conductor ran real deterministic checks; the RL loop fed hardcoded
`gate_pass=True` / `scope_clean=True` into the reward log. `enforcement.py`
now holds the three checks both need (`run_gates`, `measure_scope`,
`verify_tests`); conductor delegates to it (behavior-preserving) and the loop
records the **real** gate / SHA / scope signals. `synthetic_bootstrap.py`
seeds the real `rewards.db` so evolution has signal from the first run.

## What's Weak (patch these)

### 0. Orchestrator is still host-driven
**File**: `orchestrator_loop.py`
**Problem**: The loop generates prompts and the host executes them — same
pattern as conductor.py. Subagents aren't autonomous. The parent agent
does all the work.
**Fix**: Call `delegate_task` from the loop runner. Each phase dispatches
a real subagent with its own context. The loop receives output, scores it,
decides next phase. Parent only handles HITL.
**Priority**: HIGH — this is the fundamental architecture issue.

### 1. Pattern matching is shallow
**File**: `reward_log.py` → `_patterns_overlap()`
**Problem**: Word-level intersection misses paraphrases. "missing null check"
and "null pointer not caught" share only "null".
**Fix options**:
  - SHA256 for exact matching in gate_evolution (gates are greppable anyway)
  - Keep fuzzy for cross-agent scoring but use synonym dict
  - Or use embeddings if available (sentence-transformers)
**Priority**: Medium — works for exact-ish matches, fails on paraphrases.

### 2. No multi-variant GRPO
**File**: `orchestrator_loop.py` → `_submit_implement()`
**Problem**: Currently runs ONE variant per task. GRPO needs N variants scored.
**Fix**: Add variant loop in `_submit_implement`:
```python
for variant_name in self.evolution.get_variants(task_type):
    prompt, temp = self.evolution.get_variant_prompt(task_type, "implementer", base)
    result = host_execute(prompt, temperature=temp)
    score = score_variant(result)
    self.reward_log.record(task_type, variant_name, score, ...)
# pick winner
```
**Priority**: High — this is the core of GRPO.

### 3. Gate regex is brittle
**File**: `gate_evolution.py` → `_pattern_to_regex()`
**Problem**: Falls back to "any 2 of 3 words" for unknown patterns.
**Fix**:
  - Use SHA256 on normalized pattern for deterministic matching
  - Learn regex from positive/negative examples (regex induction)
  - Or just use the raw finding text as a grep pattern (simplest)
**Priority**: Medium — known patterns work, novel ones don't.

### 4. Composite weights are fixed
**File**: `reward_log.py` → `WEIGHTS`
**Problem**: gate_pass=0.25, test_pass=0.25, etc. are arbitrary.
Should be per-task-type (auth needs higher security weight, etc.).
**Fix**: Store weights in reward_log, tune from data:
```python
# After 10+ runs per type, compute which components correlate with
# overall success and adjust weights accordingly.
```
**Priority**: Low — fixed weights are fine for now.

### 5. No stored diffs for gate testing
**File**: `gate_evolution.py` → `test_candidate()`
**Problem**: Gate testing falls back to "count >= 3 → approve" without
testing against actual past diffs.
**Fix**: Store diffs in task_db events, pass to `test_candidate()`:
```python
# In task_db, store diff in the IMPLEMENT event's findings field
# In gate_evolution, retrieve and test against stored diffs
```
**Priority**: Medium — needed for proper gate validation.

### 6. Prompt evolution doesn't generate new prompts
**File**: `prompt_evolution.py` → `evolve()`
**Problem**: Only tweaks temperature and appends suffixes. Doesn't
generate genuinely new prompt variants.
**Fix**: Template-based generation:
```python
templates = [
    "Write code that {approach}. {constraint}. {focus}.",
    "You are an expert in {domain}. {instruction}. {rule}.",
]
# Generate variants by filling templates with different parameters
# Score each variant on held-out tasks
```
**Priority**: Low — selection from existing variants works for now.

## What's Not Built (future work)

1. **Embedding-based similarity** for pattern matching
2. **Meta-optimization** of reward weights per task type
3. **Diff storage** in task_db for gate testing
4. **Multi-model support** (different models for implementer vs reviewer)
5. **Ablation studies** (which component of composite score matters most?)

## How to Run

```bash
# Verify everything imports
cd techne/
python -c "import sys; sys.path.insert(0, 'harness');
from enforcement import run_gates, measure_scope, verify_tests;
from task_db import TaskDB; from pipeline_enforcer import PipelineEnforcer;
from orchestrator_loop import OrchestratorLoop; from reward_log import RewardLog;
from prompt_evolution import PromptEvolution; from gate_evolution import GateEvolution;
from synthetic_bootstrap import SyntheticBootstrap; from conductor import Pipeline;
print('All OK')"

# Bootstrap RL with synthetic data (run this FIRST — seeds memory/rewards.db, idempotent)
python harness/synthetic_bootstrap.py

# Run the test suite (114 pass) and evals (73/73)
python -m pytest tests/ -q
python tests/evals/run_evals.py

# Smoke test the drivers (real gates + SHA gate run)
python harness/enforcement.py
python harness/orchestrator_loop.py
```

## Key Design Decisions

1. **Host-driven**: Techne never calls a model. The host IS the model.
2. **Deterministic enforcement**: Pipeline phases are code, not agent memory.
3. **Cross-agent scoring**: Critique and reviewer score each other.
4. **Evidence-based gates**: Gates emerge from patterns, tested against history.
5. **SQLite everything**: tasks.db, rewards.db — queryable, append-only, crash-safe.

## Coding Conventions

- Python 3.10+ (type hints with `|`, not `Optional`)
- Standard library only (no pip deps — PyYAML optional)
- All modules importable standalone (`if __name__ == "__main__"` smoke tests)
- Gate plugins: `register(registry)` function in `harness/plugins/*.py`
- Agent definitions: Markdown with YAML frontmatter in `agents/*.md`
- Skill definitions: Markdown in `skills/*.md`

## Git Workflow

- Feature branches, never commit to master directly
- PR when done
- `python tests/evals/run_evals.py --save-baseline` after gate/router changes
