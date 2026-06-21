# Per-Phase External Tracking Doc Pattern

## What

The user may require a scratch document (e.g. `ui-design-ai-slop.md`) that gets
updated after every pipeline phase submit. Each update appends the lessons,
anti-patterns, or findings discovered during that phase.

## When

- The user says "every submit update the X file"
- The user creates a reference doc alongside the pipeline and asks you to keep
  it current
- You're running a redesign/branding/audit task where discovered patterns
  should be recorded for reuse

## How

1. Create the tracking doc at the beginning of the task (in the project root).
2. After each `loop.submit(tid, phase, result)` succeeds, append a structured
   section to the tracking doc with the learnings from that phase.
3. Use write_file for the primary write (avoids patch indentation corruption
   on multi-line inserts).
4. Commit the tracking doc with the final task commit, or keep it uncommitted
   as project memory.

## Example entry format

```
## Additions from <PHASE> phase — <task description>

- **<Anti-pattern or technique title>** — <2-4 sentence explanation of what
      was learned, why it matters, and what concrete parameter/rule/check to
      use next time. Use active voice and specific numbers where possible.>
```

## Why it works

- Each phase of the pipeline produces a different type of insight (RECALL:
  context gaps; IMPLEMENT: tool/technique constraints; CRITIQUE: edge cases;
  RETRO: process improvements). Capturing per-phase preserves the signal
  before it fades.
- The document becomes a durable reference for the next redesign without
  needing a separate skill creation.
- The user can see the doc growing in real-time as phases complete, which
  provides visible proof of progress through the pipeline.
