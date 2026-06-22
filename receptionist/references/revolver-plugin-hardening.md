# Revolver Plugin — Hardening Summary

## What it is

`~/.hermes/plugins/revolver/` — a Hermes plugin that manages a cascading
fallback chain for delegation model/provider and API keys. Defined in
`~/.hermes/revolver.yaml`.

## Hardening items (all implemented 2026-06-22)

| # | Item | Why |
|---|------|-----|
| 1 | **Bullet metadata** `{key, type, label}` | Backward-compat with plain strings. Auth type per bullet (Bearer, X-API-Key, custom). |
| 2 | **Per-bullet cooldown** | Individual rate-limit timers per key. A 429 on key A doesn't cool down key B. |
| 3 | **Consecutive failure count** | Requires N 401s (default 2) before advancing. Guards against transient auth glitches. |
| 4 | **Health probe** | HEAD request to provider before exhausting a cylinder. If alive, retry in place. |
| 5 | **Telemetry log** | `.revolver_events.log` — every rotation event with timestamps. `log` command shows last 20. |
| 6 | **Cron recovery** | Background thread auto-probes cylinder 0 when ALL_EXHAUSTED. Resets on recovery. |
| 7 | **Dispatch-time tool** | `get_active_delegation` tool + `tool` command. Host reads active config before dispatch. |

## State machine

```
CYLINDER_ACTIVE → bullet 0..n (on 401 advance, on 429 cooldown)
CYLINDER_EXHAUSTED → all bullets failed or in cooldown
ALL_EXHAUSTED → all cylinders exhausted → recovery thread starts
```

## Commands

| Command | Action |
|---------|--------|
| `/revolver next` | Advance one bullet; exhaust on empty; cascade on full |
| `/revolver status` | Current cylinder, bullet, state, cooldown |
| `/revolver graph` | ASCII fallback chain with `●` position marker |
| `/revolver log` | Last 20 telemetry events |
| `/revolver reset` | Back to defaults (cylinder 0, bullet -1) |
| `/revolver tool` | Active config in human-readable format |

## Key files

| File | Purpose |
|------|---------|
| `~/.hermes/plugins/revolver/plugin.yaml` | Manifest |
| `~/.hermes/plugins/revolver/__init__.py` | ~960 lines — full implementation |
| `~/.hermes/revolver.yaml` | Cylinder definitions (edit this) |
| `~/.hermes/.revolver_state.json` | Persistent state (auto-managed) |
| `~/.hermes/.revolver_events.log` | Rotation telemetry (auto-managed) |
| `~/.hermes/.revolver.lock` | File lock (auto-managed) |

## Known limitation

Config changes need `/new` to take effect. `load_config()` caches at session
start. Writing `config.yaml` mid-session changes the file but the running
session doesn't re-read it. The user assessed `/new` as solid for this — it's
a clean state machine with no mid-session cache races.
