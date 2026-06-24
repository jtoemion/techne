---
name: node-discipline
description: Enforces n8n-style module isolation — every module is exactly one of TRIGGER / CODE / GATEWAY. CODE nodes have zero lateral imports. GATEWAY nodes own all branching and merging. YAGNI gate prevents premature decomposition. Includes automated scan scripts and a ./next pipeline gate.
triggers:
  - node isolation
  - module boundary
  - layered architecture
  - code node
  - gateway node
  - trigger node
  - n8n style
  - node discipline
  - import boundary
  - lateral import
---

# Node Discipline — TRIGGER / CODE / GATEWAY

## The Founding

Every module is a NODE with exactly one role. Topology IS the constraint.
CODE = pure IO or computation, zero branching. GATEWAY = the only place branching, merging, and shaping lives. TRIGGER = starts a flow.

Without this: services import services (spread branching), hooks fetch from DAL (layering broken), CODE nodes check roles (testability halved).

## The Three Roles

| Role | What | Check |
|------|------|-------|
| TRIGGER | Starts a flow (page, context, cloud fn, cron) | Does it decide a path? → If yes, it's a GATEWAY |
| CODE | Single-responsibility IO/computation | Has `if (role)` or `switch (status)`? → Violation |
| GATEWAY | Routes, merges, shapes via IF/MERGE/SET | Does it CALL a CODE node for the work? → If no, it's doing two jobs |

## Hard Rules (abbreviated — see sub-skills for detail)

1. **One role per module** — a module that both fetches AND branches is two nodes in one file
2. **CODE nodes don't import CODE nodes** — data flows through GATEWAY nodes
3. **Branching lives only in GATEWAYs** — `if (role)` in a DAL is a violation
4. **GATEWAYs route, they don't compute** — heavy transformation lives in CODE
5. **YAGNI gate** — don't split until ≥2 consumers or independent change rate

## Automated Tools

| Tool | Command | Purpose |
|------|---------|---------|
| Scan violations | `python3 scripts/scan_node_violations.py -d .` | Greps for all 4 violation types |
| Classify module | `python3 scripts/classify_module.py path/to/file.ts` | Returns TRIGGER/CODE/GATEWAY |
| Generate map | `python3 scripts/generate_node_map.py -d . -o docs/node-map.md` | ASCII topology + inventory |
| Pipeline gate | `python3 scripts/node_gate.py -d .` | Called by ./next during VERIFY phase |

## Sub-Skills

| Topic | File |
|-------|------|
| CODE node deep reference | `skills/node-discipline/code-node.md` |
| Gateway patterns (IF/MERGE/SET) | `skills/node-discipline/gateway-patterns.md` |
| YAGNI decision tree | `skills/node-discipline/yagni-decision-tree.md` |
| ESLint rules for enforcement | `skills/node-discipline/eslint-enforcement.md` |

## Running the Gate in ./next

When this skill is loaded, `./next`'s VERIFY phase automatically runs `node_gate.py`.
If HIGH violations are found, the gate reports them but does NOT block — violations print in the phase report for the user to decide.

To make it a hard block: `./next --strict-nodes`

## Next Steps

- CODE node deep dive → `node-discipline/code-node.md`
- Gateway pattern reference → `node-discipline/gateway-patterns.md`
- YAGNI decision tree → `node-discipline/yagni-decision-tree.md`
- Run a violation scan → `python3 scripts/scan_node_violations.py -d /path/to/project`
- Generate a topology map → `python3 scripts/generate_node_map.py -d /path/to/project -o docs/node-map.md`
