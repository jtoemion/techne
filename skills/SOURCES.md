# Vendored Capability Skills — Provenance

These skill folders are **vendored verbatim** from upstream. They are capability
skills (SKILL.md + `scripts/` + `reference/`), NOT Techne house-format cards — the
agent runs their bundled scripts as black-box tools. They are **exempt from Techne's
line caps and newspaper rules** (see `skills/writing-skill.md` → "Capability skills").

## Rule: do not edit the vendored internals

Keep `SKILL.md`, `scripts/`, `reference/`, `examples/`, and `LICENSE.txt` as-is so a
re-sync is a plain copy, not a hand-merge. All Techne glue (router entries, the
SKILL.md route table) lives OUTSIDE these folders. If you need a real change, send it
upstream or keep a thin documented patch — don't fork the engine.

## Re-sync

```bash
git clone --depth 1 https://github.com/anthropics/skills /tmp/_anthro_skills
cp -r /tmp/_anthro_skills/skills/<name> skills/<name>   # overwrite, review the diff
```

## Inventory

| Skill | Upstream | Commit copied | Runtime needs |
|-------|----------|---------------|---------------|
| `webapp-testing` | github.com/anthropics/skills/tree/main/skills/webapp-testing | c30d329 (2026-06-09) | Python + Playwright (`pip install playwright && playwright install chromium`) |
| `mcp-builder` | github.com/anthropics/skills/tree/main/skills/mcp-builder | c30d329 (2026-06-09) | Python or Node; `scripts/requirements.txt` for the eval scripts |

Considered but NOT adopted: `remotion` (remotion-dev/skills) — only add if programmatic
video becomes a real workflow; a large bundle that otherwise just taxes triggering.

## Known upstream issues (flagged in review — NOT patched here)

A code-review bot flagged real bugs in the vendored scripts. We deliberately do NOT
patch vendored internals (it forks the engine and breaks `cp -r` re-sync). These are
upstream's to fix; verify on the next sync, or report them to anthropics/skills.

- `webapp-testing/scripts/with_server.py` — server spawned with `stdout/stderr=PIPE`
  but pipes never read → deadlock if a server prints >64KB. Upstream fix: `DEVNULL`.
- `mcp-builder/scripts/evaluation.py` — agent loop uses `next()` on tool_use, so it
  drops parallel tool calls (API contract violation → 400). And `extract_xml_content`
  lacks a `None` guard. Only runs if you use mcp-builder's eval harness.

If one of these actually bites your usage, keep a THIN documented patch (it shows up in
the re-sync diff) rather than a silent fork.
