# Model Routing & Delegation Config

Confirmed working routes as of 2026-06-21.

## Parent Session

The main agent runs directly from `~/.hermes/config.yaml`:

```yaml
model:
  default: deepseek-v4-flash
  provider: opencode-go
  base_url: https://opencode.ai/zen/go/v1
```

This always works because it's the session's own model.

## Delegation (subagents)

Subagents use a separate `delegation:` section in config.yaml:

```yaml
delegation:
  model: nex-agi/nex-n2-pro:free
  provider: openrouter
```

## Fallback Chain

When the delegation model fails:

| Fallback | Model | Provider | Notes |
|----------|-------|----------|-------|
| Primary (intended) | deepseek-v4-flash:free | opencode-zen | ❌ Not supported by opencode-zen |
| Current working | nex-agi/nex-n2-pro:free | openrouter | ✅ Works reliably |
| Secondary fallback | MiniMax-M2.7 | minimax.io | ✅ Works, slower (~2-3x) |

## Troubleshooting

**Symptom:** `ModelError: Model deepseek-v4-flash:free is not supported`
**Cause:** Delegation config pinned to a model/provider combo that doesn't work together.
**Fix:** User updates `~/.hermes/config.yaml` delegation section. Session restart needed for changes to take effect.

**Symptom:** `delegate_task` still fails after config.yaml update
**Cause:** Session caches delegation config at start. Restart the session, or use `execute_code` as fallback (runs on the parent's working model).

**Symptom:** Subagent modifies files in wrong repo
**Cause:** Subagent inherits CWD from parent session. If parent is in a vendored project copy, subagent drifts there.
**Fix:** Always set `workdir` on `delegate_task` or specify absolute paths in CONTEXT.
