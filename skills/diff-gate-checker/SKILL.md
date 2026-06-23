---
name: diff-gate-checker
description: Use when about to submit a phase result — run the diff or output through this before calling submit(). Saves 3-5 API calls per rejected submit.
triggers:
  - "check diff"
  - "pre-flight gate"
  - "validate output"
  - "gate check"
  - "before submit"
---

# Diff Gate Checker

A rejected submit costs 3-5 API calls (retry loop + re-submit). This tool catches format violations BEFORE they hit the gate — @@ markers missing, wrong SHA length, missing punch list sections.

## Lead — Phase-Specific Checks

```
implement:      @@ markers, +/- lines, --- a/ headers
context-guard:  PUNCH LIST section, DOCS line, HONCHO line
conclude:       SHA 40-char hex, HONCHO line, DOCS line
```

Run: `python3 scripts/diff_gate_checker.py --phase implement < mydiff.txt`

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "I'll just submit and let the gate tell me what's wrong" | Each retry costs tokens + time. Pre-flight is instant. |
| "The gate will accept narrative if the intent is clear" | Gates check FORMAT, not intent. @@ markers are required. |
| "I always get the format right the first time" | Every formatter in this session has had at least one correction. |

## Red Flags — STOP

- "Let me just try submitting and see"
- "The format looks right to me"
- "I'll fix it if the gate rejects"

## Next Steps

- Passed all checks? → submit with `skills/conclude/SKILL.md`
- Failed SHA check? → `scripts/conclude_proof_gen.py` to generate correct format
- Keep failing? → `skills/pipeline-health/SKILL.md`
