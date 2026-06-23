# Production Enforcement Plan — Making Agents Unable to Lie

Date: 2026-06-23
Status: DRAFT — pending approval
Author: Megumi Kato

## Problem

The `./next` system proves phase completion from disk artifacts — the agent
can't fake what `./next` prints. But it has five production gaps:

1. **Agent can skip `./next` entirely.** Nothing forces the agent to call it.
   The pre_tool_call plugin blocks writes outside the current phase, but only
   if loaded. An agent that starts without the plugin bypasses everything.

2. **No phase timeout.** Agent can stall in one phase forever. No alert fires.

3. **No external monitor.** No daemon/cron watches `.techne/loop/state.json`.
   The only signal that the pipeline is stuck is what the agent tells you.

4. **No tamper-evident audit trail.** `./next` prints to stdout. The agent
   could delete or rewrite `state.json` and there's no external record.

5. **Plugin is in-process Python.** A determined agent could monkey-patch
   `pipeline_hooks.py` at runtime since it runs in the same process.

## Architecture

```
                    AGENT (untrusted)
                       │
                       ▼
              ┌─────────────────┐
              │  ./next script  │ ── reads disk ──→ .techne/loop/state.json
              │  (next.py)      │ ── checks artifact ──→ .techne/loop/{phase}.txt
              │                 │ ── runs gates ──→ harness/enforcement.py
              │                 │ ── writes summary ──→ .techne/loop/state.json
              │                 │ ── APPENDS audit ──→ .techne/audit/chain.jsonl ◄ NEW
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │  WATCHDOG CRON  │ ◄ NEW — runs every 5 min
              │  (watchdog.py)  │ ── reads state.json ──→ checks updated_at age
              │                 │ ── reads chain.jsonl ──→ verifies hash chain
              │                 │ ── alerts on: stall, tamper, skipped phases
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │  HERMES PLUGIN  │ ── pre_tool_call hook
              │  (phase_guard)  │ ── blocks writes outside .techne/loop/ if
              │                 │     no state.json exists (phase not started)
              │                 │ ── blocks writes to .techne/audit/ (agent
              │                 │     cannot touch the audit trail)
              └─────────────────┘
```

The key insight: **the audit trail and watchdog are external to the agent's
process.** The agent runs `./next`, which appends to the audit log. The
watchdog reads the audit log independently. The agent cannot edit the audit
log because the plugin blocks writes to `.techne/audit/`.

---

## Phase 1 — Tamper-Evident Audit Trail

**Goal:** Every `./next` call appends a hash-chained record to an append-only
log that the agent cannot edit.

### 1.1 — Audit chain module

File: `scripts/audit_chain.py` (new)

```python
"""audit_chain.py — Append-only hash-chained audit log for ./next.

Each entry contains:
  - sequence number (monotonic)
  - timestamp (UTC ISO)
  - task_id
  - phase
  - gate results (pass/fail per gate)
  - summary text (what ./next printed)
  - prev_hash (SHA-256 of the previous entry)
  - entry_hash (SHA-256 of this entry's content minus entry_hash)

The chain is verifiable: recompute every hash from entry 0 and compare.
If any entry was modified or deleted, the chain breaks.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

@dataclass
class AuditEntry:
    seq: int
    timestamp: str
    task_id: str
    phase: str
    gates: list[dict]       # [{name, passed, detail}]
    summary: str
    prev_hash: str
    entry_hash: str = ""    # computed after construction

    def compute_hash(self) -> str:
        d = asdict(self)
        d.pop("entry_hash", None)
        return hashlib.sha256(
            json.dumps(d, sort_keys=True).encode()
        ).hexdigest()

    def seal(self) -> None:
        self.entry_hash = self.compute_hash()
```

### 1.2 — Integrate into next.py

Modify `scripts/next.py`:
- After printing the summary and before `write_state()`, call
  `audit_chain.append_entry()`.
- Read `prev_hash` from the last line of `chain.jsonl`.
- Write the new entry as one JSON line appended to
  `.techne/audit/chain.jsonl`.

### 1.3 — Plugin guard on audit dir

