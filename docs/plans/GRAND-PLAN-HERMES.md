# Grand Plan — Techne Architectural Overhaul

> Executor: Hermes Agent  
> Date: 2026-06-26  
> Branch: cut from `master`

---

## What This Is

Techne is being redesigned from a heavy CLI harness into two clean layers:

| Layer | What | Where |
|---|---|---|
| **Enforcement** | Hermes plugin — fires at tool-call layer, writes audit + RL events | `.hermes/plugins/techne_plugin.py` |
| **Orchestrator** | Skill — drives RECALL → IMPLEMENT → VERIFY → CONCLUDE, routes to best skill | `.hermes/skills/techne/SKILL.md` |

Everything that was scattered across `harness/`, `scripts/`, `techne_cli/` collapses into this structure. The Hermes agent executing this plan works from `repos/techne` — the development repo that syncs to `.hermes/skills/techne/` in consuming projects.

**State directory:** `.techne/` stays relative (no path changes in code). In deployment it becomes `.hermes/skills/techne/.techne/`.

---

## Architecture After This Plan

```
.hermes/
  plugins/
    techne_plugin.py          ← Hermes enforcement adapter (Task 1)
  skills/
    techne/
      SKILL.md                ← /techne entry point + orchestrator (Task 5)
      skills/                 ← Techne skill library (existing, no change)
      scripts/
        next.py               ← retro wiring + gate hardening (Tasks 2,3,4,9,10)
        next_state.py
        hash_gate.py
        audit_chain.py
        init_project.py       ← pre-flight added (Task 7)
      hooks/
        phase_guard_hook.py   ← CC adapter (unchanged)
      harness/                ← existing (no change)
      .techne/
        loop/
          file_scope.json     ← written at RECALL, consumed at IMPLEMENT (Task 8)
        audit/
        context/
        memory/
        events/               ← rl.jsonl written by plugin on every gate (Task 1)
```

Orchestrator discovers skills from:
1. `.hermes/skills/` — full Hermes ecosystem (omh-deep-research, omh-ralplan, etc.)
2. `skills/` — Techne skill library

---

## Tasks

### Task 6 — `techne gate` CLI Subcommand *(execute first)*

**File:** `techne_cli/main.py`  
**What:** Gates must be callable standalone so the Hermes plugin and any runtime can invoke them without importing Python directly.

```bash
techne gate hashline <diff_file>    # exit 0 pass, exit 1 + reason on stdout
techne gate forbidden <diff_file>   # exit 0 pass, exit 1 + pattern on stdout
techne gate audit <json_event>      # append to .techne/audit/chain.jsonl, exit 0
```

Add `cmd_gate(args)` to `techne_cli/main.py` and wire into `cli()`:
```python
p_gate = sub.add_parser("gate", help="Run a named gate check")
p_gate.add_argument("name", choices=["hashline", "forbidden", "audit"])
p_gate.add_argument("target", help="diff file path or JSON event string")
p_gate.set_defaults(func=cmd_gate)
```

`cmd_gate` delegates to `hash_gate.validate_diff_context`, `_check_no_forbidden_patterns`,
and `audit_chain.append_event`. Exits 0 on pass, 1 on fail (reason on stdout).

**Verify:** `techne gate hashline <clean_diff>` exits 0; `techne gate hashline <stale_diff>` exits 1.

---

### Task 7 — Pre-flight at `techne init`

**File:** `scripts/init_project.py`  
**What:** Before scaffolding `.techne/`, run three checks that surface known problems before the agent starts work. These tools exist in the harness but nothing calls them at init time.

