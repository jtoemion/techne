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

### Task 5 — Promote Orchestrator to `/techne` Skill Entry Point *(execute last)*

**Files:**
- `.hermes/skills/techne.md` → convert to directory: `.hermes/skills/techne/SKILL.md`
- `skills/orchestrator/SKILL.md` — merge content into the new entry point

**What:** Single `SKILL.md` at `.hermes/skills/techne/SKILL.md` contains:

1. Doctor check + skill inventory (both `.hermes/skills/` and `skills/`)
2. Full loop: RECALL → IMPLEMENT → VERIFY → CONCLUDE with artifact requirements
3. Skill routing table (when to call omh-deep-research, omh-ralplan, omh-deep-interview)
4. Phase guard cheatsheet (what each gate now checks, per Tasks 3,4,8,9,10)
5. HITL blocking protocol
6. Knowledge graph consultation instruction at RECALL
7. Health commands

Delete `.hermes/skills/techne.md` (flat file) once directory-based version exists.
Keep `skills/orchestrator/SKILL.md` as redirect for CC backward compat.

**Verify:** `/techne` loads in Hermes. All gate requirements visible in one document.

---

## Execution Order

```
Task 6   — gate CLI (everything else calls techne gate)
Task 7   — pre-flight at init (standalone, no deps)
Task 1   — Hermes plugin (needs Task 6)
Task 2   — wire _persist_retro (independent)
Task 3   — harden CONCLUDE gate (needs Task 2 wired first)
Task 12  — GRPO proposal review (needs Task 2 + Task 3)
Task 4   — harden RECALL gate + FILE_SCOPE write
Task 8   — file-scope gate at IMPLEMENT (needs Task 4 to write file_scope.json)
Task 9   — harden VERIFY gate (independent)
Task 10  — KG consultation at RECALL (needs Task 4, modifies same function)
Task 11  — Hermes doctor (needs Task 1 to check)
Task 5   — orchestrator skill merge (last — documents everything above)
```

---

## What Does NOT Change

- Path constants — `.techne/` stays relative; no code changes
- `harness/` internals — model-backed driver unchanged
- CC PreToolUse hook (`hooks/phase_guard_hook.py`) — still works
- `scripts/hash_gate.py` — gate logic unchanged; exposed via CLI in Task 6
- `harness/grpo.py` — GRPO proposal logic unchanged; Task 1 adds RL event writes

---

## Done When

- [ ] `techne gate hashline` / `forbidden` / `audit` callable as CLI (Task 6)
- [ ] `techne init` prints relevant mistakes + KG hits before scaffolding (Task 7)
- [ ] `.hermes/plugins/techne_plugin.py` blocks stale diffs, writes rl.jsonl (Task 1)
- [ ] CONCLUDE → DONE writes to `.techne/memory/` (Task 2)
- [ ] conclude.txt without retro markers / verify ref / valid HONCHO → blocked (Task 3)
- [ ] recall.txt without context ref / FILE_SCOPE → blocked; file_scope.json written (Task 4)
- [ ] diff touching undeclared file → blocked with file list (Task 8)
- [ ] `0 passed` / empty suite → VERIFY blocked (Task 9)
- [ ] recall.txt without KG reference → blocked (Task 10)
- [ ] `techne doctor` shows Hermes health section (Task 11)
- [ ] GRPO pending proposals surfaced at CONCLUDE (Task 12)
- [ ] `/techne` loads from `.hermes/skills/techne/SKILL.md` (Task 5)
- [ ] All existing tests still pass
