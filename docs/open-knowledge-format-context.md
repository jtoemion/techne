# Open Knowledge Format Context Standard

Source: https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing

Purpose: define how Techne should store durable building context so agents can
read, update, search, and share knowledge without needing a custom database or
vendor-specific runtime.

## Why OKF Fits Techne

Open Knowledge Format (OKF) treats knowledge as portable files:

- Markdown body for human-readable explanation.
- YAML frontmatter for small structured fields.
- File paths as stable concept identities.
- Normal markdown links as graph edges.
- Optional `index.md` files for progressive disclosure.
- Optional `log.md` files for chronological history.

This matches Techne's harness direction: context should live beside code, be
versioned in Git, be readable by humans, and be parseable by agents.

## Techne Standard

Use OKF-style files for durable building context.

Recommended location:

```text
.techne/context/
  index.md
  domains/
  decisions/
  runbooks/
  risks/
  skills/
  log.md
```

Every durable concept should be one markdown file with YAML frontmatter.

Minimum frontmatter:

```yaml
---
type: <concept type>
title: <human title>
description: <one sentence>
tags: [techne]
timestamp: <ISO-8601 timestamp>
---
```

Optional frontmatter:

```yaml
resource: <source URL, file path, command, or repo object>
status: draft | active | stale | deprecated
owner: <human or agent role>
related: [relative/path.md]
source_type: source-note | digest | runbook | decision | eval | skill | policy | state
```

## Concept Types

| Type | Use for | Example path |
|---|---|---|
| `domain` | Stable architecture area. | `.techne/context/domains/pipeline-core.md` |
| `decision` | Why an architectural choice was made. | `.techne/context/decisions/use-okf-context.md` |
| `runbook` | Repeatable operating procedure. | `.techne/context/runbooks/verify-output-hash.md` |
| `risk` | Known failure mode and mitigation. | `.techne/context/risks/context-bloat.md` |
| `skill-note` | Gotcha that may become a skill. | `.techne/context/skills/sha-gate.md` |
| `eval-note` | Evaluation scenario or benchmark note. | `.techne/context/evals/harness-isolation.md` |
| `policy-note` | Rule that may become deterministic policy. | `.techne/context/policies/immutable-artifacts.md` |
| `source-note` | Imported external source summary. | `.techne/context/sources/open-knowledge-format.md` |

## File Body Shape

Use this shape for most files:

```markdown
# <Title>

## Summary
One short paragraph.

## Applies When
- Trigger or situation.

## Rule
The durable rule, pattern, or decision.

## Evidence
- Source file, URL, command, test, or observed failure.

## Links
- [Related concept](../path/file.md)
```

Keep each concept focused. If a file starts covering multiple unrelated ideas,
split it into separate concept files and link them.

## Agent Rules

When adding building context:

1. Create or update the smallest relevant concept file.
2. Include YAML frontmatter.
3. Link related concepts with normal markdown links.
4. Add important chronology to `log.md` instead of burying it in prose.
5. Prefer active, curated context over raw transcript dumps.
6. If the context affects future work, update `.techne/context/index.md`.
7. If a concept becomes enforceable, promote it into a gate, eval, skill, or policy.

When reading building context:

1. Start at `.techne/context/index.md`.
2. Follow only the links needed for the current task.
3. Prefer files with `status: active`.
4. Treat `source-note` files as evidence, not automatically as policy.

## What Not To Do

- Do not create one giant context file.
- Do not paste full articles into context.
- Do not invent a new database unless files stop being enough.
- Do not make every source note a skill.
- Do not let raw notes become mandatory context for every task.

## Techne Adoption Path

1. Add this standard as the default building-context convention.
2. Use OKF-style frontmatter for new `.techne/context/` files.
3. Gradually convert important existing context docs when they are touched.
4. Add a lightweight validator only after several files exist and drift appears.
5. Keep the standard minimally opinionated: one concept per file, frontmatter,
   markdown links, Git history.

