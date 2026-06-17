# Techne

**τέχνη** — Greek for *skill, craft, art*. The root of "technology."

A harness engineering environment for disciplined AI agent pipelines. Compact, chainable skills. Hard gates. Structured memory. Scored evaluations.

> **Plugging Techne into a host agent (Claude Code / Hermes / OpenCode)?**
> Start with **[INSTALL.md](INSTALL.md)** (plug-and-play setup, no API key) and
> **[COMPONENTS.md](COMPONENTS.md)** (every skill/gate/element + conflict check).

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

Techne is **host-driven**: your agent harness (Claude Code, Hermes, OpenCode)
is the model. Techne never calls a model and needs no API key — it supplies the
deterministic spine (routing, gates, SHA, intent L1/L2, eval, session, and
mandatory context preflight) and the host runs each phase as its own turn.

```python
import sys; sys.path.insert(0, "harness")
from conductor import Pipeline

p = Pipeline.start("add WhatsApp button to product page")

# IMPLEMENT — host runs p.implement_prompt(), produces a diff
res = p.submit_implementation(host_diff)
while res.status == "RETRY":          # gate violation → host fixes, resubmits
    res = p.submit_implementation(host_fixed_diff)

# VERIFY → REVIEW → RETRO — host runs each *_prompt(), submits the artifact
p.submit_verification(host_test_output)
p.submit_review(host_findings)
p.submit_retro(host_retro_output)

report = p.finalize()                 # scored eval report + SESSION.md
print(report.format_report())
```

Each `*_prompt()` returns `{system, user}` for the host to execute; each
`submit_*()` runs Techne's deterministic gates on what the host produced.
Intent L3 (semantic) is an optional host hook via
`intent_reasoner.build_semantic_prompt` — still no model call inside Techne.

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
CONTEXT_PREFLIGHT → IMPLEMENT → CONTEXT_GUARD → CRITIQUE → REVIEW → VERIFY → DONE
```

Every run produces a scored evaluation report (0-100) saved to `memory/latest_eval.txt`.
