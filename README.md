# Techne

**τέχνη** — Greek for *skill, craft, art*. The root of "technology."

A harness engineering environment for disciplined AI agent pipelines. Compact, chainable skills. Hard gates. Structured memory. Scored evaluations.

## Structure

```
techne/
  SKILL.md          ← entry point — read this first
  skills/           ← compact reference cards, each with Next Steps chains
  agents/           ← declarative agent definitions (conductor, implementer, verifier, reviewer, retro)
  harness/          ← Python enforcement layer (gates, SHA, conductor, router, evaluator)
  memory/           ← mistakes log, run log, eval history (append-only)
  tests/            ← stress tests for every component
```

## Quick Start

```bash
cd harness/
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
python conductor.py "your task description"
```

## Run Tests

```bash
cd tests/
python -X utf8 test_harness.py    # gate unit tests
python -X utf8 test_synthetic.py  # end-to-end with fake project
python -X utf8 test_adopted.py    # skill router, mistakes, checkpoint
python -X utf8 test_evaluator.py  # scoring and report generation
```

## Skills Chain

Each skill is a reference card that points to the next:

```
SKILL.md → implementer.md → nextjs.md / typescript.md
         → diagnose.md    → implementer.md (after root cause found)
         → tdd.md         → grill.md (if interface unclear)
         → grill.md       → implementer.md (after design locked)
```

## Pipeline

```
IMPLEMENT → gates.py → VERIFY → sha_gate.py → REVIEW → RETRO → EVALUATE
```

Every run produces a scored evaluation report (0-100) saved to `memory/latest_eval.txt`.
