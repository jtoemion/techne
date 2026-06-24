# oh-my-models

**Repo:** https://github.com/notfixingit3/oh-my-models  
**What it is:** CLI + OpenCode plugin companion for oh-my-openagent. View and bulk-set LLM models across all OMO agents with one command.  
**Status:** Private beta — not yet published to npm.

---

## Two Surfaces

| Capability | CLI | OpenCode Plugin |
|---|---|---|
| View current agent models | `list` / `status` | `/agent-models` |
| Apply presets | `use <preset>` | — (use CLI) |
| Set one agent | `set <agent> <model>` | `set_agent_model` tool |
| Set all agents | `set-all <model>` | `set_agent_model` per agent |
| Search live models | — | `/models-search <query>` |
| Smart recommendations | — | `/models-recommend <agent>` |
| Natural language control | — | Ask the LLM |

Plugin advantage: sees models actually connected right now. CLI advantage: scripting and direct changes.

---

## CLI Commands

```bash
oh-my-models list              # Table of all agents and current models
oh-my-models set <agent> <model>
oh-my-models set-all <model>
oh-my-models use <preset>      # Apply a smart preset
oh-my-models select            # Interactive picker
oh-my-models presets           # List all presets
oh-my-models init              # Create starter oh-my-openagent.jsonc
```

---

## Presets

| Preset | Strategy |
|---|---|
| `claude` | Opus for sisyphus/oracle, Sonnet elsewhere |
| `gpt` | GPT-5.5 / GPT-5 family |
| `gemini` | Gemini 3 Pro + Flash |
| `mixed` *(recommended)* | Best brains where it matters, fast models for research |
| `fast` | Cheapest capable models everywhere |
| `balanced` | Sonnet + Flash mix |

Aliases: `opus`, `sonnet`, `gpt5`, `mix`, `cheap`, `speed`, `quick`

---

## Config Discovery

Walks upward from CWD checking `.opencode/` at each level for:
1. `oh-my-openagent.jsonc` (preferred)
2. `oh-my-openagent.json`
3. `oh-my-opencode.jsonc` (legacy)
4. `oh-my-opencode.json` (legacy)

Falls back to `~/.config/opencode/` (XDG) or `~/.opencode/`.

---

## Beta Install

```bash
git clone https://github.com/notfixingit3/oh-my-models.git
cd oh-my-models
./scripts/beta-setup.sh        # guided
./scripts/beta-setup.sh --yes  # non-interactive, project-level
./scripts/beta-setup.sh --yes --global
```

Manual: build with `bun install && bun run build`, then add `file:///path/to/dist/index.js` to `opencode.jsonc` plugin array.

---

## Techne Relevance

- Narrow utility tool — not directly relevant to Techne's pipeline.
- The **preset system** (routing by task type to the right model tier) is conceptually similar to what Techne could do for per-phase model routing.
- The **config discovery** (walk upward from CWD) pattern is a clean UX for project-local config that Techne's `.techne/config.yaml` already approximates.
