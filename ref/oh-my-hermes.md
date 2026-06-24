# Oh My Hermes (OMH)

**Repo:** https://github.com/witt3rd/oh-my-hermes  
**What it is:** Composable multi-agent orchestration skills for [Hermes Agent](https://github.com/NousResearch/hermes-agent).  
**Inspired by:** oh-my-claudecode; rebuilt natively for Hermes primitives.

---

## Skills

| Skill | Purpose |
|---|---|
| `omh-deep-research` | Multi-phase web research: decompose → parallel search → synthesize → verify citations |
| `omh-ralplan` | Consensus planning: Planner → Architect → Critic debate until agreement |
| `omh-ralplan-driver` | Dispatcher playbook for driving a `ralplan` run (context-package authoring, round dispatch, distillation, final review) |
| `omh-deep-interview` | Socratic requirements interview with coverage tracking |
| `omh-ralph` | Verified execution: implement → verify → iterate until done |
| `omh-ralph-driver` | Dispatcher playbook for driving a `ralph` run (plan-shape, parallel batching, evidence gathering, verifier discipline, strike categorization, Step-7 final architect review, commit hygiene) |
| `omh-ralph-task` | Executor discipline for a single `ralph` task (task-envelope contract, file-scope rigidity, stash-verify-against-HEAD for sibling-task isolation, commit-author override, structured report-back shape) |
| `omh-triage` *(v0.1)* | Multi-role consensus triage of an issue backlog — Maintainer (code-anchored) + Skeptic (pruning) |
| `omh-triage-driver` *(v0.1)* | Dispatcher playbook for driving a triage run — pre-flight backlog audit, role-pass dispatch, distillation, user sign-off gate |
| `omh-autopilot` | Full pipeline composing all skills end-to-end |

## Recommended Pipeline

```
omh-deep-research → omh-deep-interview → omh-ralplan → omh-ralph
```

Or fold `omh-deep-research` in as Phase -1 of `omh-autopilot` for unfamiliar domains.

---

## Optional Plugin

Adds hook-based role injection, atomic state management, and evidence gathering on top of the standalone skills.

- Requires Python 3.10+ and `pyyaml`
- Self-seeds `.omh/` directory in project on first use
- State management via `omh_state(action="init")`

---

## Cost Envelope (omh-deep-research)

- Happy path: ~5-8 `delegate_task` calls (3-5 researchers + 0-1 followup + 1 synthesist + 1 verifier)
- With one synthesis retry: up to ~10-12 calls
- 3-strike retry cap bounds worst-case at ~14-16 calls before BLOCKED

---

## Known Gaps

- Wiki/fact_store/memory persistence not yet integrated for `omh-deep-research` research artifacts. Durable interface is `.omh/research/{slug}-report.md` with `status: confirmed`; downstream skills consume it directly. Persisting into fact_store/wiki is a deferred item.
- Per-call subagent tool scoping for the `omh-deep-research` verifier may be unavailable depending on Hermes install; READ-ONLY contract is enforced by prose in `role-research-verifier.md` as fallback.

---

## Requirements

- Hermes Agent v0.7.0+
- Plugin additionally requires Python 3.10+ and `pyyaml`

## Install

```bash
hermes skills tap add witt3rd/oh-my-hermes
hermes skills install omh-deep-research omh-ralplan omh-ralplan-driver omh-deep-interview omh-ralph omh-ralph-driver omh-ralph-task omh-autopilot
```

---

## Key Design Decisions vs OMC

See [`docs/omc-comparison.md`](https://github.com/witt3rd/oh-my-hermes/blob/main/docs/omc-comparison.md) in repo.

## Techne Relevance

- `omh-ralph` / `omh-ralph-driver` pattern (implement → verify → iterate) maps closely to Techne's IMPLEMENT → VERIFY phases but is role-split across dispatcher + executor.
- `omh-ralplan` Planner/Architect/Critic consensus debate is similar to Techne's `grill` skill but multi-agent.
- `omh-triage` is a good reference for a structured triage skill Techne doesn't yet have.
- The `ralph-task` stash-verify-against-HEAD for sibling-task isolation is worth studying for parallel IMPLEMENT phase work.
