---
kind: context_doc
subsystem: root
paths: [harness, agents, skills, tests, docs, references, .techne]
tags: [workshop, pipeline, memory, retrieval]
related_skills: [techne, diagnose, writing-skill]
related_tests: [tests/test_orchestrator_driver.py, tests/test_docs_skill_wiring.py]
refresh_policy: proposed
---

# Root Context

## Purpose
Techne is a project-attached engineering workshop around a disciplined multi-phase pipeline.

## Entry points
- harness/orchestrator_loop.py
- harness/conductor.py
- harness/wikilink.py
- .techne/scripts/

## Invariants
- pipeline state changes belong to the orchestrator/conductor, not agents improvising their own flow
- durable lessons should survive the task and be discoverable later
- generated knowledge belongs under `.techne/generated/`; human-authored subsystem context belongs under `.techne/context/`

## Common failure modes
- memory is updated but retrieval is not, so lessons exist but are not recalled
- docs are written as prose blobs with no subsystem edges, so search becomes decorative
- repo-root detection drifts to the wrong `.git` if code walks from the wrong path

## If you change X, also inspect Y
- If you change recall, inspect `.techne/scripts/context_search.py`, `harness/orchestrator_loop.py`, and workshop indexes.
- If you change durable memory, inspect `harness/ledger.py`, `harness/mistakes.py`, and `harness/wikilink.py`.
- If you change generated workshop docs, inspect `.techne/scripts/refresh_generated_docs.py` and `.techne/generated/`.
