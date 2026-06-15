---
name: retro-learn
description: Reinforcement-learning retrospective. Analyzes task DB for recurring mistake patterns, weights them by frequency, updates discipline docs and framework MDs. Closes the learning loop — the system gets smarter each run.
---

# Retro-Learn — Reinforcement Learning Retrospective

## When to Use

- After ALL tasks in a plan are complete (or halted)
- When `db.get_mistake_stats()` shows recurring patterns
- Periodically (every 5-10 pipeline runs) even on clean runs

## The Learning Loop

```
  ┌─────────┐     ┌──────────┐     ┌───────────┐     ┌──────────┐
  │ task_db  │────▶│ analyze  │────▶│ weight    │────▶│ update   │
  │ events   │     │ patterns │     │ by freq   │     │ docs     │
  └─────────┘     └──────────┘     └───────────┘     └──────────┘
       ▲                                                    │
       └────────────────────────────────────────────────────┘
                    next run reads updated docs
```

## Step 1: Collect Data

```python
import sys; sys.path.insert(0, "techne/harness")
from task_db import TaskDB

db = TaskDB()
stats = db.get_mistake_stats()

# What you get:
# stats["by_agent"]           → {"implementer": 5, "reviewer": 2, ...}
# stats["by_task"]            → [{id, title, attempts, fail_count}, ...]
# stats["recurring_patterns"] → {"missing null check": 4, "stale closure": 3, ...}
# stats["total_tasks"]        → 47
# stats["total_events"]       → 312
```

Also read:
- `memory/mistakes.md` — structured failure log from Techne
- `memory/eval_history.json` — score trend over time
- `memory/retro_proposals.md` — unapplied proposals from prior retros

## Step 2: Analyze Patterns

### Frequency Analysis

Sort `recurring_patterns` by count. Each pattern that appears 2+ times is a
**candidate for reinforcement**.

```
Pattern                     Count   Action
─────────────────────────   ─────   ──────────────────────
missing null check            4     ADD to implementer rules
stale closure in useEffect    3     ADD to implementer rules
console.log left in           2     ALREADY GATED (verify gate works)
unused import                 1     MONITOR (not yet threshold)
```

### Agent Failure Analysis

Which agent fails most? If `implementer` dominates, the skill rules need
strengthening. If `critique` catches things `reviewer` misses, the review
checklist needs updating.

### Task Complexity Analysis

Tasks with `attempt >= 3` — what made them hard? Was it:
- Ambiguous spec? → improve task decomposition
- Missing context? → improve agent prompts
- Genuinely hard? → acceptable, but document the pattern

## Step 3: Weight the Patterns

Each recurring pattern gets a weight based on frequency:

```
Count 1     → weight: low     (monitor only)
Count 2-3   → weight: medium  (add to skill rules)
Count 4+    → weight: high    (add to skill rules AND create a gate if possible)
```

The weight determines WHERE the reinforcement goes:

```
weight: low    → record in mistakes.md only (observation)
weight: medium → ADD a rule to the relevant skill file + mistakes.md
weight: high   → ADD a rule + propose a gate (harness/plugins/) + mistakes.md
```

## Step 4: Update Discipline Docs

### 4a. Update mistakes.md

For each new pattern, append below the marker:

```markdown
## [GATE_OR_AGENT] — YYYY-MM-DD
- **Error**: <what happened>
- **Cause**: <root cause>
- **Lesson**: <what to do differently>
- **Weight**: low | medium | high
- **Seen**: Nx across M tasks
- **Gate**: yes/no (is there already a gate for this?)
```

### 4b. Update Skill Files

For weight:medium+ patterns, add a rule to the relevant skill:

**implementer.md** — if the pattern is about code the implementer writes:
```markdown
## Reinforced Rules (learned from past failures)
- <rule text>  <!-- weight: high, seen: 4x, added: YYYY-MM-DD -->
```

**reviewer.md** — if the pattern is about something the reviewer should catch:
```markdown
## Additional Checks (learned from past failures)
- <check text>  <!-- weight: medium, seen: 3x, added: YYYY-MM-DD -->
```

**diagnose.md** — if the pattern is about a recurring bug type:
```markdown
## Known Failure Patterns
- <pattern>  <!-- weight: high, seen: 5x, added: YYYY-MM-DD -->
```

### 4c. Update Framework Docs

For patterns specific to the project framework (React, Vite, Svelte, etc.),
add to the SKILL.md "Live Framework Findings" section:

```markdown
#### <Pattern Title> (learned from <N> failures)
<code example showing the wrong way and the right way>
**Why:** <explanation>
```

### 4d. Propose Gates (weight: high only)

If a pattern appears 4+ times and is greppable, propose a gate:

```python
# harness/plugins/learned_gates.py
def gate_no_stale_closure(diff: str) -> None:
    """Reject useEffect with missing deps on mutation objects."""
    # greppable pattern here
```

Write the proposal to `memory/retro_proposals.md` for human review.

## Step 5: Score the Run

Update `memory/eval_history.json` with the run's score. Track the trend:

```
Run 1: 72/100  (3 gate violations, 1 critique critical)
Run 2: 81/100  (1 gate violation, 0 critique)
Run 3: 88/100  (0 violations, 0 critique, clean run)
→ Trend: IMPROVING
```

If the trend is flat or declining despite retro proposals, the proposals
aren't working — flag for human review.

## Output Format

```
RETRO-LEARN REPORT
Run: <pipeline_number> | Tasks: <N> | Events: <M>

PATTERN ANALYSIS:
  <pattern> — count: N — weight: <level> — action: <what was done>

AGENT PERFORMANCE:
  implementer: N failures (top issue: <pattern>)
  reviewer:    N failures (top issue: <pattern>)
  critique:    N critical findings caught

REINFORCEMENTS APPLIED:
  [✓] Added to implementer.md: "<rule>"
  [✓] Added to SKILL.md findings: "<pattern>"
  [→] Gate proposed: "<gate_name>" (pending human review)

SCORE: N/100 (trend: IMPROVING | STABLE | DECLINING)

NEXT ACTIONS:
  - <actionable recommendation>
```

## Hard Constraints

- Never auto-apply gate proposals — humans review before merging
- Weight thresholds are hard: count 1 = low, 2-3 = medium, 4+ = high
- Don't remove existing rules unless they've been clean for 10+ runs
- Every reinforcement must include the evidence (which tasks, how many times)
- If no patterns meet threshold, say "NO CHANGE" — don't manufacture insights

## Integration with Orchestrator

The orchestrator calls retro-learn after all tasks are done:

```python
# After all tasks complete
stats = db.get_mistake_stats()
if stats["recurring_patterns"]:
    # dispatch retro-learn agent
    delegate_task(
        goal="Run retro-learn analysis",
        context=json.dumps(stats),
        toolsets=["file"]
    )
```

## The Reinforcement Contract

```
The system commits to:
1. Every failure is recorded (task_db + mistakes.md)
2. Patterns are weighted by frequency, not opinion
3. Weighted patterns become rules in skill files
4. High-weight patterns become proposed gates
5. The trend is tracked — improvement is measured, not assumed
6. The docs are the system's memory — they get heavier as it learns
```

## Next Steps

- Want to see current stats? → `db.get_mistake_stats()`
- Want to see the trend? → read `memory/eval_history.json`
- Want to apply pending proposals? → `python harness/apply_retro.py`
- Starting a new project? → clear DB + reset mistakes.md (see INSTALL.md §6)
