# Retro Proposal Format

This document specifies the exact format `apply_retro.parse_proposals()` expects.
Future GRPO scoring (B2/B3) should emit proposals conforming to this format.

## File location

Retro proposals are written to `.techne/memory/retro_proposals.md` by the retro
agent and consumed by `harness/apply_retro.py`.

## Overall structure

Each retro session produces a `## Retro — <ISO date>` block. Within that block,
zero or more proposal entries follow the formats below. The `apply_retro.py`
parser scans for `### PROPOSE` markers inside each `## Retro` block.

```
## Retro — 2026-06-20T12:00:00Z

### 7-Question Summary
GOAL: ...
DONE: ...
...

### PROPOSE ADD to skills/<file>.md
# weight: medium | seen: Nx | gate: yes/no
<exact text, under 3 lines>

### PROPOSE DELETE from skills/<file>.md
Entry: "<first line>"
Reason: weight:low, not seen in 10 runs

### PROPOSE RESOLVE mistake
Date: "<timestamp>"
Reason: root cause now covered by gate <gate_name>

### NO CHANGE
(if nothing meets thresholds)
```

## Proposal types

### PROPOSE ADD

Adds text to a skill file (appended at the end).

```
### PROPOSE ADD to skills/<file>.md
# weight: medium | seen: Nx | gate: yes/no
<exact text, under 3 lines>
```

- **target** — path after `to skills/`, e.g. `skills/nextjs.md`, `skills/tdd/mocking.md`
- **comment line** — starts with `# weight:` followed by metadata (parsed by humans, not by `parse_proposals`)
- **text** — the content to append (under 3 lines recommended). If the text contains `NO CHANGE` it is skipped
- **APPLIED** — once applied, an HTML comment `<!-- APPLIED: ... -->` is appended after the raw text

### PROPOSE DELETE

Removes an entry block starting with a given first line.

```
### PROPOSE DELETE from skills/<file>.md
Entry: "<first line>"
Reason: weight:low, not seen in 10 runs
```

- **target** — path after `from skills/`, relative to repo root
- **Entry** — the exact first line of the entry to remove, in double quotes
- **Reason** — human-readable explanation (parsed by humans, not by `parse_proposals`)

The parser finds the entry block starting with `## <first_line>` and removes it
(up to the next `## ` or EOF).

### PROPOSE RESOLVE

Marks a mistakes.md entry as RESOLVED.

```
### PROPOSE RESOLVE mistake
Date: "<timestamp>"
Reason: root cause now covered by gate <gate_name>
```

- **Date** — ISO timestamp of the mistake entry in `mistakes.md`, in double quotes
- **Reason** — why it's resolvable now

Calls `mistakes.mark_resolved(mistake_date)` to update `mistakes.md`.

## APPLIED tracking

After a proposal is successfully applied, `apply_retro.mark_applied()` appends an
HTML comment to the raw proposal text:

```
<!-- APPLIED: 2026-06-20T12:00:00Z | eval@apply=85 — Appended 2 lines to skills/nextjs.md -->
```

This comment is read back by `parse_proposals()` via the `"APPLIED" in m.group(0)`
check, which sets `proposal["applied"] = True`. Only non-applied proposals are
considered "pending".

## Target path resolution

| Example input | Resolves to |
|---|---|
| `skills/nextjs.md` | `<root>/skills/nextjs.md` |
| `skills/tdd/mocking.md` | `<root>/skills/tdd/mocking.md` |
| `nextjs.md` (bare) | `<root>/skills/nextjs.md` |

The resolver never produces a double `skills/skills/` prefix.

## Parser regex summary

```
PROPOSE ADD:  ### PROPOSE ADD to ([\w/\.]+)\n(.*?)(?=###|\Z)
PROPOSE DELETE:  ### PROPOSE DELETE from ([\w/\.]+)\s*\nEntry: "([^"]+)"
PROPOSE RESOLVE:  ### PROPOSE RESOLVE mistake\s*\nDate: "([^"]+)"\s*\nReason: (.+)
```

## Constraints for GRPO emission

- Each proposal MUST be inside a `## Retro — <date>` block (date is parsed as
  the `date` field on each proposal dict)
- Target paths MUST be repo-root-relative (e.g. `skills/nextjs.md`)
- ADD text SHOULD be under 3 lines
- DELETE entry first line MUST be the exact text of the `## Entry Title` in the
  target skill file
- RESOLVE date MUST match a `## [timestamp]` in `mistakes.md`
- Do NOT emit `### NO CHANGE` as a proposal — it's only a human-readable marker
