# File Authorship Convention

## Rule

When adding new content to an existing document, do NOT overwrite it.
Restore the original from git (or revert your change), then create
your own separate file.

## Pattern

```
Original: docs/retro/2026-06-22-session.md    ← leave intact
My take:   docs/retro/2026-06-22-inkforge.md    ← new file, my name
```

This prevents accidental data loss and keeps authorship clear.
Different perspectives go in different files — not different sections
of the same file.

## When to apply

- Session retros, reports, analysis docs where multiple versions exist
- Any file that was created by someone else (user, previous agent, tool)
- When the user says "revert that" or "make your own"

## When NOT to apply

- Personal notes, scratch files, work-in-progress docs you created
- Files explicitly given to you to edit (user says "update this doc")
