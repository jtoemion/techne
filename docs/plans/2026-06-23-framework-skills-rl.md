# Framework Skills — RL-Backed Self-Improvement

Date: 2026-06-23
Author: Megumi Kato
Status: DRAFT — extension to 2026-06-23-grpo-production-plan.md

## Problem

The framework-specific skill files (`skills/react.md`, `skills/svelte.md`,
`skills/nextjs.md`, `skills/typescript.md`, `skills/react-vite/SKILL.md`)
are static documents. They don't learn from agent experience.

When an agent discovers a new framework pitfall during a real task, that
knowledge should flow back into the framework skill file automatically —
so the next agent working on the same framework doesn't hit the same bug.

Currently:
```
stack_detect → loads static skill → agent works → pitfall found →
  → nothing happens (skill stays static)
```

Target:
```
stack_detect → loads static skill → agent works → pitfall found →
  → reward_log.record(skill="react") →
  → post_run_evolve() → propose_skill_edits() →
  → PROPOSE ADD to skills/react.md →
  → Human confirms → skill improves for next agent
```

## Framework → Skill File Mapping

The mapping already exists in `skills/skill-router.yaml` under `stack_loaded`:

```yaml
stack_loaded:
  nextjs:     "skills/nextjs.md"
  react:      "skills/react.md"
  svelte:     "skills/svelte.md"
  sveltekit:  "skills/svelte.md"
  typescript: "skills/typescript.md"
  firestore:  "skills/diagnose/firestore.md"
  netlify:    "skills/diagnose/netlify.md"
```

This same mapping must be used by the RL system to know which skill file
to propose edits for. The `stack_detect` module returns tags like `react`,
`svelte`, `nextjs` — these are also the skill file names (minus the path).

**No change needed here** — the mapping is correct as-is. The gap is that
the reward system never receives the stack tag information.

## What Needs to Change

### 1. Wire stack tags into reward recording

**File:** `harness/orchestrator_loop.py` in `submit()`

When recording a reward, read the detected stack tags for the project
and include them:

```python
from stack_detect import detect_stack

# When recording reward (inside submit() or the host code)
stack_tags = detect_stack(project_root)
# Include the primary framework tag as the reward skill
primary_skill = _pick_primary_skill(stack_tags)
# e.g. "react" from {"react", "typescript", "vite"}
```

The `_pick_primary_skill()` helper chooses the most specific tag:
prefer `sveltekit` over `svelte`, `nextjs` over `react`. `vite` and
`typescript` are infrastructure, not primary skills.

This gives the RL system the connection: "this task was on a React
project, so improvements should target skills/react.md."

### 2. Extend propose_skill_edits() with framework awareness

**File:** `harness/grpo.py`

The current `propose_skill_edits()` already targets `skills/{skill}.md`.
The `skill` field in the reward comes from the task's tags or discipline.
With change #1, it now comes from `detect_stack()` as well.

The proposal generation needs one enhancement: when the skill is a
framework name (react, svelte, nextjs, typescript), the proposal text
should include:
- The framework name
- The specific pitfall found (from review findings or gate violations)
- The fix pattern
- An example code snippet (from the diff)

This means `propose_skill_edits()` should include the actual review
finding text in the proposal, not just aggregate stats.

**Current proposal text:**
```
Skill-based GRPO edit: skill **react** under task type **ui**
Advantage: 0.35
Proposed improvement:
- append actionable guidance to skills/react.md
```

**Target proposal text:**
```
Skill-based GRPO edit: skill **react** under task type **ui**
Advantage: 0.35
Runs: 3
Review finding repeated across runs:
  "useEffect missing resetMutation in dependency array"
Proposed addition to skills/react.md:
  ## useEffect with React Query mutations — include mutation in deps
  When using useMutation().reset() inside useEffect, always include
  the mutation object in the dependency array.
```

### 3. Framework skill files need a "latest additions" section

**Files:** `skills/react.md`, `skills/svelte.md`, `skills/nextjs.md`,
`skills/typescript.md`, `skills/react-vite/SKILL.md`

