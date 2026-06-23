# Techne Enforcement System — Operational Guide

Date: 2026-06-23
Author: Megumi Kato
Scope: Hermes-plugin enforcement, audit chain, watchdog, firewall

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    ENFORCEMENT STACK                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. Hermes Plugin (~/.hermes/plugins/techne/__init__.py)         │
│     ├─ Auto-activates on session start if .techne/ exists        │
│     ├─ Delegates path checks to phase_guard.py                   │
│     ├─ Detects shell-level writes (echo > file via terminal())   │
│     ├─ Detects reverse shell patterns (bash -i, /dev/tcp, nc)    │
│     ├─ Phase timeout: blocks writes if no ./next > timeout_min   │
│     ├─ Tool-count limit: forces ./next after N calls per phase   │
│     └─ Logs every block to .techne/audit/blocked.log             │
│                                                                  │
│  2. ./next Script (scripts/next.py)                              │
│     ├─ Reads real disk artifacts (not agent self-report)         │
│     ├─ Runs deterministic gates (diff format, test output, etc.) │
│     ├─ Appends hash-chained entry to .techne/audit/chain.jsonl   │
│     └─ Only advances phase when ALL gates pass                   │
│                                                                  │
│  3. Watchdog Cron (every 5 min, script-only)                     │
│     ├─ STALL  (exit 1): no ./next call > timeout_min             │
│     ├─ TAMPER (exit 2): audit chain hash broken                  │
│     ├─ SKIP   (exit 3): phase advanced without audit entry       │
│     └─ ORPHAN (exit 4): work found without loop state            │
│                                                                  │
│  4. Firewall (iptables)                                          │
│     ├─ Default DROP on OUTPUT                                    │
│     ├─ Allowlisted: DNS, HTTP/HTTPS, API endpoints               │
│     └─ Catches reverse shells / unknown egress                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Alert Response

### STALL alert (exit 1)

The agent hasn't called `./next` in over `phase_timeout_min` (default 30).

```
⚠️ PIPELINE STALL: Task abc123 in phase IMPLEMENT, last seen 47 min ago (timeout: 30 min)
```

**Causes:**
- Agent is working but hasn't advanced the phase (common — agent keeps editing)
- Agent is stuck on a problem
- Agent abandoned the task

**Actions:**
1. `/techne status` — check current phase + tool count
2. `cat .techne/loop/state.json` — check `updated_at` and `phase_timeout_min`
3. If agent is legitimately working: either increase timeout (`phase_timeout_min` in state.json), or just call `./next` to advance
4. If agent left the task: `/techne off`, clean up, restart

### TAMPER alert (exit 2)

Someone modified the audit log after it was written.

```
🚨 AUDIT TAMPER: entry 2: hash mismatch
  Expected: a3f2e1...
  Actual:   b8c4d9...
```

**Causes:**
- Agent attempted to edit chain.jsonl (blocked by plugin → persistent block log)
- Corrupted filesystem
- Manual editing by operator

**Actions:**
1. `cat .techne/audit/blocked.log` — check if the plugin caught the write attempt
2. `cat .techne/audit/chain.jsonl` — inspect the broken entry
3. For corrupted chain: delete `.techne/audit/chain.jsonl` and start fresh
4. For agent tampering: review the blocked.log, increase enforcement

### SKIP alert (exit 3)

The state.json says a phase but the audit chain has no matching entry.

```
⚠️ PHASE SKIP: state says VERIFY but no audit entry for it.
Last audit entry phase: RECALL
```

