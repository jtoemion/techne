---
kind: context_doc
subsystem: memory
paths: [memory, .techne/memory]
tags: [ledger, mistakes, wikilinks, recall]
related_skills: [techne, retro-learn]
related_tests: [tests/test_ledger.py, tests/test_docs_skill_wiring.py]
refresh_policy: proposed
---

# Memory Context

## Purpose
Stores durable lessons, mistakes, decisions, disciplines, and the graph indexes that make them recallable.

## Entry points
- memory/ledger.md
- memory/mistakes.md
- memory/wikilinks.json
- .techne/memory/

## Invariants
- lessons should be structured, not buried in freeform retro prose
- graph indexes should unify old memory with workshop-local context
- root memory and workshop memory should not silently diverge forever

## Common failure modes
- RETRO writes insights but nothing indexes them
- workshop-local files and legacy root-memory files get out of sync
- search surfaces everything except the one lesson that matters

## If you change X, also inspect Y
- If you change ledger schema, inspect `harness/ledger.py`, `harness/wikilink.py`, and any search readers.
- If you change workshop memory paths, inspect `.techne/scripts/context_search.py` and `.techne/scripts/refresh_generated_docs.py`.
