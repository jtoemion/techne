---
name: knowledge-graph
description: Use when you need to understand pipeline patterns — which phases fail most, which skills fire together, which mistakes recur. Not for real-time debugging; use pipeline-health for that.
triggers:
  - "knowledge graph"
  - "pipeline patterns"
  - "skill graph"
  - "phase outcomes"
  - "graph query"
---

# Knowledge Graph

The graph is already built (321 nodes, 320 edges from wikilinks + task DB + mistakes). This skill queries that existing data — it does not rebuild the graph.

## Lead — Two Layers

```
techne graph (pipeline):   python3 scripts/knowledge_graph.py status
                           python3 scripts/knowledge_graph.py phases
                           python3 scripts/knowledge_graph.py mistakes
                           python3 scripts/knowledge_graph.py skill <name>

project graph (files):     python3 scripts/knowledge_graph.py file <path>
                           python3 scripts/knowledge_graph.py search <term>
```

The techne graph answers *what's happening to the pipeline*. The project graph answers *what's happening in the codebase*.

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "I don't need the graph, I know the pipeline state" | You know the current state. The graph shows trends — phase A fails 3x more than phase B on auth tasks. |
| "The graph is just wikilinks" | wikilinks.json is one source. The script also reads tasks.db, mistakes.md, and rewards.db to give a full picture. |
| "Project graph is unnecessary" | Without it, you can't answer "what does this file connect to?" without reading every import. |

## Red Flags — STOP

- "I'll check the graph later"
- "I already know the pattern without querying"
- "The graph doesn't have useful data"
- "Let me just look at wikilinks.md directly"

## Next Steps

- Queries the techne graph → `skills/session-reporter/SKILL.md` for session-level view
- Queries the project graph → `skills/preflight/SKILL.md` for context amortization
- Graph seems wrong? → `skills/pipeline-health/SKILL.md`
