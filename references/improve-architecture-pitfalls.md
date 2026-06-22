# Improve-Architecture — Session Notes (2026-06-22)

## Sequencing

Bug hunt first, THEN architecture. Fixing defects before looking for
deepening opportunities prevents false positives — a "shallow module"
that is actually a known bug reads differently once the bug is fixed.

## YAGNI Assessment Step

After GRILL, the agent should assess each candidate:

  Strong          → Worth doing. Clear before/after, measurable.
  Worth exploring → Merit but not urgent. Do if the user says "fix all remaining."
  Speculative     → Not worth code. Document the reasoning and skip.

When the user says "decide with best for app in mind" or "fix remaining
issue," the agent makes the call on each candidate and reports pass/skip
with the rationale. Do NOT re-ask the user for each candidate unless
there's a genuine trade-off that needs a human decision.

## Triggers Added

  - fix remaining architecture issues
  - decide with best for app in mind

## Candidate Report Format

Present as a 6-column table:

  Files     | Problem        | Solution | Benefit | Before/After | Strength
