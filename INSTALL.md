# Installing Techne

Plug-and-play setup for dropping Techne into a host agent
(**Claude Code, Hermes, OpenCode**, or any LLM loop).

Techne is **host-driven**: *you* are the model. Techne never calls a model and
needs **no API key**. It supplies the deterministic spine — skill routing, hard
gates, verification, intent checks, scored evals, and structured memory — and
your agent runs each reasoning turn.

---

## 1. Requirements

- **Python 3.10+** (standard library only — no pip install required)
- **git**
- Optional: **PyYAML** (`pip install pyyaml`) for nicer `skill-router.yaml`
  parsing. Not required — `harness/router.py` ships a stdlib fallback parser.

That's the whole dependency list. There is intentionally no `anthropic` /
OpenAI SDK and no network call anywhere in Techne.

> **Before you integrate, read [COMPONENTS.md](COMPONENTS.md).** It catalogs
> every skill, agent, gate, and file you're pulling in, and flags the conflict
> surfaces — the Next.js/TypeScript stack assumption, generic skill-name
> collisions, and root-file ownership. Skip it and the gates may reject valid
> code on a non-Next.js project.

---

## 2. Install

Pick whichever fits how your host consumes code.

### Option A — git submodule (recommended for a host repo)

```bash
cd your-project/
git submodule add https://github.com/jtoemion/techne.git techne
git submodule update --init
```

### Option B — clone standalone

```bash
git clone https://github.com/jtoemion/techne.git
cd techne
```

### Option C — vendor (copy the folder in)

Copy the repo into your project as `techne/`. Keep the directory structure
intact — the harness modules import each other by bare name and resolve paths
relative to their own location.

---

## 3. Verify the install

From the repo root, run the deterministic suites. **No API key, no network.**

```bash
# 3a. All harness modules import with zero dependencies
python -c "import sys; sys.path.insert(0,'harness'); \
import conductor, gate_registry, router, gates, sha_gate, measure, intent_reasoner, \
evaluator, checkpoint, session, mistakes, store, diff_parser; \
print('Techne OK - no SDK needed')"

# 3b. Eval suites (router + gates + intent are deterministic)
python tests/evals/run_evals.py
#   expect: Router 20/20, Gates 27/27, Intent 18/18 = 65/65
#           Pipeline E2E SKIPPED (host-judged)

# 3c. Full test suite
cd tests/
python -X utf8 test_harness.py        # gate + path unit tests
python -X utf8 test_adopted.py        # router, mistakes, checkpoint
python -X utf8 test_evaluator.py      # scoring + report
python -X utf8 test_intent_layers.py  # intent L1/L2 + semantic hook
python -X utf8 test_conductor.py      # full Pipeline, host-driven
python -X utf8 test_synthetic.py      # end-to-end on a fake project
```

If 3a prints `Techne OK` and 3b shows `65/65`, the install is good.

---

## 4. What Techne owns vs what you own

```
techne/
  SKILL.md         ← ENTRY POINT. Your agent reads this first, every task.
  CONTEXT.md       ← domain glossary (YOU fill this for your project)
  skills/          ← compact skill cards the router loads on demand
  agents/          ← phase prompts (implementer/verifier/reviewer/retro/…)
  harness/         ← the deterministic engine (add this dir to sys.path)
  docs/adr/        ← architecture decisions (YOU append as you make them)
  memory/          ← run state: mistakes, eval history, session handoffs
  tests/           ← stress tests + the eval suites
```

