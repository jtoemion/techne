---
name: honcho-precompaction-checkpoint
description: Mandatory Honcho checkpoint before session compaction. Preserve durable facts before raw context is discarded.
triggers:
  - honcho before compaction
  - pre-compaction checkpoint
  - session compaction
  - long-term memory
  - critical context
  - checkpoint honcho
---

# Honcho Pre-Compaction Checkpoint

## Lead Rule

Before any session compaction, write the durable facts to Honcho first.

```
extract durable facts → honcho_conclude → verify recall → then compact
```

If Honcho is unreachable, save the same checkpoint to Hermes memory as fallback and report the Honcho failure.

## What to Checkpoint

```
user preferences
project conventions
architecture decisions
HITL boundaries
new mandatory workflow rules
known tool/server blockers
stable file paths
verified test results
```

## Do Not Checkpoint

```
full transcripts
temporary TODO state
every command output
commit SHAs
PR numbers
transient progress logs
```

## Honcho Write Pattern

```python
honcho_conclude(
    conclusion="Judah wants critical context checkpointed to Honcho before compaction.",
    peer="user"
)
```

Write one conclusion per durable fact. Keep conclusions compact and future-useful.

## Fallback Pattern

```python
memory(
    action="replace",
    target="user",
    content="Short durable user preference or project convention.",
    old_text="Existing overlapping memory entry"
)
```

Use fallback only when Honcho is down, not as the primary store.

## Verification

After writing, verify with one of:

```python
honcho_context(peer="user")
honcho_profile(peer="user")
```

If both return empty but writes succeeded, record that Honcho recall may be async. If writes fail, run diagnostics:

```bash
curl http://localhost:8000/health
hermes honcho status
```

## Next Steps

- Need a compact checkpoint? → summarize durable facts, then call `honcho_conclude`
- Honcho write fails? → `curl http://localhost:8000/health`, then use Hermes memory fallback
- Need to make this automatic? → add this skill to `harness/skill-router.yaml` and `always_loaded`
- Need to preserve Techne context too? → `skills/context-amortization.md`
