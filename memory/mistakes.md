# MISTAKES.md — Structured Gate Failure Log
# Written by conductor.py on every gate rejection
# Read by retro agent to find systemic patterns
# Read by mistake checker to surface relevant lessons before each task
#
# Format: structured entries with ACTIVE/RESOLVED status
# Adopted from jtoemion/harness-engineering-skills

<!-- New entries go below this line -->
## [2026-06-02T14:57:39Z] CONDUCTOR | TEST-DISCOVERED
**Error**     : AttributeError: 'dict' object has no attribute 'verdict'
**Cause**     : verdict_to_gate() expected IntentVerdict dataclass, got plain dict from full_intent_check
**Lesson**    : when passing data across module boundaries, accept both dict and dataclass
**Gate**      : intent
**Status**    : RESOLVED

## [2026-06-02T14:57:39Z] IMPLEMENT | TEST-DISCOVERED
**Error**     : GATE FAIL [nextjs/redirect]: redirect() on diff line 3 is outside middleware.ts
**Cause**     : agent violated skill rule on first try, retry succeeded
**Lesson**    : redirect() must stay in middleware.ts — gate fires on page components
**Gate**      : nextjs/redirect
**Status**    : ACTIVE

## [2026-06-02T14:59:47Z] CONDUCTOR | TEST-DISCOVERED
**Error**     : TypeError: injected fault — simulating seam bug
**Cause**     : unexpected exceptions were not caught, propagated uncaught from pipeline
**Lesson**    : always use broad except in conductor finally block; log to mistakes.md
**Gate**      : none
**Status**    : RESOLVED

