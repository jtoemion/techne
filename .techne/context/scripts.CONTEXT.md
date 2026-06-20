---
kind: context_doc
subsystem: scripts
paths: [.techne/scripts]
tags: [context-index, context-search, refresh, generated]
related_skills: [techne, diagnose]
related_tests: [tests/test_workshop_foundation.py]
refresh_policy: proposed
---

# Scripts Context

## Purpose
Holds workshop automation entrypoints used by RECALL and post-work refresh.

## Entry points
- .techne/scripts/context_index.py
- .techne/scripts/context_search.py
- .techne/scripts/refresh_generated_docs.py

## Invariants
- scripts should be runnable directly from the repo
- scripts should fail loudly when workshop prerequisites are missing
- script outputs should be predictable enough for tests and host automation

## Common failure modes
- scripts hardcode the current repo instead of resolving the active workshop root
- scripts write partial JSON on error
- generated indexes refresh globally when only one subsystem changed

## If you change X, also inspect Y
- If you change CLI flags, inspect tests and any host prompt templates that call the scripts.
- If you change search output shape, inspect RECALL consumers and task artifact writers.
