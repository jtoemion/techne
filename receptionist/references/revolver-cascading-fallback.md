# Revolver — Cascading Fallback Plugin Architecture

**Location:** `~/.hermes/plugins/revolver/`

**Purpose:** Cycle through provider+model combinations for `delegate_task`
when one hits auth or rate-limit errors. Unlike a simple round-robin,
revolver uses a **cascading fallback chain**: each provider gets its own
pool of API keys ("bullets"), and only when all keys are spent does it
move to the next provider ("cylinder").

---

## Architecture

```
revolver.yaml                         state.json
┌──────────────────────┐              ┌─────────────────┐
│ cylinders:           │              │ cylinder: 0      │
│   - delegation:      │   loaded     │ bullet: 1        │
│       model: n2-pro  │─────────▶    │ state: ACTIVE    │
│       provider: or   │              │ bullet_cooldowns:│
│     bullets:         │              │   "0": 0.0      │
│       - key: k1      │              │   "1": 1e10     │
│       - key: k2      │              └─────────────────┘
│   - delegation: ...  │
└──────────────────────┘
         │
         ▼
  ┌──────────────────┐     401/429      ┌──────────────────┐
  │ api_request_error│─────────────────▶│  _advance()      │
  │ hook             │                  │  round-robin     │
  └──────────────────┘                  │  skip cooldown   │
         │                              └──────────────────┘
         ▼                                       │
  ┌──────────────────┐                    ┌──────┴──────────┐
  │ _classify_error  │  ┌──────┐          │  index advanced  │
  │ 401 → advance    │  │lock │          │  state saved    │
  │ 429 → cooldown   │  │file │          └─────────────────┘
  │ 5xx → transient  │  └──────┘
  └──────────────────┘
```

## State Machine

```
CYLINDER_ACTIVE → on 401, advance bullet index
                → on 429, set bullet cooldown, retry in place
                → all bullets in cooldown → ALL_COOLDOWN signal
                                        → caller decides exhaust
                
CYLINDER_EXHAUSTED → all bullets failed (after consecutive failures + health probe)
                   → advance to next cylinder index
                   → if no more cylinders → ALL_EXHAUSTED

ALL_EXHAUSTED → recovery thread starts, probes cylinder 0 periodically
              → probe succeeds → reset to cylinder 0
              → /revolver reset to recover manually
```

## Config Schema (`~/.hermes/revolver.yaml`)

```yaml
cylinders:
  - delegation:
      model: nex-agi/nex-n2-pro:free
      provider: openrouter
    consecutive_failures_threshold: 2     # 401s before advancing (default 2)
    cooldown_seconds: 60                   # between retries on 429
    probe_url: https://openrouter.ai/api/v1/models  # health check before exhausting
    recovery_check_interval_seconds: 300   # how often to retry when exhausted
    bullets:
      - key: sk-or-v1-aaa
        type: bearer                        # auth header type
        label: "openrouter-1"               # for graph display
        cooldown_seconds: 30                # per-bullet override
      - key: sk-or-v1-bbb
        type: bearer

  - delegation:
      model: deepseek-v4-flash
      provider: opencode-zen
    bullets: []                             # free tier, no keys needed
```

## Error Classification

| Code | Classification | Action |
|------|---------------|--------|
| 401  | `advance`     | Increment consecutive_failures counter. When counter ≥ threshold, advance to next bullet or cylinder. |
| 429  | `cooldown`    | Set cooldown on the current bullet/cylinder. Retry in place. Do NOT count as consecutive failure. |
| 408, 502, 503 | `transient` | Do NOT rotate. Retry in place. The provider may recover. |
| _    | `unknown`     | Treat as transient. |

## Locking

File-based lock at `~/.hermes/.revolver.lock` containing PID + timestamp.
Purpose: prevent race conditions when two API errors fire simultaneously.
- 5-second acquire timeout
- Stale lock (>10s without PID alive) is broken
- Non-blocking — fail fast rather than block the API call

## Telemetry

Every rotation event is logged to `~/.hermes/.revolver_events.log`
(newline-delimited JSON, max 10,000 lines, auto-trims to 5,000).

Event types:
- `bullet_advanced` — moved to next bullet within same cylinder
- `cylinder_exhausted` — all bullets in cylinder spent
- `cylinder_entered` — moved to a new cylinder
- `all_exhausted` — all cylinders exhausted
- `cooldown_set` — cooldown placed on a bullet or cylinder
- `probe_passed` / `probe_failed` — health probe result
- `recovery_scheduled` / `recovery_attempt_failed` / `recovery_success`
- `reset` — /revolver reset called

## Commands

| Command | What it does |
|---------|-------------|
| `rev next` | Advance one bullet. If magazine empty, cascade to next cylinder. |
| `rev status` | Show current cylinder index, bullet index, state, cooldown. |
| `rev graph` | Print full fallback chain with `●` position marker. |
| `rev reset` | Back to cylinder 0, bullet -1, CYLINDER_ACTIVE. Stop recovery thread. |
| `rev log` | Last 20 rotation events. |

## Hardening History

| # | Item | What it prevents |
|---|------|------------------|
| 1 | Bullet metadata (key/type/label, backward compat) | Different providers need different auth headers |
| 2 | Per-bullet cooldown | One key rate-limited shouldn't poison the whole cylinder |
| 3 | Consecutive failure threshold (default 2) | Transient 401 glitch shouldn't burn a key |
| 4 | Health probe | Don't exhaust a working provider due to one bad key |
| 5 | Telemetry log | Audit trail for rotation decisions |
| 6 | Cron recovery (background thread) | Auto-recover when a dead provider comes back |
| 7 | Dispatch-time tool (get_active_delegation) | Host agent can read current config before dispatching |

## Key Limitation

`delegate_task` does NOT accept model/provider overrides per-call.
Config changes take effect on next `/new`, not mid-session.
The user's assessment: `/new` is solid for this — clean state machine,
no mid-session cache races.