```python
# 1. Audit chain integrity — detect tampering or corruption before new task
from audit_chain import verify_chain
ok, msg = verify_chain()
if not ok:
    print(f"WARNING: audit chain broken — {msg}")
    # Block init or warn depending on config

# 2. Mistakes pre-flight — surface known pitfalls for this task type
sys.path.insert(0, str(Path(__file__).parent.parent / "harness"))
from mistakes import check_relevant
hits = check_relevant(task_description)
if hits:
    print(f"\n⚠  {len(hits)} known mistake(s) relevant to this task:")
    for h in hits:
        print(f"   [{h['gate']}] {h['lesson']}")

# 3. Knowledge graph surface — prior work on similar tasks
from knowledge_graph import cmd_search  # or subprocess call
# Print top 3 matches if available
```

Print warnings before init completes. Never block on empty stores (new project). Block only on broken audit chain.

**Verify:** Seed `.techne/memory/mistakes.md` with a relevant entry, run `techne init <matching-task>`, assert warning is printed.

---

### Task 1 — Hermes Enforcement Plugin (with GRPO wiring)

**File:** `.hermes/plugins/techne_plugin.py`  
**What:** Hermes enforcement adapter. Mirrors CC's PreToolUse hook as an OMH plugin.

Gate fires on every write tool call (`write_file`, `edit_file`, `multi_edit`, `notebook_edit`):

1. Read current phase from `.techne/loop/state.json`
2. At IMPLEMENT: `techne gate hashline .techne/loop/diff.txt` — block if stale
3. On any write: `techne gate forbidden <content>` — block if forbidden pattern
4. `techne gate audit <event_json>` — write SHA-chained audit event
5. Write RL event to `.techne/events/rl.jsonl` on every gate outcome:

```python
rl_event = {
    "ts": time.time(),
    "phase": phase,
    "gate": gate_name,            # "hashline" | "forbidden" | "audit"
    "reward": 1.0 if passed else -1.0,
    "advantage": 0.5 if passed else -0.5,
    "tool": tool_name,
    "path": file_path,
}
```

Return `None` to allow, `{"blocked": True, "reason": str}` to deny.

**Register in:** `.hermes/config.yaml` — document the required line, don't create the file (project-specific).

**Verify:** Unit tests with synthetic tool payloads. Assert: stale diff → blocked, clean diff → allowed, rl.jsonl written on both outcomes.

---

### Task 2 — Wire `_persist_retro` into `./next` CONCLUDE Transition

**File:** `scripts/next.py`  
**What:** Wire wisdom extraction when `./next` advances CONCLUDE → DONE. Currently only runs in model-backed `OrchestratorLoop` — every CC/Hermes task silently throws DECISION/LESSON/DISCIPLINE away.

**Where:** Find `if old_phase == "CONCLUDE":` block (~line 735). After the wikilink rebuild block:

```python
try:
    sys.path.insert(0, str(Path(__file__).parent.parent / "harness"))
    from _retro_conclude import _persist_retro
    conclude_text = (cwd / ".techne" / "loop" / "conclude.txt").read_text()
    _persist_retro(state.task_id, conclude_text, state.task_id)
except Exception:
    pass  # best-effort — never block DONE on retro failure
```

**Verify:** Integration test — conclude.txt with markers → run `./next` → assert `.techne/memory/ledger.md` and `.techne/memory/retros/` written.

---

### Task 3 — Harden CONCLUDE Gate

**File:** `scripts/next.py` → `_check_conclude_gates()`

**3a. Require retro markers:**
```python
has_markers = bool(re.search(
    r"^\s*[-*]\s+(DECISION|LESSON|DISCIPLINE):", text, re.MULTILINE
))
results.append(GateResult(
    "retro markers",
    has_markers,
    "markers found" if has_markers
    else "missing retro markers — add: DECISION: / LESSON: / DISCIPLINE:",
))
```

**3b. Require VERIFY reference:**
```python
has_verify_ref = bool(re.search(
    r"(?:tests?\s+pass|all\s+\d+\s+pass|pytest|test_output|✓)", text, re.I
))
results.append(GateResult(
    "verify reference",
    has_verify_ref,
    "test reference found" if has_verify_ref
    else "no test reference — mention test results in conclude.txt",
))
```