Modify `harness/plugins/pipeline_hooks.py`:
- Add path check: if a write targets `.techne/audit/`, block it.
  Only `./next` (running as a subprocess, not through the plugin) can
  write there. The agent's `write_file` tool goes through the plugin.

### 1.4 — Tests

File: `tests/test_scripts/test_audit_chain.py` (new)

- `test_append_creates_chain` — first entry has prev_hash="0"*64
- `test_chain_is_sequential` — seq numbers increment
- `test_tamper_detection` — modify an entry, verify chain breaks
- `test_hash_is_deterministic` — same content → same hash
- `test_append_after_next` — run `./next` in a test fixture, verify
  chain.jsonl has a new entry

---

## Phase 2 — Phase Timeout + Stall Detection

**Goal:** If the agent doesn't call `./next` within N minutes of entering a
phase, the watchdog flags a stall.

### 2.1 — Add timeout to state.json

Modify `scripts/next_state.py`:
- Add `phase_timeout_min: int = 30` field to `LoopState`
- On `write_state()`, set `updated_at` to now
- The timeout is the max wall-clock minutes a phase should take

### 2.2 — Watchdog script

File: `scripts/watchdog.py` (new)

```python
"""watchdog.py — External pipeline stall + tamper detector.

Run via cron every 5 minutes:
  */5 * * * * cd /path/to/project && python3 /path/to/techne/scripts/watchdog.py

Checks:
  1. STALL: state.json exists and updated_at is older than phase_timeout_min
  2. TAMPER: chain.jsonl hash chain is broken
  3. SKIP: state.json phase advanced but chain.jsonl has no matching entry
  4. ORPHAN: state.json doesn't exist but .techne/ has recent task dirs

Exit codes:
  0 = healthy
  1 = stall detected
  2 = tamper detected
  3 = skip detected
  4 = orphan detected

Output: plain-text alert suitable for cron email / ntfy / Telegram
"""
```

### 2.3 — Watchdog tests

File: `tests/test_scripts/test_watchdog.py` (new)

- `test_healthy_state` — fresh state.json, recent updated_at → exit 0
- `test_stall_detected` — updated_at 2h old → exit 1, alert text
- `test_tamper_detected` — modified chain entry → exit 2
- `test_skip_detected` — phase advanced in state.json but no chain entry → exit 3
- `test_no_state` — no state.json → exit 0 (nothing running)

---

## Phase 3 — Plugin Hardening (Write Blockade)

**Goal:** If no `state.json` exists, the agent cannot write to project files.
This forces the agent to start the loop before doing any work.

### 3.1 — Phase-guard plugin

File: `harness/plugins/phase_guard.py` (new)

```python
"""phase_guard.py — Pre_tool_call plugin that blocks writes outside the loop.

Logic:
  1. Read .techne/loop/state.json
  2. If no state.json:
     - Block ALL writes except to .techne/ (can't start work without starting the loop)
     - Print: "No active pipeline. Call ./next to start the loop."
  3. If state.json exists:
     - Read current phase
     - Block writes to .techne/audit/ (agent cannot touch audit trail)
     - Allow writes to the current phase's artifact path
     - Allow writes to project source files (the agent is implementing)
     - Block writes to other phase artifact paths (can't pre-write next phase)
  4. Log every blocked write to .techne/audit/blocked.log
"""
```

### 3.2 — Plugin registration

Modify `harness/plugins/__init__.py`:
- Import and register `phase_guard` alongside existing plugins

### 3.3 — Plugin tests

File: `tests/test_plugin_phase_guard.py` (new)

- `test_no_state_blocks_writes` — no state.json, write to src/ → blocked
- `test_no_state_allows_techne_writes` — write to .techne/loop/ → allowed
- `test_active_state_allows_source_writes` — write to src/app.py → allowed
- `test_blocks_audit_dir_writes` — write to .techne/audit/ → blocked
- `test_blocks_other_phase_artifacts` — in IMPLEMENT, write to verify/ → blocked
- `test_blocked_writes_logged` — check .techne/audit/blocked.log has entry

---

## Phase 4 — Cron Integration + Alert Delivery

**Goal:** Watchdog runs automatically and alerts reach the user.

### 4.1 — Hermes cron job

