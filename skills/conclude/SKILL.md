---
name: conclude
description: Honcho write-back and proof format for the CONCLUDE phase. SHA requirements, conclusion ID structure, and what disqualifies a conclusion as invalid.
triggers:
  - conclude phase
  - honcho conclusion
  - proof format
  - sha requirement
---

# Conclude — Honcho Write-Back Phase

## When to Use

CONCLUDE runs after RETRO completes. It synthesizes what happened during the task run and writes durable conclusions to Honcho.

## Required Output Format

```
HONCHO: honcho://conclusion/<id> — <one-line summary of what was learned or decided>
DOCS: <action + reason: e.g. "UPDATE: auth flow changed in middleware.ts" or "NOT_NEEDED: trivial change">
CONTEXT: <action + reason: e.g. "UPDATE: new .techne/context file needed for workshop pattern" or "NOT_NEEDED: no context files affected">
```

All three lines are required. Omitting any line disqualifies the conclusion.

## HONCHO Line

- Must reference a real Honcho conclusion ID (not a placeholder)
- The URL format is `honcho://conclusion/<id>`
- The summary after `—` must describe a genuine conclusion, not a vague status
- Examples: `honcho://conclusion/abc123 — auth middleware pattern now centralized in middleware.ts`

## DOCS Line

Must state one of:
- `UPDATE: <file> — <reason>` — a docs file was updated during this run
- `CREATE: <file> — <reason>` — a new docs file was created
- `NOT_NEEDED: <reason>` — no docs were affected by this change

Cannot be blank or omitted.

## CONTEXT Line

Must state one of:
- `UPDATE: <file> — <reason>` — a context file was updated during this run
- `CREATE: <file> — <reason>` — a new context file was created
- `NOT_NEEDED: <reason>` — no context files were affected

Cannot be blank or omitted.

## SHA Requirement

When context files are updated, the submission must include a SHA:

```
SHA: sha:<40-char-hex>
```

The SHA must reference the git commit containing the context file updates. If context was updated but no SHA is provided, the conclusion is invalid.

**When SHA is NOT required:**
- `DOCS: NOT_NEEDED` AND `CONTEXT: NOT_NEEDED`
- Only docs or only context was updated (SHA still required if that thing was context)

## Honcho Conclusion IDs

Use the conclusion IDs assigned by Honcho during the run. These are proof of the conclusion's durability — a human or automated system can retrieve the conclusion later via Honcho.

If Honcho is unavailable, the conclusion is still recorded to `.techne/memory/` as a fallback, but the SHA discipline still applies.

## Git Commit Discipline

Before a CONCLUDE can claim `CONTEXT: UPDATE: <file>`, those context files **must already be committed**:

```bash
git add .techne/context/
git commit -m "context: refresh <context_file> after <task>"
```

The SHA in the conclusion proof must match a committed state — uncommitted context updates do not satisfy the proof requirement.

## What Disqualifies a Conclusion

A conclusion is **rejected** if:
- Any required line (HONCHO, DOCS, CONTEXT) is missing
- HONCHO line contains a placeholder or fake conclusion ID
- DOCS or CONTEXT line is blank or just `...`
- Context was updated but no SHA line is present
- The SHA does not match the actual git commit state

## Reference Implementation

The concluder agent (`agents/concluder.md`) enforces these rules:
- HONCHO line must describe a real conclusion, not a placeholder
- DOCS and CONTEXT must state either an action (UPDATE/CREATE/NOT_NEEDED) with a reason
- Keep it concise — the host runs the actual refresh, the agent only declares intent

## Hard Constraints

- All three lines (HONCHO, DOCS, CONTEXT) are required
- SHA is required when context files were updated
- Honcho conclusion IDs must be real (not fabricated)
- Context file updates must be git-committed before conclude claims them
- A trivial change with no meaningful conclusion is still a valid conclusion — use `NOT_NEEDED` with a reason

## Next Steps

- After CONCLUDE? → Pipeline complete, task moves to DONE status
- Verifying conclusion durability? → retrieve from Honcho via `honcho://conclusion/<id>`
- Context refresh? → `skills/refresh-context/SKILL.md`
