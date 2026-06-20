# Techne Pipeline — Phase Context Injection & Gate Contracts

How the orchestrator loop builds prompts for phases that need context, and what the gates enforce.

## Phase Context Injection

### RECALL
Injects task title + tags. Host searches Honcho. Gate: length > 20 chars.

### RETRO
Injects: (1) per-skill recurrence from `mistakes.count_by_skill()`, (2) routed skill content from `router.route()`, (3) full `mistakes.md`. Gate: length >= 100 + must reference ≥1 completed phase by name.

### CONCLUDE
Injects latest Context-Guard findings + proof requirements. Gate: HONCHO + DOCS + CONTEXT proof, uncommitted context check, SHA when context updated.

## Context-Guard Punch List

Context-Guard must emit `CONCLUDE PUNCH LIST` with:
- `DOCS: docs/<file>.md updated | NOT_NEEDED: <reason>`
- `CONTEXT: .techne/context/<path> refreshed | NOT_NEEDED: <reason>`
- `HONCHO: <durable fact(s) to write back>`

## CONCLUDE Proof Contract (full spec)

See `techne-orchestrator-pitfalls/references/conclude-proof-contract.md` for the complete validation spec including SHA regex, uncommitted check implementation, and unit test mocking pattern.

### Quick reference

```
HONCHO: honcho://conclusion/<id> — <what was saved>
DOCS: docs/<file>.md updated | NOT_NEEDED: <reason>
CONTEXT: .techne/context/<path> refreshed sha:<hex> | NOT_NEEDED: <reason>
```

When CONTEXT mentions a file path (not NOT_NEEDED), SHA is mandatory.