**3c. Raise minimum length** from 20 → 150 chars.

**3d. HONCHO ID must match task context** — HONCHO value must contain a kebab-case string
(not generic like "done" or "ok"). Regex: `HONCHO:\s+[a-z][a-z0-9-]{3,}`.

**Verify:** Short/markerless conclude.txt blocked. Well-formed conclude.txt with markers passes.

---

### Task 4 — Harden RECALL Gate

**File:** `scripts/next.py` → `_check_recall_gates()`

**4a. Require context reference:**
```python
has_context_ref = bool(re.search(
    r"\.techne/context/|project_digest|file_roles|context_hash", text
))
results.append(GateResult(
    "context reference",
    has_context_ref,
    "context file referenced" if has_context_ref
    else "no .techne/context/ reference — read context pack before RECALL",
))
```

**4b. Require FILE_SCOPE declaration:**
```python
has_scope = bool(re.search(r"^FILE_SCOPE:", text, re.MULTILINE))
results.append(GateResult(
    "FILE_SCOPE declared",
    has_scope,
    "FILE_SCOPE found" if has_scope
    else "missing FILE_SCOPE: line — list expected files to change",
))
```

If FILE_SCOPE present, extract the file list and write to `.techne/loop/file_scope.json`
for consumption by the IMPLEMENT gate in Task 8.

**Verify:** recall.txt without context ref → blocked. recall.txt without FILE_SCOPE → blocked. Well-formed recall.txt → passes and writes file_scope.json.

---

### Task 8 — File-Scope Gate at IMPLEMENT

**File:** `scripts/next.py` → `_check_implement_gates()`  
**What:** If `.techne/loop/file_scope.json` exists (written by RECALL gate in Task 4), verify the diff only touches declared files. Silent scope creep is currently undetected.

```python
scope_file = Path.cwd() / ".techne" / "loop" / "file_scope.json"
if scope_file.exists():
    declared = set(json.loads(scope_file.read_text()))
    touched = {
        line[6:].partition("\t")[0].strip()
        for line in text.split("\n")
        if line.startswith("+++ ") and line[6:].strip() != "/dev/null"
    }
    undeclared = touched - declared
    results.append(GateResult(
        "file scope",
        not undeclared,
        f"all {len(touched)} file(s) in scope" if not undeclared
        else f"undeclared file(s): {', '.join(sorted(undeclared))}",
    ))
```

**Verify:** diff touching undeclared file → blocked with file list. diff within declared scope → passes.

---

### Task 9 — Harden VERIFY Gate

**File:** `scripts/next.py` → `_check_verify_gates()`  
**What:** Current gate passes on any "passed" keyword. An empty test suite (`ran 0 tests`) passes silently.

**9a. Detect empty test suite:**
```python
ran_zero = bool(re.search(r"ran\s+0\s+test|0\s+passed|collected\s+0\s+item", text, re.I))
results.append(GateResult(
    "non-empty test suite",
    not ran_zero,
    "tests ran" if not ran_zero
    else "empty test suite — 0 tests ran, nothing verified",
))
```

**9b. Require explicit test count:**
```python
has_count = bool(re.search(r"\d+\s+passed", text, re.I))
results.append(GateResult(
    "explicit test count",
    has_count,
    "test count found" if has_count
    else "no test count — output must show N passed",
))
```

**Verify:** `0 passed` → blocked. `12 passed` → passes.

---

### Task 10 — Knowledge Graph Consultation at RECALL

**File:** `scripts/next.py` → `_check_recall_gates()`  
**What:** The knowledge graph (`scripts/knowledge_graph.py`) exists and is queryable but is never consulted at RECALL. Agent can skip it entirely. Require evidence of consultation.

```python
has_kg_ref = bool(re.search(
    r"knowledge.graph|kg.search|wikilink|prior.task|previous.task|ledger", text, re.I
))
results.append(GateResult(
    "knowledge graph consulted",
    has_kg_ref,
    "KG reference found" if has_kg_ref
    else "no knowledge graph reference — run: techne kg search <term>",
))
```

