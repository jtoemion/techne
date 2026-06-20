---
kind: context_doc
subsystem: harness
paths: [harness]
tags: [pipeline, gates, recall, conclude, refresh]
related_skills: [techne, diagnose]
related_tests: [tests/test_orchestrator_driver.py, tests/test_ledger.py, tests/test_docs_skill_wiring.py]
refresh_policy: proposed
---

# Harness Context

## Purpose
Owns deterministic pipeline behavior, gate execution, reward/eval plumbing, and workshop-side integration points.

## Entry points
- harness/orchestrator_loop.py
- harness/conductor.py
- harness/enforcement.py
- harness/wikilink.py
- harness/workshop.py

## Invariants
- orchestrator decides phase progression
- conductor validates host artifacts before state advances
- workshop scripts should be deterministic enough that RECALL can depend on them

## Common failure modes
- phase logic and workshop refresh drift apart
- retrieval depends on lucky prose instead of deterministic indexes
- project shell writes into the wrong memory directory and fragments recall

## If you change X, also inspect Y
- If you add a new end-phase like REFRESH_CONTEXT, inspect `harness/pipeline_enforcer.py`, `harness/orchestrator_loop.py`, and tests.
- If you change graph output, inspect `harness/wikilink.py`, `.techne/generated/context_index.json`, and search consumers.