Each framework skill file gets a new section at the bottom:

```markdown
## RL-Proposed Additions

<!-- New RL-generated entries appear here. Reviewed and confirmed
     before being promoted to the main body above. -->

<!-- Template for new entries:
### [YYYY-MM-DD] Pitfall description
- **Source:** GRPO proposal from task ABC123
- **Evidence:** Review finding "..." repeated N times across M tasks
- **Pattern:** ...
-->
```

This section is where `propose_skill_edits()` writes new entries. After
human review, entries get promoted to the main body of the skill file.
The section serves as staging area — same pattern as `retro_proposals.md`.

### 4. Pipeline integration for framework skills

Add a new phase or step after `post_run_evolve()` that specifically
checks if the generated proposals target a framework skill and routes
them there instead of the generic `retro_proposals.md`.

Right now all proposals go to `retro_proposals.md`. Framework-specific
proposals should go to the framework skill file's RL-Proposed Additions
section instead.

**File:** `harness/grpo.py` — add `propose_framework_edits()`

```python
def propose_framework_edits(
    reward_log,
    stack_tags: set[str],
    threshold: float = ADVANTAGE_THRESHOLD,
) -> list[dict]:
    """
    Like propose_skill_edits but writes directly to the framework skill
    file's RL-Proposed Additions section instead of retro_proposals.md.
    
    Only processes skills that match detected stack tags (react, svelte, etc.).
    Others go through the normal retro_proposals.md path.
    """
```

## Implementation Order

| # | Change | File | Risk |
|---|--------|------|------|
| 1 | Wire stack tags into reward recording | orchestrator_loop.py | Low |
| 2 | Enhance propose_skill_edits with finding text | grpo.py | Low |
| 3 | Add RL-Proposed Additions section to framework skills | skills/{react,svelte,nextjs,typescript}.md | None |
| 4 | Add propose_framework_edits() routing | grpo.py | Low |

Total: 4 changes, ~150 lines.

## Existing Framework Skills Status

| Skill | Lines | RL-ready? | Current content |
|-------|-------|-----------|-----------------|
| skills/react.md | 61 | Yes — has multiple documented pitfalls | useEffect deps, mutation refs, eslint guards |
| skills/svelte.md | 68 | Yes — has multiple documented pitfalls | $state mutation, Dexie duality, dev guards, dynamic imports |
| skills/nextjs.md | 49 | Yes — basic router rules | Middleware, metadata, redirect patterns |
| skills/typescript.md | 46 | Yes — basic type safety | Generics, strict mode, error handling |
| skills/react-vite/SKILL.md | 89 | Partial — sub-skill, not a stack_loaded | Vite build config, TanStack Query |

## How It Works End-to-End

```
1. Agent starts task in React project
2. stack_detect() returns {"react", "typescript", "vite"}
3. skill-router loads skills/react.md (current best practices)
4. Agent works → encounters useEffect deps issue → gate catches it
5. Reward recorded with skill="react", review finding captured
6. submit() → DONE → post_run_evolve() → compute_batch_advantages()
7. propose_skill_edits() finds high advantage for (task_type="ui", skill="react")
8. propose_framework_edits() writes PROPOSE ADD to skills/react.md
   under the ## RL-Proposed Additions section
9. Human reviews the addition → confirms or rejects
10. Next agent working on React gets the updated skill

Each iteration sharpens the framework skill against real task experience.
```

## Pitfalls

- **Don't let RL proposals overwrite human-written content.** The
  RL-Proposed Additions section is always at the bottom, below the
  human-curated main body. Only promote entries after human review.

- **Framework files are loaded every session in that stack.** A bad
  proposal that gets promoted could degrade performance across all
  React tasks. Keep the human-in-the-loop gate from the main RL system.

- **stack_detect relies on package.json.** A project without a JS
  manifest won't get framework skills loaded. This is correct behavior
  — don't force framework skills on non-framework projects.
