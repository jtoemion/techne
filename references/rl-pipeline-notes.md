# RL Pipeline Notes

Field notes from real Techne pipeline runs. These are operating rules, not vibes.

## What worked

- Keep task IDs as the unit of work. The task board is the dashboard.
- Require real gates: IMPLEMENT diff gate, CONTEXT_GUARD, CRITIQUE, REVIEW, VERIFY SHA gate, EVAL, RETRO.
- Use diverse model providers where available. Different models catch different mistakes.
- Keep tests as the ratchet. Green tests are evidence; prose is not.

## Mandatory ergonomics learned from real runs

### 1. IMPLEMENT returns a diff, not prose

The implementer must return raw unified diff only:

```text
diff --git a/file b/file
--- a/file
+++ b/file
@@ ...
+change
```

No summary. No markdown fence. No “I changed X”. The diff gate rejects prose-only output and wastes a phase roundtrip.

### 2. Do not broaden types

When editing typed code, match the touched file's current typing style.

Hard rule:

```text
Do not introduce `any`, `unknown as`, broad casts, or typed escape hatches unless the original file already used that exact escape hatch and the task requires preserving it.
```

CRITIQUE and REVIEW should compare the diff against the pre-edit file and flag type-narrowing regressions.

### 3. CRITIQUE follow-ups become tasks immediately

Critique may report pre-existing or out-of-scope issues. If they are real work, the critique output must include explicit task lines:

```text
FOLLOW_UP_TASKS:
- FOLLOW_UP_TASK: Add Convex index for users.by_email lookup
```

The orchestrator turns those lines into child tasks tagged `critique-follow-up`. Ordinary bullets are not auto-tasked.

### 4. Honcho after every submit

The host should checkpoint after every `loop.submit()`, not only after whole tasks. Use `run_plan(..., on_submit=...)` for that hook.

Minimum checkpoint contents:

```text
<task_id> <phase> -> <outcome.action>; next=<outcome.phase>; message=<short message>
```

This preserves retry/HITL state if the session compacts at 90–95k tokens.

### 5. PR base preflight before opening or trusting a PR

When target history was squash-merged, branch follow-up work from the target base, not from `main`.

Preflight:

```bash
gh pr view <N> --json baseRefName,headRefName,additions,deletions,changedFiles
gh pr diff <N> --stat
git merge-base --is-ancestor origin/<baseRefName> HEAD || echo "wrong base"
```

A surprise 100+ file diff is a stop sign. Close/rebase/cherry-pick before review.

### 6. Stagger long queues

For a queue of independent tasks, start the next task's IMPLEMENT when the previous task enters VERIFY. Do not wait for the previous task to reach DONE before starting context-safe independent work.

Guardrails:

- Only stagger independent tasks.
- Never run two IMPLEMENT phases that touch the same files.
- Keep VERIFY serialized if it mutates shared state.
- Still submit every phase through the conductor.

### 7. Verify-gate wording

The SHA gate needs actual pass indicators. Verification summaries should include real command output with terms like:

```text
RESULTS: 25/25 passed -- all clear
0 errors
```

Do not rely on architecture explanations as verification.

## Current minimax default

Use the official MiniMax OpenAI-compatible endpoint:

```text
provider: minimax
model: MiniMax-M2.7
base_url: https://api.minimax.io/v1
env: MINIMAX_API_KEY
```