Also: in the orchestrator skill (Task 5), add explicit instruction to run
`python3 scripts/knowledge_graph.py search <task-keyword>` at the start of RECALL
and include the output summary in recall.txt.

**Verify:** recall.txt without KG reference → blocked. recall.txt referencing prior task from KG → passes.

---

### Task 11 — Hermes Doctor

**File:** `techne_cli/main.py` → `cmd_doctor()`  
**What:** `techne doctor` currently checks CC setup only. Add Hermes-specific checks:

```
Hermes checks:
✓/✗  .hermes/config.yaml exists
✓/✗  techne plugin registered in config (grep for techne_plugin)
✓/✗  .hermes/skills/techne/SKILL.md exists
✓/✗  techne gate hashline callable (subprocess test)
✓/✗  .techne/audit/chain.jsonl integrity (verify_chain())
```

Print Hermes section separately from CC section. Detect which runtime is active
by checking which config files are present.

**Verify:** With Hermes plugin registered → all Hermes checks pass. With plugin missing → specific failure shown.

---

### Task 12 — GRPO Proposal Review at CONCLUDE

**File:** `scripts/next.py` → CONCLUDE → DONE transition  
**What:** `harness/grpo.py` generates proposals in `.techne/memory/retro_proposals.md` when high-advantage RL events accumulate. These proposals currently sit forever — nothing surfaces them. Wire a review prompt at CONCLUDE:

After `_persist_retro` (Task 2), check for unreviewed proposals:

```python
proposals_path = cwd / ".techne" / "memory" / "retro_proposals.md"
if proposals_path.exists():
    content = proposals_path.read_text()
    pending = content.count("PROPOSE ADD")
    if pending > 0:
        print(f"\n  ⚡  {pending} GRPO proposal(s) ready for review:")
        print(f"      Run: techne proposals review")
        print(f"      File: .techne/memory/retro_proposals.md")
```

Also add `techne proposals review` CLI subcommand that opens the proposals file
and walks the agent through accept/reject for each pending entry.

**Verify:** Seed retro_proposals.md with a PROPOSE ADD entry → run `./next` at CONCLUDE → assert proposal count is printed.

---

### Task 13 — Sterile Techne Repo Restructure

**What:** Strip `repos/techne` down to enforcement only. Everything that is not a gate, hook, audit, or CLI moves out.

**Keep in `repos/techne/`:**
```
hooks/phase_guard_hook.py       ← CC enforcement adapter
scripts/next.py                 ← phase transitions + gate checks
scripts/next_state.py
scripts/hash_gate.py            ← hashline gate
scripts/audit_chain.py          ← audit chain
scripts/init_project.py         ← scaffold (.techne/)
techne_cli/                     ← CLI (gate, init, next, doctor, handoff, status)
harness/gates.py                ← gate functions
harness/pipeline_enforcer.py    ← phase mode classifier
harness/enforcement.py
harness/mistakes.py             ← gate failure store (enforcement reads it)
harness/ledger.py               ← enforcement writes here
harness/_retro_conclude.py      ← wisdom extraction (wired in Task 2)
harness/grpo.py                 ← RL event logic
tests/                          ← all tests stay
```

**Move out:**
```
skills/          → .hermes/skills/techne-skills/   (Techne skill library)
agents/          → .hermes/agents/                 (phase agent prompts)
harness/orchestrator_loop.py  → orchestrator plugin (Task 14)
harness/driver.py             → orchestrator plugin (Task 14)
harness/task_db.py            → orchestrator plugin (Task 14)
harness/phase_skills.py       → orchestrator plugin (Task 14)
docs/            → keep (plans, retros, ADRs stay with source)
```

After this task, a reader opening `repos/techne/` should see only enforcement machinery.
No skills, no orchestration, no agent prompts.