- **Techne owns** the harness, the gates, the routing logic, the eval machinery.
- **You own** `CONTEXT.md` (your domain language), `docs/adr/` (your decisions),
  the gate rules in `harness/gates.py` + `harness/skill-router.yaml` (your
  stack's rules), and every reasoning turn at runtime.

For the full element-by-element breakdown — every skill, agent, gate, memory
file, their requirements, and a pre-integration conflict checklist — see
**[COMPONENTS.md](COMPONENTS.md)**.

---

## 5. Two ways to plug in

### Mode 1 — Knowledge layer (read-only, simplest)

Point your agent at `SKILL.md` and let it route into `skills/`. This gives the
agent your conventions, hard rules, and Next-Steps chains with zero code wiring.
Best first step for any host.

> Rule for the host: **read `SKILL.md` first, never browse `skills/` directly.**
> It is the router.

### Mode 2 — Pipeline library (the full loop)

Drive the disciplined pipeline turn by turn. Each phase gives you a prompt to
run as your own model turn; you submit the artifact you produced; Techne runs
the deterministic gates on it.

```python
import sys; sys.path.insert(0, "techne/harness")   # or "harness" if cwd is the repo
from conductor import Pipeline

p = Pipeline.start("add WhatsApp button to product page")

# IMPLEMENT — run p.implement_prompt() as your turn, produce a unified diff
res = p.submit_implementation(host_diff)
while res.status == "RETRY":            # gate rejected it; fix and resubmit
    res = p.submit_implementation(host_fixed_diff)
# res.status is "PASS" or "HALT"

if res.status == "PASS":
    # VERIFY — run p.verify_prompt(), execute the tests, capture stdout
    p.submit_verification(host_test_output)
    # REVIEW — run p.review_prompt(), review the diff
    p.submit_review(host_findings)

# RETRO always runs
p.submit_retro(host_retro_output)

report = p.finalize()                   # scored eval (0-100) + SESSION.md
print(report.format_report())
```

**Host gate injection** -- the host can add custom gates and hooks without
touching core files:

```python
p = Pipeline.start('task')
p.register_host_gate('custom/no-any', my_gate_fn, stack='typescript')
p.add_host_hook('pre', my_pre_hook)   # runs before each gate
p.add_host_hook('post', my_post_hook) # runs after each gate
```

Phase contract:

| Method | You run | You submit | Techne checks |
|---|---|---|---|
| `implement_prompt()` / `submit_implementation(diff)` | the implementer turn | a unified diff | all gates; intent L1/L2 |
| `verify_prompt()` / `submit_verification(out)` | the test run | full stdout | SHA gate (real, unique output) |
| `review_prompt()` / `submit_review(findings)` | the review turn | findings text | HARD_FAIL / drift markers |
| `retro_prompt()` / `submit_retro(out)` | the 7-question retro | retro notes | records for eval |
| `finalize()` | — | — | scores the run, writes SESSION.md |

`PhaseResult.status` is one of `PASS | RETRY | HALT | DONE`. `AgentPrompt` is
`{system, user}` — the system prompt is the matching `agents/*.md` body.

### Optional — call individual tools without the Pipeline

```python
from router import route                      # route(task) -> skill dict | None
from gates import run_all_gates, GateViolation # raises on a rule violation
from measure import run_measurements           # diff focus, scope, intent L1/L2
from intent_reasoner import build_semantic_prompt, parse_semantic_response
from evaluator import evaluate_pipeline_run     # score a run
from store import read_json, write_json         # memory persistence
```

### Optional — host-run L3 semantic intent (no model call inside Techne)

```python
from diff_parser import parse_diff
from intent_reasoner import build_semantic_prompt, parse_semantic_response

prompt = build_semantic_prompt(task, parse_diff(diff))   # {system, user}
reply  = host_run(prompt["system"], prompt["user"])      # YOUR model turn
verdict = parse_semantic_response(reply)                 # IntentVerdict
p.submit_implementation(diff, semantic_verdict=verdict)  # inject it
```

---

## 6. Start clean for a new project

The repo ships with example `memory/` history. For a fresh project, reset the
run state (keep the seed files and their markers):

```bash
# Keep mistakes.md but clear past entries below the marker (the marker is REQUIRED)
printf '%s\n' \
  '# MISTAKES.md — Structured Gate Failure Log' \
  '' \
  '<!-- New entries go below this line -->' > memory/mistakes.md

# Empty the append-only logs
echo '[]' > memory/eval_history.json
echo '[]' > memory/run_log.json

# Clear old session handoffs
rm -f memory/SESSION.md memory/sessions/*.md

# Re-baseline the evals for your repo once your gates/router reflect your stack
python tests/evals/run_evals.py --save-baseline
```

> `memory/mistakes.md` **must exist and contain** the line
> `<!-- New entries go below this line -->` — `harness/mistakes.py` writes new
> entries directly below it and raises if it's missing.

Runtime scratch files (`harness-state.json`, `test_output.txt`,
`latest_eval.txt`, `retro_proposals.md`, per-run eval results) are already
`.gitignore`d.

---

## 7. Make it yours

| To do this | Edit |
|---|---|
| Teach the agent your conventions | `CONTEXT.md` (domain glossary) |
| Add a hard, greppable rule | Drop a `.py` in `harness/plugins/` with `register(registry)` |
| Disable a stack of gates | `harness/gate-config.yaml` -- remove from `active_stacks` |
| Disable a single gate | `harness/gate-config.yaml` -- add to `disabled_gates` |
| Change which skill loads for a task | `harness/skill-router.yaml` |
| Add a new skill card | follow `skills/writing-skill.md`, then add a router entry |
| Record a decision | append to `docs/adr/` using `docs/adr/ADR-FORMAT.md` |

After any change to gates or routing, re-run `python tests/evals/run_evals.py`
and, when intentional, `--save-baseline`. The eval suite is your regression net.

---

## 8. The contract

Techne guarantees it will **never call a model and never need a key**. Every
LLM turn is yours; every gate, score, and memory write is deterministic Python.
That is what makes it portable across Claude Code, Hermes, OpenCode, or any
host loop — plug it in, read `SKILL.md`, and drive.
