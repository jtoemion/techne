# Techne — Component Catalog & Compatibility

Read this **before** integrating. It lists every element you are pulling in,
what each one requires, and where it can collide with skills or files already
in your host system.

---

## TL;DR — the three things that cause conflicts

1. **Stack lock-in.** Out of the box, Techne assumes a **Next.js (App Router) +
   TypeScript** project. Five hard gates and two always-loaded skills enforce
   that stack. **On any other stack (Python, Go, Rails, plain JS…) the gates
   will false-reject correct diffs.** See [Adapting to your stack](#adapting-to-your-stack).
2. **Generic skill names.** `implementer`, `diagnose`, `tdd`, `grill` are common
   names that may shadow or duplicate skills you already have. See
   [Name & trigger collisions](#name--trigger-collisions).
3. **Root-file ownership.** Techne expects to own `SKILL.md`, `CONTEXT.md`,
   `docs/adr/`, and `memory/` at its root. If you vendor it into a project that
   already has these names, namespace Techne under its own folder.

**Safe default:** install Techne in its **own subdirectory** (`techne/`) so its
`SKILL.md`, `CONTEXT.md`, gates, and memory never collide with your host's.

---

## Skills catalog

All skills live in `skills/` as Markdown. Your agent reads `SKILL.md` first (the
router), which points into these. Loading a skill = reading a file; it changes
the agent's instructions, not your code.

| Skill | What it does | Requires | Writes to | Conflict risk |
|---|---|---|---|---|
| **implementer** | How to implement a task: pre-flight, minimal-diff discipline, gate awareness | Reads `nextjs.md`, `typescript.md`, `memory/mistakes.md` | — | Med — generic name; assumes the Next.js/TS gates |
| **diagnose** | Disciplined 6-phase debugging (feedback loop → reproduce → hypothesize → instrument → fix+test → cleanup) | — | — | Med — name/triggers overlap a host "debug" skill |
| **tdd** | Test-first, vertical slices; good-vs-bad test guidance | — | — | Med — overlaps a host "testing" skill |
| **grill** | Stress-test a plan against the codebase, one question at a time | Reads `CONTEXT.md`, `docs/adr/` | **`CONTEXT.md`**, **`docs/adr/`** | Med — writes shared docs |
| **persona-brainstorm** | Multi-persona discovery dialogue → surfaces one improvement as ADRs | — | **`CONTEXT.md`**, **`docs/adr/`**, `SESSION.md` | Low name / Med file writes |
| **writing-skill** | How to author a new Techne-style skill (inverted-pyramid, Next Steps chain) | — | — | Low — meta |
| **prototype** | Throwaway code that answers ONE design question (logic vs UI branch) | — | optional `docs/adr/` | Low — generic name |
| **improve-architecture** | Find deepening opportunities (shallow → deep modules); explore → grill → ADR | Reads `CONTEXT.md`, `docs/adr/` | **`CONTEXT.md`**, **`docs/adr/`** | Low name / Med file writes |
| **check-pr** | One-pass PR triage: checks, comments, description → report → optional fix | `gh` (or `glab`/`p4`) authenticated | PR threads (on fix) | Med — needs a VCS CLI |
| **greploop** | Iterate a PR until 5/5 + zero unresolved (max 5 iters) | `gh` + **Greptile** on the repo | PR (push/comments) | Med — vendor + CLI dep |
| **evaluation** | Post-run scoring of a pipeline (5 dimensions, 0–100) | The harness eval machinery | `memory/eval_history.json`, `memory/latest_eval.txt` | Low |
| **nextjs** ⚠ | **Always-loaded.** Next.js App Router hard rules — backs 4 gates | Project **is** Next.js App Router | — | **High off-stack** |
| **typescript** ⚠ | **Always-loaded.** TS suppression rules — backs the `@ts-ignore` gate | Project **is** TypeScript | — | **High off-stack** |

### Sub-skills (loaded only when their parent points to them)

```
diagnose/feedback-loop.md          10 loop strategies + non-deterministic bugs
persona-brainstorm/personas.md     the four personas + rules
persona-brainstorm/loop.md         loop mechanics, pause/resume
persona-brainstorm/adr.md          ADR template + when-to-write
tdd/interface.md                   choosing the interface to test
tdd/mocking.md                     when/how to mock
writing-skill/template.md          copy-paste skill scaffold
writing-skill/checklist.md         pre-merge skill review
```

---

## Agents catalog

`agents/*.md` are **declarative subagent definitions** — frontmatter (model,
tools) + a system-prompt body. Techne hands the body to your host as the
`system` prompt for each phase; **the `model:` field is advice for your host to
map to its own model.** Techne does not call these models itself.

| Agent | Role | Declared model | Declared tools |
|---|---|---|---|
| **conductor** | Orchestrates phases; delegates, never edits | `claude-sonnet-4-6` | Agent |
| **implementer** | Writes/edits code from a task spec | `claude-sonnet-4-6` | Read, Glob, Grep, Edit, Write, Bash |
| **verifier** | Runs tests, captures real output for the SHA gate | `claude-sonnet-4-6` | Read, Bash |
| **reviewer** | Read-only review for security/correctness/rule compliance | `claude-sonnet-4-6` | Read, Glob, Grep |
| **retro** | 7-question retrospective; proposes skill edits | `claude-haiku-4-5-20251001` | Read, Write |

> If your host can't use these exact model IDs, treat `model:` as "use a capable
> coding model" (implementer/verifier/reviewer/conductor) or "a cheap fast
> model" (retro), and map accordingly.

---

## Gates catalog ⚠ (the real conflict surface)

`harness/gates.py` runs `run_all_gates(diff)` and **raises `GateViolation`** on a
match. These are **opinionated and stack-specific**. All five assume Next.js +
TypeScript:

| Gate | Rejects | Assumes |
|---|---|---|
| `gate_no_redirect_outside_middleware` | `redirect(` outside `middleware.ts` | Next.js routing |
| `gate_no_router_import` | imports from `next/router` | Next.js App Router |
| `gate_no_gSSP` | `getServerSideProps` | Next.js App Router |
| `gate_no_ts_ignore` | `@ts-ignore` / `@ts-nocheck` | TypeScript |
| `gate_no_console_log` | added `console.log` lines | JS/TS conventions |

**If your project is not Next.js/TypeScript, these will fire on valid code.**
You must edit `harness/gates.py` to remove/replace them with your stack's rules
(see below). The gate *engine* (greppable rule → raise → eval) is reusable; the
*specific rules* are not.

---

## Harness modules (the deterministic engine)

`harness/` — Python 3.10+, standard library only (PyYAML optional). Add this dir
to `sys.path`. Modules import each other by bare name.

| Module | Provides | Notes |
|---|---|---|
| `conductor.py` | `Pipeline` host-driven state machine | The orchestration entry point |
| `router.py` | `route(task)` → skill dict | Reads `skill-router.yaml`; stdlib fallback if no PyYAML |
| `gates.py` | `run_all_gates(diff)`, `GateViolation` | **Stack-specific — customize** |
| `sha_gate.py` | `gate_test_output(...)` | Verification integrity (real, unique test output) |
| `diff_parser.py` | `parse_diff(diff)` → structured facts | Feeds intent reasoning |
| `measure.py` | `run_measurements(task, diff)` | Diff focus, scope creep, intent L1/L2 |
| `intent_reasoner.py` | L2 structural verdict; L3 host hook (`build_semantic_prompt`, `parse_semantic_response`) | No model call inside |
| `evaluator.py` | `evaluate_pipeline_run(...)` → scored report | Writes `eval_history.json` |
| `checkpoint.py` | run/verification state | Uses `store` |
| `mistakes.py` | structured failure log + relevance match | Needs `memory/mistakes.md` marker (below) |
| `session.py` | `SESSION.md` handoff log | Tool-agnostic markdown |
| `apply_retro.py` | apply retro proposals to skills | Closes the learning loop |
| `store.py` | `read_json` / `write_json` | Shared persistence service |

---

## Memory & files

| Path | Kind | Note |
|---|---|---|
| `SKILL.md` | entry | Router the agent reads first |
| `CONTEXT.md` | yours | Domain glossary; `grill`/`persona-brainstorm` write here |
| `docs/adr/` | yours | Decisions; `ADR-FORMAT.md` is the template |
| `harness/skill-router.yaml` | config | Task → skill routing + always-loaded list |
| `memory/mistakes.md` | seed | **Must contain** `<!-- New entries go below this line -->` or `mistakes.py` raises |
| `memory/eval_history.json` | runtime | Append-only scores (seed `[]`) |
| `memory/SESSION.md`, `memory/sessions/` | runtime | Handoff logs |
| `memory/harness-state.json`, `test_output.txt`, `latest_eval.txt`, `retro_proposals.md` | scratch | `.gitignore`d; regenerated per run |

---

## Name & trigger collisions

`harness/skill-router.yaml` fires a skill when a task contains its **condition
keywords**. If your host has its own router or skills, these overlap:

| Techne skill | Trigger keywords (abbrev.) | Likely host overlap |
|---|---|---|
| techne/diagnose | bug, broken, throwing, failing, regression, debug | a "debug" / "incident" skill |
| techne/writing-skill | write a skill, create a skill, skill template | a meta "skill-creator" |
| techne/tdd | test-first, TDD, red-green-refactor, write tests | a "testing-strategy" skill |
| techne/persona-brainstorm | persona brainstorm, grill session, Ezekiel, Jeremiah | unlikely |
| techne/grill | stress-test plan, challenge design, before implementing | a "design-review" skill |
| techne/improve-architecture | architecture review, refactoring opportunities, deepen module | a "refactor" skill |
| techne/prototype | prototype, throwaway, mock up, sanity-check state model | a "spike" skill |
| techne/check-pr | check pull request, review comments, prepare to merge | a host PR skill |
| techne/greploop | greploop, optimize/iterate pull request, greptile review | a host PR skill |
| techne/nextjs-rules | Next.js, app router, middleware, redirect, server component | framework skills |
| techne/typescript-rules | TypeScript, type error, generics, strict mode | language skills |
| techne/implementer | implement, add feature, build, create component, fix, refactor | a generic "code" skill (very broad) |

**Resolution options:** (a) install under `techne/` and only invoke Techne's
router explicitly; (b) rename colliding skills + their `skill-router.yaml` ids;
(c) trim the router conditions so Techne only claims the tasks you want it to.

---

## Adapting to your stack

If you are **not** on Next.js + TypeScript, do this before first use:

1. **Edit `harness/gate-config.yaml`.** Remove `nextjs` and/or `typescript` from
   `active_stacks`. The registry automatically disables gates in those stacks.
   No code changes needed.
2. **Add your own gates** (optional). Drop a `.py` file in `harness/plugins/`
   with a `register(registry)` function. See `plugins/security_gates.py` for
   an example. Add your stack to `active_stacks` in `gate-config.yaml`.
3. **Replace the always-loaded skills.** In `harness/skill-router.yaml`, change
   `always_loaded` from `nextjs.md`/`typescript.md` to your stack's rule cards,
   and rewrite those cards (`skills/writing-skill.md` shows the format).
4. **Update the gate eval cases.** Edit `tests/evals/cases/gate_cases.json` to
   cover your gates, then `python tests/evals/run_evals.py --save-baseline`.
5. **Keep everything else.** The router, intent reasoning, eval scoring, memory,
   retro loop, and the `diagnose`/`tdd`/`grill`/`writing-skill` skills are
   stack-agnostic and carry over unchanged.

The engine is portable; only the **rules** are stack-specific plugins.

---

## Pre-integration checklist

Run through this before wiring Techne in:

```
[ ] Python 3.10+ available
[ ] Installed in its own dir (techne/) OR root-file collisions resolved
    (SKILL.md, CONTEXT.md, docs/adr/, memory/)
[ ] Stack check: Next.js+TS?  → gates work as-is
                  other stack? → replaced gates + always_loaded (see above)
[ ] Skill-name collisions checked against host skills (diagnose/tdd/grill/implementer)
[ ] Router trigger overlap reviewed (skill-router.yaml conditions)
[ ] memory/mistakes.md present with the insert marker
[ ] agents/*.md model: fields mapped to your host's models
[ ] python tests/evals/run_evals.py → 65/65 (or your re-baselined number)
```

See **[INSTALL.md](INSTALL.md)** for the wiring steps and the `Pipeline` API.