**Verify:** `ls repos/techne/` shows no `skills/` or `agents/` directory. `techne doctor` still passes. All enforcement tests still pass.

---

### Task 14 — Orchestrator as Hermes Plugin

**Files:** `.hermes/plugins/orchestrator/plugin.yaml` + `.hermes/plugins/orchestrator/__init__.py`

**What:** Elevate the orchestrator from a SKILL.md (prose the model follows) to a registered Hermes plugin with lifecycle hooks and deterministic state management. The plugin handles what prose cannot enforce.

**plugin.yaml:**
```yaml
name: orchestrator
version: "1.0.0"
description: >
  Techne pipeline orchestrator — drives RECALL → IMPLEMENT → VERIFY → CONCLUDE.
  Tracks phase state, enforces retry caps, surfaces HITL blocks, manages session
  continuity via handoff.md.

hooks:
  on_session_start: true   # read state.json, surface active phase to agent
  pre_tool_call: true      # enforce retry cap (block if phase exceeded 3 attempts)
  on_session_end: true     # write handoff.md if task incomplete

commands:
  - name: orchestrator
    description: Start or resume a Techne pipeline task
    subcommands: [status, retry, block, unblock, handoff]
```

**`__init__.py` — key responsibilities:**
- `on_session_start`: read `.techne/loop/state.json`, print current phase + attempt count
- `pre_tool_call`: if `attempt_count > 3` for current phase → `{"blocked": True, "reason": "retry cap — HITL required"}`
- `on_session_end`: if phase != DONE → call `techne handoff` to write continuity doc
- Phase routing: on user message containing `ultrawork` or `ulw` → inject pipeline instructions

Skills are still loaded as prose (SKILL.md files from `.hermes/skills/`). The plugin handles the state and caps; the skill handles the instructions.

**Verify:** Start a task, fail IMPLEMENT gate 4 times → assert plugin blocks on 4th attempt with HITL message. Session end with incomplete task → assert handoff.md written.

---

### Task 15 — Revolver Plugin Reintroduction

**What:** Revolver is the delegation fallback plugin — when a model/provider fails or produces garbage output, Revolver rotates to the next cylinder (model/key combination) and retries without human intervention. It was documented in `docs/techne-domains.md` (Domain 9) and `skills/receptionist/references/revolver-plugin-hardening.md` but is not wired into the current grand plan.

**Reintroduce in three steps:**

**15a. Document as required companion** in `ref/HANDOFF-HERMES.md`:
```
## Required Companion Plugins

### Revolver (~/.hermes/plugins/revolver/)
Delegation fallback — rotates model/provider on failure.
Required for production Techne use. Without it, a blocked IMPLEMENT
(e.g. model API failure) stalls the pipeline permanently.

Setup: copy revolver-plugin-hardening.md config into ~/.hermes/revolver.yaml
Commands: /revolver status, /revolver graph, /revolver next
```

**15b. Add Revolver health check to `techne doctor`** (extend Task 11):
```
Revolver checks:
✓/✗  ~/.hermes/plugins/revolver/ exists
✓/✗  ~/.hermes/revolver.yaml cylinder pool configured
✓/✗  /revolver status callable
```

**15c. Wire Revolver into orchestrator plugin** (extend Task 14):
When orchestrator's `pre_tool_call` detects a model failure pattern (empty output,
repeated identical errors, API error codes), emit:
```python
{"blocked": False, "inject": "/revolver next — model failure detected, rotating cylinder"}
```
This nudges Hermes to rotate before the next call rather than retrying the same
failing model.

**Verify:** `techne doctor` shows Revolver section. `ref/HANDOFF-HERMES.md` includes Revolver setup instructions.

---

### Task 5 — Promote Orchestrator to `/techne` Skill Entry Point *(execute last)*

