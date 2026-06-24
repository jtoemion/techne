# Oh My OpenAgent (OMO)

**Repo:** https://github.com/code-yeongyu/oh-my-openagent  
**Docs:** https://omo.dev/docs  
**What it is:** Multi-model agent orchestration framework for AI coding agents (OpenCode, Codex CLI).  
**Core philosophy:** Route different tasks to different models/agents based on their strengths. Not locked to one provider.

---

## Editions

| Edition | Target | Install |
|---|---|---|
| **Ultimate** | OpenCode | `bunx oh-my-openagent install` |
| **Light** | Codex CLI | `npx lazycodex-ai install` |

---

## Agent Hierarchy

### Orchestrators
| Agent | Role |
|---|---|
| **Sisyphus** | Main coordinator; plans and delegates work |
| **Hephaestus** | Deep autonomous worker (GPT-native) |
| **Prometheus** | Strategic planner; conducts interviews before coding |
| **Atlas** | Execution conductor; distributes tasks to specialists |

### Specialists
| Agent | Role |
|---|---|
| **Oracle** | Architecture and complex debugging |
| **Librarian** | Documentation and OSS code search |
| **Explore** | Fast codebase pattern discovery |
| **Multimodal Looker** | Vision and screenshot analysis |
| **Metis** | Gap analyzer for plans |
| **Momus** | Rigorous plan reviewer |
| **Sisyphus-Junior** | Task executor for delegated work |

---

## Category-Based Model Routing

| Category | Default Model | Use Case |
|---|---|---|
| `visual-engineering` | Gemini | Frontend/UI work |
| `ultrabrain` | GPT-5.5 | Complex reasoning |
| `deep` | GPT-5.5 | Autonomous work |
| `quick` | GPT-5.4 Mini | Speed over intelligence |
| `writing` | Claude Opus | Prose optimization |
| `artistry` | Gemini | Creative/design work |

---

## Three-Layer Architecture

```
Planning Layer:
  Prometheus (user interview) → Metis (gap analysis) → Momus (validation)
       ↓
Execution Layer:
  Atlas (reads approved plan, accumulates learnings, delegates)
       ↓
Worker Layer:
  Oracle / Explore / Librarian / Junior (specialized execution)
```

---

## Key Features

### Ultrawork Mode
Type `ultrawork` or `ulw`:
1. Explores codebase automatically
2. Researches patterns independently
3. Implements without micromanagement
4. Verifies with diagnostics
5. Continues until complete

### Prometheus Planning (Tab)
Tab → interview → Metis gap-analysis → Momus validation → `/start-work`

### Wisdom Accumulation
After each task, extracts: conventions, successful patterns, failures, gotchas, test results. Passes to all subsequent agents. (Session-scoped, not persisted cross-session.)

### Hashline (Hash-Anchored Edits)
Every file read tagged with content hash. Edits validate against hash before applying. Solves whitespace reproduction problem. Reported improvement: **6.7% → 68.3%** edit success rate.

### LSP + AST Tools
Workspace-level rename, go-to-definition, find-references, pre-build diagnostics, AST-aware rewrites.

### Team Mode
Parallel multi-agent coordination with shared mailbox and task lists. Powers concurrent implementations of `hyperplan` (adversarial planning) and `security-research` (vulnerability auditing).

### Ralph Loop
Self-referential development loop that works until 100% done.

### Handoff Generation (`boulder.json`)
Detailed context summaries for continuing work across sessions.

---

## Hooks & Configuration

- 54+ lifecycle hooks (Ultimate)
- Config: `oh-my-openagent.jsonc` with schema-validated autocomplete
- Override agent/category models, disable features via `disabled_*` arrays
- OpenClaw for external notifications (Discord, Telegram, HTTP)

## Telemetry

Anonymous DAU via PostHog. SHA256-hashed install ID, no person profiles. Opt-out: `OMO_DISABLE_POSTHOG=1`.

## Maintenance

```bash
bunx oh-my-openagent doctor   # 6-category health check
bunx oh-my-openagent boulder  # Inspect work state
```

---

## Techne Relevance

- **Hashline** is the highest-priority borrow candidate — hash-anchoring reads before edits is a narrow, concrete fix Techne doesn't have.
- **Multi-model routing per phase** (e.g. cheap model for RECALL, code-strong model for IMPLEMENT) is low-effort config-level improvement.
- **Prometheus adversarial planning** (interview → gap → validate) is more structured than Techne's `grill` skill; worth studying for a pre-`./next --init` planning skill.
- **LSP/AST tools** are high-value for IMPLEMENT phase precision but high-effort to integrate.
- **Wisdom accumulation** is session-scoped and model-driven; Techne's GRPO is more rigorous and persistent.
- OMO's discipline enforcement is prompt-based (soft); Techne's phase_guard is tool-call-layer (hard) — Techne is categorically stronger here.

## Sisyphus Model Compatibility Warning

Sisyphus is NOT model-agnostic. Only verified on: Claude (Opus 4.7+, Sonnet 4.6), Kimi (K2.5-K2.7), GLM (5, 5.1), GPT (5.4, 5.5). Using with MiniMax/Qwen/unlisted models risks breakage at next prompt update.
