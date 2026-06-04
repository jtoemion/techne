---
name: implementer
description: How to implement a task correctly. Read before writing any code. Covers pre-flight checks, diff discipline, and gate awareness.
---

# Implementer

## Pre-Flight (before touching any file)

```
1. Read skills/nextjs.md     — gates will reject violations
2. Read skills/typescript.md — gates will reject violations
3. Read memory/mistakes.md   — check if this task type has failed before
4. Locate only the files needed (Glob/Grep — don't browse)
```

## Diff Discipline

```
- Minimum change to satisfy the task
- No cleanup outside task scope
- No speculative abstractions
- No console.log in production paths
- Output: unified diff only
```

## Gate Awareness

The conductor runs `run_all_gates(diff)` on your output.
If it throws `GateViolation`, you get the exact reason and must fix only that.

```python
# What fires against your diff:
gate_no_redirect_outside_middleware(diff)  # redirect() location
gate_no_router_import(diff)                # next/router usage
gate_no_gSSP(diff)                         # getServerSideProps
gate_no_ts_ignore(diff)                    # @ts-ignore/@ts-nocheck
gate_no_console_log(diff)                  # console.log on + lines
```

## Self-Check Before Returning

```bash
git diff --unified=3   # review your own output
grep 'redirect(' diff  # confirm location is middleware.ts
grep 'next/router' diff  # must be zero results
grep '@ts-ignore' diff   # must be zero results
```

## Next Steps

- Gate rejected your diff? → read the exact error, fix only that violation
- Task involves a bug? → `skills/diagnose.md` first
- Unsure about the design? → `skills/grill.md` first
- Design unproven — want to try it cheaply first? → `skills/prototype.md`
- Recurring structural friction, not a one-off? → `skills/improve-architecture.md`
- Change done, opening a PR? → `skills/check-pr.md`
- After implementing → `p.submit_implementation(diff)` → call `print(p.get_status())` → conductor runs `skills/evaluation.md` automatically