**Files:**
- `.hermes/skills/techne.md` → convert to directory: `.hermes/skills/techne/SKILL.md`
- `skills/orchestrator/SKILL.md` — merge content into the new entry point

**What:** Single `SKILL.md` at `.hermes/skills/techne/SKILL.md` contains:

1. Doctor check + skill inventory (`.hermes/skills/` and `.hermes/skills/techne-skills/`)
2. Full loop: RECALL → IMPLEMENT → VERIFY → CONCLUDE with artifact requirements
3. Skill routing table (when to call omh-deep-research, omh-ralplan, omh-deep-interview)
4. Phase guard cheatsheet (what each gate checks, per Tasks 3,4,8,9,10)
5. HITL blocking protocol
6. Knowledge graph consultation instruction at RECALL
7. Health commands including Revolver status

Delete `.hermes/skills/techne.md` (flat file) once directory-based version exists.
Keep `skills/orchestrator/SKILL.md` as redirect for CC backward compat.

**Verify:** `/techne` loads in Hermes. All gate requirements visible in one document.

---

## Execution Order

```
Task 13  — repo restructure (do early — clarifies what's enforcement vs ecosystem)
Task 6   — gate CLI (everything else calls techne gate)
Task 7   — pre-flight at init (standalone)
Task 1   — Hermes enforcement plugin (needs Task 6)
Task 14  — orchestrator plugin (needs Task 13 — files moved out first)
Task 15  — Revolver reintroduction (needs Task 11 for doctor, Task 14 for wiring)
Task 2   — wire _persist_retro (independent)
Task 3   — harden CONCLUDE gate (needs Task 2)
Task 12  — GRPO proposal review (needs Task 2 + Task 3)
Task 4   — harden RECALL gate + FILE_SCOPE write
Task 8   — file-scope gate at IMPLEMENT (needs Task 4)
Task 9   — harden VERIFY gate (independent)
Task 10  — KG consultation at RECALL (needs Task 4)
Task 11  — Hermes doctor (needs Task 1 + Task 15)
Task 5   — orchestrator skill merge (last — documents everything above)
```

---

## What Does NOT Change

- Path constants — `.techne/` stays relative; no code changes needed
- CC PreToolUse hook (`hooks/phase_guard_hook.py`) — still works unchanged
- `scripts/hash_gate.py` — gate logic unchanged; exposed via CLI in Task 6
- `harness/grpo.py` — GRPO proposal logic unchanged; Task 1 adds RL event writes
- `harness/` enforcement modules — internals unchanged; only orchestration modules move

---

## Done When

- [ ] `repos/techne/` contains only enforcement (no skills/, no agents/) (Task 13)
- [ ] `techne gate hashline` / `forbidden` / `audit` callable as CLI (Task 6)
- [ ] `techne init` prints relevant mistakes + KG hits before scaffolding (Task 7)
- [ ] `.hermes/plugins/techne_plugin.py` blocks stale diffs, writes rl.jsonl (Task 1)
- [ ] `.hermes/plugins/orchestrator/` registered, enforces retry cap + handoff (Task 14)
- [ ] Revolver documented as companion, wired into doctor + orchestrator (Task 15)
- [ ] CONCLUDE → DONE writes to `.techne/memory/` (Task 2)
- [ ] conclude.txt without retro markers / verify ref / valid HONCHO → blocked (Task 3)
- [ ] recall.txt without context ref / FILE_SCOPE → blocked; file_scope.json written (Task 4)
- [ ] diff touching undeclared file → blocked with file list (Task 8)
- [ ] `0 passed` / empty suite → VERIFY blocked (Task 9)
- [ ] recall.txt without KG reference → blocked (Task 10)
- [ ] `techne doctor` shows Hermes + Revolver health sections (Task 11)
- [ ] GRPO pending proposals surfaced at CONCLUDE (Task 12)
- [ ] `/techne` loads from `.hermes/skills/techne/SKILL.md` (Task 5)
- [ ] All existing tests still pass