Create a cron job via `cronjob action='create'`:
- Schedule: every 5 minutes
- Script: `scripts/watchdog.py`
- `no_agent=True` (script-only, no LLM needed)
- Deliver to origin chat if non-empty output (stall/tamper alert)

### 4.2 — Alert format

```
⚠️ PIPELINE STALL DETECTED

Task:       abc123
Phase:      IMPLEMENT
Last seen:  47 minutes ago (timeout: 30 min)
State file: .techne/loop/state.json

The agent has not called ./next in 47 minutes.
Either it's stuck, or it's working outside the pipeline.

Audit trail: .techne/audit/chain.jsonl (4 entries, chain intact)
```

### 4.3 — Tamper alert format

```
🚨 AUDIT TAMPER DETECTED

Entry #2 in .techne/audit/chain.jsonl has a broken hash.
Expected: a3f2e1...
Actual:   b8c4d9...

Someone modified the audit log after it was written.
This should never happen under normal operation.
```

---

## Phase 5 — Verification + Integration Test

**Goal:** End-to-end proof that the system catches a lying agent.

### 5.1 — Integration test: agent skips ./next

File: `tests/test_scripts/test_e2e_enforcement.py` (new)

Scenario:
1. Create a task, start the loop (state.json = RECALL)
2. Simulate agent writing code WITHOUT calling `./next`
3. Run watchdog → should detect stall (exit 1)
4. Verify audit chain has no new entries (agent didn't call ./next)
5. Verify blocked.log shows attempted writes if plugin was loaded

### 5.2 — Integration test: agent fakes state.json

Scenario:
1. Create a task, run `./next` once (RECALL → IMPLEMENT)
2. Manually rewrite state.json to say "DONE"
3. Run watchdog → should detect skip (exit 3)
4. Verify chain.jsonl has RECALL entry but no DONE entry

### 5.3 — Integration test: agent edits audit log

Scenario:
1. Run `./next` three times (3 chain entries)
2. Modify entry #2 in chain.jsonl
3. Run watchdog → should detect tamper (exit 2)

---

## Build Order

| Step | Files | Tests | Depends on |
|------|-------|-------|------------|
| 1.1  | scripts/audit_chain.py | test_audit_chain.py | — |
| 1.2  | scripts/next.py (modify) | test_audit_chain.py | 1.1 |
| 1.3  | harness/plugins/pipeline_hooks.py (modify) | — | 1.1 |
| 2.1  | scripts/next_state.py (modify) | — | — |
| 2.2  | scripts/watchdog.py | test_watchdog.py | 1.1, 2.1 |
| 3.1  | harness/plugins/phase_guard.py | test_plugin_phase_guard.py | 2.1 |
| 3.2  | harness/plugins/__init__.py (modify) | — | 3.1 |
| 4.1  | cronjob create | — | 2.2 |
| 5.1  | test_e2e_enforcement.py | — | 1-3 all done |
| 5.2  | test_e2e_enforcement.py | — | 5.1 |
| 5.3  | test_e2e_enforcement.py | — | 5.1 |

Total: 4 new files, 4 modified files, 4 new test files, 1 cron job.

## What This Does NOT Solve

- **Agent refuses to load the plugin.** If the agent starts a session without
  loading techne, the plugin never fires. The watchdog catches this as a stall
  (no state.json, no chain entries), but can't prevent the work from happening.
  Mitigation: the watchdog alert tells you to check what the agent did.

- **Agent writes to files through a different tool.** If the agent uses
  `terminal()` with `echo > file` instead of `write_file`, the plugin doesn't
  intercept it. This is a fundamental limitation of tool-level hooks.
  Mitigation: the audit chain still shows whether `./next` was called. If it
  wasn't, and files changed (git diff is non-empty), the watchdog can flag
  "uncommitted work without pipeline."

- **Agent runs ./next in a subprocess and ignores the output.** The agent
  could call `./next` just to generate the audit entry, then ignore the
  "next phase requirements" and do whatever it wants. The chain shows the
  phase advanced, but the next `./next` call would fail (missing artifact).
  The stall watchdog catches this.

These are diminishing returns. The first three phases close 90% of the lying
surface. The remaining 10% requires OS-level sandboxing (seccomp, containers)
which is out of scope.
