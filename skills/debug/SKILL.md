---
name: debug
description: Use when diagnosing a failure, fixing a bug, or reproducing an issue. WHEN-TO-USE only, no workflow summary.
triggers:
  - "debug issue"
  - "diagnose failure"
  - "fix bug"
  - "phase debug"
---

# Debug

One line: Reproduce before you fix — the symptom might not match the root cause, and knowing the fix first corrupts diagnosis.

## Lead — FIX_OF Pattern

```text
Reproduce → Diagnose → Fix → Verify
RED FIRST: write a test that fails before touching any fix.
If you cannot reproduce, you cannot verify the fix.
```

## Body

```text
FIX_OF:<ticket-id> pattern:
  1. Build feedback loop (failing test, repro script, or CLI)
  2. Confirm symptom matches the reported bug exactly
  3. Generate falsifiable hypotheses
  4. Instrument one at a time, no parallel probes
  5. Write RED test → watch fail → apply minimal fix → watch pass
  6. Clean all debug tags before concluding
```

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "I know what the bug is without reproducing it" | The symptom might not match the root cause. Reproduce first or fix the wrong thing. |
| "No need to reproduce, let me just patch it" | Without a failing test, you cannot verify the fix works. |
| "I know the fix" | Knowing the fix before the diagnosis biases your instrumentation toward confirming it. |
| "I'll write the test after" | After means never in practice. Write it before or the fix is unverified. |

## Red Flags — STOP

- "I know the fix" before reproducing
- Skipping the feedback loop
- Writing the fix before the failing test
- Applying multiple probes in parallel
- "this seems like the issue" without a falsifiable hypothesis

## Next Steps

- Root cause found, fix verified, debug tags removed → `skills/skill-router.yaml`
