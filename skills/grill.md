---
name: grill
description: Stress-test a plan against the actual codebase. Writes resolved terms to CONTEXT.md. Offers ADRs for hard, surprising, trade-off decisions. Ask one question at a time, wait for answer.
---

# Grill

## Before You Ask Anything

Read these first — answer from them before asking the user:

```
1. CONTEXT.md          — existing domain glossary (don't re-ask resolved terms)
2. docs/adr/           — existing decisions (don't re-litigate them)
3. Relevant source files (Glob/Grep — read the code, don't assume)
```

## Process — One Question at a Time

```
1. Read codebase → answer what you can without asking
2. Challenge terminology → "codebase calls this X, you said Y — which?"
3. Stress-test edge cases → "what happens when list is empty?"
4. Cross-reference → "your code does X but you said Y — which is right?"
5. Lock scope → "what is explicitly out of scope?"
```

**Wait for each answer before continuing to the next question.**

## Inline Actions (do these as decisions crystallize, not at the end)

### Update CONTEXT.md
When a term is resolved, write it immediately:

```markdown
## [TermName]
[1-2 sentence definition]. Distinct from [related term] because [reason].
<!-- resolved: YYYY-MM-DD, grill session -->
```

Do NOT add: implementation details, file paths, specs, code snippets.
CONTEXT.md is a glossary. Nothing else.

### Offer an ADR (sparingly)
Only when ALL THREE are true:
- Hard to reverse
- Surprising without context
- Real trade-off (alternatives existed)

If you offer one: `docs/adr/ADR-FORMAT.md` for the template.
Next number = count existing ADRs in `docs/adr/` + 1.

## Challenge Patterns

```
Fuzzy term        → "You said 'product' — do you mean the Product type or the SKU entity?"
Conflict with code → "Your code cancels entire Orders but you said partial cancellation
                      is possible — which is correct?"
Missing edge case  → "What happens when the user has no active session?"
Scope creep risk   → "That would also touch the billing module — is that in scope?"
```

## Output After Grilling

You have:
- [ ] CONTEXT.md updated with all resolved terms
- [ ] ADR(s) written for hard, surprising, trade-off decisions
- [ ] Locked interface (what callers see) documented
- [ ] Scope boundary explicit (what is NOT being built)
- [ ] Edge cases either handled or explicitly deferred

## Next Steps

- Design locked? → `skills/implementer.md`
- Need testable interface? → `skills/tdd/interface.md`
- Already in grill and hit a bug? → `skills/diagnose.md` (don't grill a bug)
