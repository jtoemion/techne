# Interactive Pipeline Driving — Session Pattern

How to drive the Techne orchestrator pipeline interactively when working
on a project that does NOT have a full autonomous model backend (you are
the agent doing the model's job for each phase).

## Setup

```python
import sys
sys.path.insert(0, '/home/ubuntu/.hermes/skills/techne/harness')
os.chdir('/path/to/project')

from orchestrator_loop import OrchestratorLoop
from task_db import TaskDB

db = TaskDB('/tmp/project-task.db')
loop = OrchestratorLoop(db)
task = db.create_task(title='...', description='...', discipline='tdd',
                      tags=['...'], phase_mode='full')
tid = task.id
```

### Worktree isolation for pipeline tasks

When starting a pipeline task on an existing repo, create a separate git
worktree on a new branch. This keeps in-flight changes fully isolated from
the main checkout — you can run a dev server on the main repo while making
changes in the worktree, and there's zero risk of committing work-in-progress
to the wrong branch.

```bash
# From the main repo:
git branch feature/my-task master
git worktree add ../my-task-worktree feature/my-task

# Work in ../my-task-worktree, commit there.
# The main repo stays clean and independently runnable.
```

After the pipeline completes and commits, you can push or merge from the
worktree normally. Clean up with `git worktree remove ../my-task-worktree`
and `git branch -d feature/my-task` after merge.

## Per-Phase Flow

```python
# 1. Get next phase
phase = loop.next_phase(tid)

# 2. Get the prompt (for reference)
prompt = loop.get_prompt(tid, phase)

# 3. Do the work, produce the artifact

# 4. Submit
outcome = loop.submit(tid, phase, artifact)
# outcome.action: LoopAction.RUN_PHASE / RETRY / BLOCK_HITL / DONE / FAILED
# outcome.message: feedback text
# outcome.phase: next phase to run (for RUN_PHASE/RETRY)
```

## Phase Artifacts

| Phase | Artifact |
|---|---|
| RECALL | Structured output with HONCHO_CONTEXT, WORKSHOP_CONTEXT, LESSONS, FOCUS |
| IMPLEMENT | Raw git diff (``git diff --unified=3``) |
| CONTEXT_GUARD | File inventory, diff metrics, scope check, CONCLUDE PUNCH LIST |
| CRITIQUE | Emergent bugs, integration risks, test gaps |
| REVIEW | REVIEW RESULT: PASS/SOFT_FAIL/HARD_FAIL + findings |
| VERIFY | Full stdout from build/test command |
| EVAL | Empty string (deterministic, computed from signals) |
| RETRO | 10 structured questions (GOAL..SKILL PROPOSALS) |
| CONCLUDE | HONCHO/DOCS/CONTEXT proof lines |
| REFRESH_CONTEXT | Empty or minimal text (runs a script) |

## Pitfalls

### RECALL gate requires checkpoint state

The gate calls `checkpoint.check_honcho_logged()` which reads from
`.techne/memory/harness-state.json`. A `honcho_conclude()` tool call
alone does NOT set this. You must write it manually:

```python
from checkpoint import read_state, write_state
state = read_state()
state['honcho_conclusion_id'] = 'my-id'
write_state(state)
```

### REFRESH_CONTEXT needs .techne/config.yaml

The script walks up from CWD looking for `.techne/config.yaml`.
Create a minimal one:

```yaml
name: project-name
type: static-site
framework: sveltekit
app_dir: site/
build_cmd: npm run build
build_dir: site/build
```

Add generated dirs to .gitignore:

```
.techne/generated/
.techne/memory/
.techne/tasks/
memory/
```

### Static site: VERIFY via build

No test suite → use `npm run build` stdout. SHA gate accepts it.

## Techniques Discovered During Pipeline Runs

### Variable aliasing for zero-breakage palette swaps

When migrating token values in a CSS-variable-based project, define the old
variable names as `var(--new-name)` aliases in the `:root` block. This means
zero component file changes when the swap is purely value-to-value — every
existing `var(--old-name)` reference automatically resolves through the alias.

```css
:root {
  --color-antique-gold: #B3914F;
  --gold: var(--color-antique-gold);  /* alias — all existing references work */
}
```

Pattern steps:
1. Add the new semantic token with the new hex value.
2. Define each old variable name as `var(--new-token)` immediately below.
3. Build & verify — if all components used CSS variables, nothing breaks.
4. Then sweep for hardcoded hex values and rgba() references in scoped styles
   (see pitfall below).
5. Only update component files that have hardcoded colors, not the ones that
   used the variables.

This reduces a 50-file palette swap to a single `:root` block edit plus
a handful of targeted fix-ups.

### Hardcoded hex + RGBA grep trap

A hex-value grep (`grep -r '#C9A84C' src/`) finds CSS variable definitions and
hardcoded hex colors. It does NOT find `rgba(201, 168, 76, 0.35)` in button
shadows or hover overlay colors. Always run a SECOND grep for the RGB channels
of the old palette's primary accent color:

```
grep -ri 'rgba(201,168,76' src/
```

Common missed locations during palette migration (checked in order):
- Button box-shadow rgba values
- Button hover/focus background overlays
- Input focus ring box-shadows
- Semi-transparent background overlays behind text on images
- SVG inline fill/stroke colors (if SVGs have hardcoded colors)
- Fallback colors in gradient definitions
- Color-stop midpoints in gradient strings

## Reference-Doc Update Pattern

Per user preference: after every `loop.submit()`, update a running
reference document (e.g., `ui-design-ai-slop.md`) with any new
patterns, anti-patterns, or lessons learned during that phase.
This keeps the doc fresh and turns pipeline execution into a
research output, not just a code change.
