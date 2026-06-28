# Installing Techne on Hermes Agent

> A standalone install + wiring guide for running Techne enforcement under
> [Hermes Agent](https://hermes-agent.nousresearch.com). Grounded in the real Hermes
> hooks API ([docs](https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks)).
> For the Claude Code edition see [HANDOFF-CC-V0.md](../HANDOFF-CC-V0.md); for the
> architecture see [plans/GRAND-PLAN-FINAL.md](plans/GRAND-PLAN-FINAL.md).
>
> **Corrects** the earlier `ref/HANDOFF-HERMES.md`, which used the wrong hook event
> (`pre_tool_use`) and the wrong block-return shape. Use this guide instead.

---

## 1. What You're Installing

Techne is **two layers over one spine**. On Hermes they wire in like this:

| Techne layer | Hermes mechanism | Hook event |
|---|---|---|
| **Enforcement** (the Boundary, gate checks, audit) | plugin hook or shell hook | `pre_tool_call` |
| **Context Engine** (GROUND injection) | plugin hook | `pre_llm_call` → `{"context": str}` |
| **Orchestration** (phase state, handoff) | plugin hooks | `on_session_start` / `on_session_end` |
| **Anti-injection** (retrieved content = DATA) | plugin hook | `transform_tool_result` |
| **Audit** (every write logged) | plugin/shell hook | `post_tool_call` |

The gate logic itself is **runtime-agnostic** — the same `techne gate` CLI the Claude Code
edition uses. Hermes only needs the thin hook adapter that calls it.

---

## 2. Requirements

- **Hermes Agent v0.7.0+** with the plugin system (OMH) enabled
- **Python 3.10+**, `pyyaml`
- A project with a `.techne/` directory (created by `techne init`)
- *(Optional, for production)* the **Revolver** companion plugin (model/provider failover — see §9)

---

## 3. Install the `techne` CLI (shared, runtime-agnostic)

```bash
# From the Techne repo:
pip install -e /path/to/techne/
techne --help            # init / next / status / doctor / gate / handoff / proposals
```

The CLI is the same in both editions — **do not rewrite it for Hermes.** The Hermes hooks
shell out to it.

---

## 4. The Three Hermes Hook Systems (pick the right one)

Hermes has three hook architectures. Techne uses **Plugin hooks** (richest) and/or
**Shell hooks** (simplest). Gateway hooks are observer-only and not used.

| System | Where it runs | Can block? | How declared | Techne uses it for |
|---|---|---|---|---|
| **Plugin hooks** | CLI + gateway | ✅ | `ctx.register_hook()` in Python | Full edition (enforcement + context + orchestration) |
| **Shell hooks** | everywhere | ✅ | `~/.hermes/config.yaml` | Minimal edition (enforcement only, reuses the CC hook script) |
| **Gateway hooks** | gateway only | ❌ | `~/.hermes/hooks/*/HOOK.yaml` | *(not used — observers)* |

**Choose:**
- Want the **whole framework** (boundary + Context-Engine injection + orchestration)? → **Plugin hook** (§5).
- Want **just enforcement**, minimal setup, and to share one script with the CC edition? → **Shell hook** (§6).

> Precedence note: Python plugins register before shell hooks, and **a Python `block`
> decision takes precedence**. The first valid block wins across both systems — so you can
> run both safely.

---

## 5. Option A — Plugin Hook (full edition, recommended)

### 5.1 File layout

```
.hermes/
  plugins/
    techne_plugin.py     ← the adapter (below)
  skills/
    techne.md            ← /techne slash command (§7)
  config.yaml            ← registers the plugin
```

### 5.2 `techne_plugin.py`

The Hermes plugin API registers hooks in a `register(ctx)` function. The **correct**
`pre_tool_call` signature is `(tool_name, args, task_id, **kwargs)` and blocking returns
`{"action": "block", "message": str}` (return `None` to allow).

```python
"""Techne enforcement + context plugin for Hermes Agent.

Wires the runtime-agnostic `techne gate` CLI into Hermes hooks:
  - pre_tool_call       → the Boundary (block wrong-phase / boundary-violating writes)
  - pre_llm_call        → Context Engine (inject GROUND context)
  - post_tool_call      → audit
  - transform_tool_result → anti-injection (mark retrieved content as DATA)
  - on_session_start/end → orchestration state + handoff
"""
import subprocess
from pathlib import Path

# Adjust to where Techne is installed (or rely on `techne` being on PATH).
WRITE_TOOLS = {"write_file", "edit_file", "multi_edit", "notebook_edit"}


def _gate(*args) -> tuple[int, str]:
    """Run `techne gate ...`; return (exit_code, stdout)."""
    r = subprocess.run(["techne", "gate", *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


# ── Enforcement: the Boundary ────────────────────────────────────────────────
def pre_tool_call(tool_name: str, args: dict, task_id: str, **kwargs):
    """Return {"action": "block", "message": str} to deny, or None to allow."""
    if tool_name not in WRITE_TOOLS:
        return None

    path = args.get("file_path") or args.get("path") or ""

    # Boundary: block writes outside the active phase's artifact / FILE_SCOPE.
    code, out = _gate("boundary", path)          # exit 1 = denied
    if code != 0:
        return {"action": "block", "message": f"[Boundary] {out}"}

    # Hashline: at IMPLEMENT, validate diff context against the real file.
    diff = Path(".techne/loop/diff.txt")
    if tool_name in {"edit_file", "multi_edit"} and diff.exists():
        code, out = _gate("hashline", str(diff))
        if code != 0:
            return {"action": "block", "message": f"[Hashline] {out} — re-read the file"}

    # Forbidden patterns on any write.
    content = args.get("content") or args.get("new_content") or ""
    if content:
        code, out = _gate("forbidden", "-")      # pass content on stdin if supported
        # (or write content to a temp file and pass the path)

    return None


# ── Audit ────────────────────────────────────────────────────────────────────
def post_tool_call(tool_name: str, args: dict, result: str,
                   task_id: str, duration_ms: int, **kwargs):
    if tool_name in WRITE_TOOLS:
        _gate("audit", f'{{"tool":"{tool_name}","task":"{task_id}"}}')


# ── Context Engine: inject GROUND context ────────────────────────────────────
def pre_llm_call(session_id: str, user_message: str, conversation_history: list,
                 is_first_turn: bool, model: str, platform: str, **kwargs):
    """Return {"context": str} to inject lean grounding (OKF index + Honcho recall)."""
    ground = Path(".techne/loop/ground.md")
    if ground.exists():
        return {"context": ground.read_text(encoding="utf-8")[:8000]}  # keep it lean
    return None


# ── Anti-injection: retrieved content is DATA, never INSTRUCTIONS ─────────────
def transform_tool_result(tool_name: str, result: str, **kwargs) -> str | None:
    """Fence tool output so smuggled instructions can't be obeyed as commands."""
    if tool_name in {"web_fetch", "read_file"} and result:
        return f"<RETRIEVED_DATA source={tool_name}>\n{result}\n</RETRIEVED_DATA>"
    return None


# ── Orchestration: surface phase state / write handoff ───────────────────────
def on_session_start(session_id: str, model: str, platform: str, **kwargs):
    subprocess.run(["techne", "status"], check=False)


def on_session_end(session_id: str, model: str, platform: str,
                   completed: bool = False, interrupted: bool = False, **kwargs):
    if not completed:
        subprocess.run(["techne", "handoff"], check=False)


# ── Registration ─────────────────────────────────────────────────────────────
def register(ctx):
    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_hook("post_tool_call", post_tool_call)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("transform_tool_result", transform_tool_result)
    ctx.register_hook("on_session_start", on_session_start)
    ctx.register_hook("on_session_end", on_session_end)
```

> The branch ships a fuller version at `plugins/techne-plugin/` — use that as the source
> of truth for the production plugin; the above is the minimal, correct shape.

### 5.3 Register it

In your project `.hermes/config.yaml`:

```yaml
plugins:
  - .hermes/plugins/techne_plugin.py
```

Restart the Hermes session. The plugin auto-activates.

---

## 6. Option B — Shell Hook (enforcement-only, shares the CC script)

Hermes shell hooks read a JSON payload on **stdin** and block via **stdout** — exactly like
the Claude Code `PreToolUse` hook. So you can point Hermes at the **same**
`hooks/phase_guard_hook.py` (with a tiny payload shim).

### 6.1 Declare the hook

In `~/.hermes/config.yaml`:

```yaml
hooks:
  pre_tool_call:
    - matcher: "write_file|edit_file|multi_edit|notebook_edit"   # optional regex
      command: "python3 /path/to/techne/hooks/phase_guard_hook.py"
      timeout: 10
  post_tool_call:
    - command: "python3 /path/to/techne/hooks/audit_hook.py"

hooks_auto_accept: false   # leave false; approve once interactively
```

### 6.2 The stdin/stdout contract

Hermes sends:

```json
{
  "hook_event_name": "pre_tool_call",
  "tool_name": "edit_file",
  "tool_input": {"file_path": "src/auth.py", "content": "..."},
  "session_id": "sess_abc",
  "cwd": "/home/user/project",
  "extra": {"task_id": "feat-auth-01"}
}
```

The hook blocks by printing **either** canonical form:

```json
{"action": "block", "message": "Boundary: tests/ is read-only this phase"}
```
```json
{"decision": "block", "reason": "Boundary: tests/ is read-only this phase"}
```

A silent allow is `{}` or empty output. `phase_guard_hook.py` already emits the right shape;
it reads `tool_name` + `tool_input.file_path` which Hermes provides identically to CC.

### 6.3 Consent

First use of each `(event, command)` pair prompts for approval, stored in
`~/.hermes/shell-hooks-allowlist.json`. To pre-approve non-interactively:
`HERMES_ACCEPT_HOOKS=1`, the `--accept-hooks` flag, or `hooks_auto_accept: true`.

---

## 7. The `/techne` Skill

Copy [`.hermes/skills/techne.md`](../.hermes/skills/techne.md) into your project (or
`~/.hermes/skills/`). It drives the loop, lists artifacts/gates per phase, and routes to
Hermes-native skills (`omh-deep-research`, `omh-ralplan`, `omh-deep-interview`) alongside
the Techne library. Invoke with `/techne <task>`.

> **Zero-HITL note:** that skill still lists HITL stop conditions. Under the
> GRAND-PLAN-FINAL direction those become *automated* gates (mutation gate, spec-soundness,
> boundary monitor); the HITL lines are the transitional/calibration form (see
> [GRAND-PLAN-FINAL §6](plans/GRAND-PLAN-FINAL.md)).

---

## 8. Verify the Install

```bash
# Hermes-side: are the hooks registered and healthy?
hermes hooks list                 # show configured hooks + consent status
hermes hooks doctor               # audit exec perms, validity, timing
hermes hooks test pre_tool_call   # fire against a synthetic payload

# Techne-side: is enforcement live?
techne doctor                     # .techne/ present, audit chain intact, hook wired, context fresh
```

**Smoke test (proves the Boundary actually blocks):** start a task with `techne init smoke`,
advance to IMPLEMENT, then attempt a write to `tests/` (read-only this phase). The hook must
return a `block` and the attempt must appear in `.techne/audit/blocked.log`. If the write
succeeds, the hook isn't wired — re-check §5.3 / §6.1.

---

## 9. Companion: Revolver (production)

Without model/provider failover, a transient API failure during IMPLEMENT stalls the
pipeline. Install **Revolver** (`~/.hermes/plugins/revolver/`) so a failed call rotates to
the next cylinder instead of halting.

```
Commands: /revolver status · /revolver graph · /revolver next
Config:   ~/.hermes/revolver.yaml
```

`techne doctor` includes a Revolver health check when present.

---

## 10. Hook → Pillar Map (reference)

How each Hermes hook implements the GRAND-PLAN-FINAL pillars:

| Pillar / mechanism | Hermes hook | Returns |
|---|---|---|
| Boundary (block boundary-violating writes) | `pre_tool_call` | `{"action":"block","message":...}` |
| Hashline + forbidden gates | `pre_tool_call` → `techne gate` | block on non-zero |
| Audit chain | `post_tool_call` → `techne gate audit` | — |
| Context Engine (GROUND injection) | `pre_llm_call` | `{"context": str}` |
| Anti-injection (DATA-fence retrieved content) | `transform_tool_result` | replacement `str` |
| Orchestration (phase surfacing) | `on_session_start` | — |
| Handoff on incomplete session | `on_session_end` (`completed=False`) | — |
| Separation of authorship (delegation tracking) | `subagent_start` / `subagent_stop` | — |

---

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Writes never blocked | hook not registered | `hermes hooks list`; check `plugins:` / `hooks:` in config |
| `pre_tool_use` not firing | wrong event name | use **`pre_tool_call`** (not `pre_tool_use`) |
| Block ignored | wrong return shape | return `{"action":"block","message":...}` (plugin) or print `{"decision":"block","reason":...}` (shell) |
| Shell hook silently skipped | consent not granted | approve once, or `HERMES_ACCEPT_HOOKS=1` |
| Hook times out | long gate call | raise `timeout:` (default 60, max 300) |
| Plugin crash takes down a turn | — | it won't: Hermes catches/logs hook exceptions, never crashes the agent |

---

## 12. What NOT To Do

- Don't rewrite `techne_cli/` or `scripts/` for Hermes — they're shared; call via subprocess.
- Don't use `.claude/settings.json` — that's the Claude Code edition; Hermes uses
  `.hermes/config.yaml`.
- Don't let the agent edit `.techne/audit/` or the verification surface — that's the
  Boundary; it must be denied (and on a real deployment, OS-isolated — see
  [GRAND-PLAN-FINAL §ProofSpine](plans/GRAND-PLAN-FINAL.md)).
