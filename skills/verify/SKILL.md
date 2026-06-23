---
name: verify
description: Use when about to skip test execution or claim a green build without running SHA gate. Symptom-based: agent says "tests pass locally" or "this is just a comment change" to avoid running verification.
triggers:
  - verify changes
  - run tests
  - check build
---

# Verify

One line: Violating the letter violates the spirit — SHA gate hashes the actual test output. No faking green.

## Lead — SHA Gate Check

```text
Gate: grep -i "FAILED" in test output. Uppercase matters.
If "FAILED" present → SHA gate fails. Fix before proceeding.
Browser check: required for web apps — manual or Playwright verification.
```

## Body

```text
1. Run tests. Capture output.
2. Check for FAILED (uppercase). Case-sensitive grep.
3. Run SHA gate on test output if harness requires it.
4. Web app? Run browser check (Playwright or manual).
5. Gate passes only when output shows no FAILED.
```

## Rationalization Table

| Excuse | Reality |
|--------|---------|
| "Tests pass locally" | SHA gate hashes the actual output. Run it. |
| "This is just a comment change" | Then it takes 10 seconds to run tests. Do it. |
| "I'll just say tests pass" | The gate checks the output, not your word. |
| "Build looks fine" | FAILED could be in the output. Look for it. |

## Red Flags — STOP

- "I'll just say tests pass" → stop. Run them.
- "don't need to run tests for a comment change" → stop. 10 seconds.
- "locally everything works" → run the SHA gate.
- Claiming green without running → stop. Run verification.

## Next Steps

- Verify PASS → `skills/conclude/SKILL.md`
- Verify FAIL → return to `skills/implement/SKILL.md`
- Back to `skills/skill-router.yaml`