**Causes:**
- Agent manually edited state.json to skip phases
- Agent called `./next` without the intermediate phase (shouldn't be possible)

**Actions:**
1. `diff .techne/loop/state.json.bak .techne/loop/state.json` — check for manual edits
2. Review the audit chain: `cat .techne/audit/chain.jsonl | python3 -m json.tool`
3. Reset state if needed: delete `.techne/loop/state.json` and restart

### ORPHAN alert (exit 4)

Task directories exist but no active loop state.

```
⚠️ ORPHANED WORK: 3 task dirs modified in last 5 min without active loop state
```

**Causes:**
- Agent started work before calling `./next`
- Previous session crashed without cleanup
- Stale task directories from a completed run

**Actions:**
1. `ls .techne/tasks/` — see which task dirs exist
2. If stale: clean with task-gardener or `rm -rf .techne/tasks/*/`
3. If current work: create state.json and start the loop properly

## Managing Enforcement

### Session commands

| Command | Effect |
|---------|--------|
| `/techne` | Activate pipeline mode (auto-activates if .techne/ exists) |
| `/techne status` | Show phase, tool count, block log, task DB |
| `/techne bypass` | Grant 3 bypass writes (for exceptions) |
| `/techne off` | Disable all enforcement for the session |

### Configuration

**Phase timeout** (per-task, in `.techne/loop/state.json`):
```json
{
  "task_id": "abc123",
  "phase": "IMPLEMENT",
  "phase_timeout_min": 30,
  ...
}
```

**Tool-count limits** (in plugin, per phase):
```python
_PHASE_TOOL_LIMITS = {
    "RECALL":    15,
    "IMPLEMENT": 25,
    "VERIFY":     8,
    "CONCLUDE":  10,
}
```

### Firewall management

```bash
# Check status
sudo ~/.hermes/scripts/techne-iptables.sh status

# Lockdown (default DROP, allowlisted destinations only)
sudo ~/.hermes/scripts/techne-iptables.sh apply [N minutes]

# Revert to default (allow all)
sudo ~/.hermes/scripts/techne-iptables.sh revert

# View dropped packets
dmesg | grep TECHNE-DROP | tail -20
```

## Audit Trail Format

The chain.jsonl is a JSONL file (one JSON object per line). Each entry:

```json
{
  "seq": 1,
  "timestamp": "2026-06-23T12:00:00+00:00",
  "task_id": "abc123",
  "phase": "RECALL",
  "gates": [{"name": "artifact: recall.txt", "passed": true, "detail": "42 bytes on disk"}],
  "summary": "  ◇ NEXT — RECALL → IMPLEMENT\n  ✓ artifact: recall.txt\n      42 bytes on disk\n  ✓ phase\n      RECALL\n  ...",
  "prev_hash": "0000000000000000000000000000000000000000000000000000000000000000",
  "entry_hash": "a3f2e1b4c5d6..."
}
```

The hash chain: `entry[N].prev_hash == entry[N-1].entry_hash`. Breaking any link = tamper detected.

## Verification

Run the verification suite to prove the enforcement system is operational:

```bash
cd ~/repos/techne && python3 -m pytest tests/test_scripts/test_e2e_verification.py -v
```

Expected output:
```
test_scenario_1_stall_detection ........... PASS
test_scenario_2_audit_chain_created ....... PASS
test_scenario_3_tamper_detection .......... PASS
test_scenario_4_no_pipeline_blocks_writes . PASS
test_scenario_5_phase_aware_blocks ........ PASS
test_scenario_6_phase_skip_detected ....... PASS
test_summary_table ....................... PASS
```

Full test suite:
```bash
cd ~/repos/techne && python3 -m pytest tests/ -q
# Expect: 774 passed (7 new E2E + 767 existing)
```

## Recovery Procedures

### Agent bypassed plugin at the OS level
If the agent managed to write files despite the plugin (e.g., via spawned subprocess):
1. Check `dmesg | grep TECHNE-DROP` for blocked reverse shell attempts
2. Check `~/.hermes/logs/` for Hermes agent logs
3. `git log --all --oneline` to review what was committed
4. `git diff HEAD~1` to review uncommitted changes that slipped through

### Corrupt state.json
```bash
# Backup and reset
cp .techne/loop/state.json .techne/loop/state.json.corrupt
rm .techne/loop/state.json
# Start fresh
python3 /home/ubuntu/repos/techne/scripts/next_state.py create --task-id new-task
```

### Watchdog cron not firing
```bash
hermes cron list
# Look for techne-watchdog (job_id: 0d99666674e3)
# If missing or disabled, re-create:
hermes cron create --name techne-watchdog --schedule "every 5 min" \
  --script techne_watchdog.sh --no-agent --deliver origin
```

## Files Reference

| File | Purpose |
|------|---------|
| `~/.hermes/plugins/techne/__init__.py` | Hermes plugin — enforcement core |
| `scripts/next.py` | ./next script — phase advancement + audit |
| `scripts/next_state.py` | LoopState dataclass + state.json read/write |
| `scripts/audit_chain.py` | Hash-chained audit log API |
| `scripts/watchdog.py` | External stall/tamper/skip detector |
| `harness/plugins/phase_guard.py` | Path-level write enforcement |
| `harness/plugins/pipeline_hooks.py` | Gate-level enforcement hooks |
| `~/.hermes/scripts/techne_watchdog.sh` | Watchdog cron wrapper |
| `~/.hermes/scripts/techne-iptables.sh` | Firewall lockdown script |
| `.techne/loop/state.json` | Active loop state |
| `.techne/audit/chain.jsonl` | Append-only audit trail |
| `.techne/audit/blocked.log` | Persistent block log |
