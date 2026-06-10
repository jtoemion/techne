---
name: ui-grill
description: Stress-test UI design decisions while the design is still undecided. One question at a time, forces math and physics on vague choices, writes resolved terms to CONTEXT.md, offers ADRs for hard trade-offs. Use to LOCK a design before any code exists. Once the design is locked and you're prompting a model to build it, use ui-craft instead.
triggers:
  - ui-grill
  - grill the ui
  - design grill
  - stress test the design
  - ui review
---

# UI Grill

Stress-test UI design decisions. Forces math and physics on vague choices. One question at a time, wait for answer.

## Before You Ask Anything

Read these first — answer from them before asking the user:

```
1. CONTEXT.md          — existing UI glossary (resolved terms, locked values)
2. docs/adr/           — existing design decisions
3. Reference assets    — any existing design files, tokens, or mockups shared in chat
```

## Pre-Questionnaire: Commit to a Conceptual Direction

Before asking about colors or spacing, force the user to pick an extreme. This is non-negotiable:

> "What is the visual direction? Pick one:
> - Brutalist/raw (high contrast, exposed structure, no decoration)
> - Refined minimal (precision spacing, restricted palette, purposeful white space)
> - Retro-futuristic (geometric shapes, warm metallics, CRT-era glow)
> - Organic/natural (earth tones, irregular shapes, handcrafted feel)
> - Luxury/refined (dark backgrounds, gold accents, generous negative space)
> - Playful/toy-like (bright saturated colors, bouncy animations, rounded forms)
> - Editorial/magazine (large serif type, asymmetric grid, bold hierarchy)
> - Industrial/utilitarian (monospace type, exposed grid, function-first)"

Document the chosen direction in CONTEXT.md as the first entry. All subsequent decisions must serve this direction. If a choice contradicts it, reject it.

## The One-Question Loop

```
1. Read existing context → answer what you can without asking
2. Force the math → "What exact hex value?" / "What px radius?" / "What easing curve?"
3. Challenge vague terms → "You said 'premium' — what does that look like in pixels?"
4. Reject generic AI patterns → no generic gradients, no Lorem ipsum, no center-aligned walls of text
5. Lock scope → what is explicitly out, what stays in
```

**Wait for each answer before continuing.**

## What to Challenge

For every UI decision the user makes, force at least:

| Vague term | Force this |
|---|---|
| "premium feel" | Contrast ratio, exact shadow values, spacing scale |
| "nice green" | Exact hex or HSL value |
| "animate nicely" | Exact duration (ms), easing function (ease-in-out-cubic etc.) |
| "rounded" | Exact border-radius value (px or rem) |
| "responsive" | Breakpoint list and what changes at each |
| "accessible" | WCAG level (A/AA/AAA), minimum contrast ratio |
| "modern" | Reference screenshot or exact style anchors |

## Anti-Generic-AI-Pattern Checklist

Reject any output containing:
- Linear gradients as background fills (use solid or subtle noise textures)
- Center-aligned hero text with no visual weight
- Generic placeholder images (use Unsplash URLs, specific)
- "Lorem ipsum" anywhere
- Icon dumps (use only what the feature needs)
- CSS variables without actual values defined

## Inline Actions

### Update CONTEXT.md (as decisions lock)

```markdown
## [UI_TermName]
[Value or range]. Distinct from [related term] because [reason].
<!-- resolved: YYYY-MM-DD, ui-grill session -->
```

Include: color values, spacing tokens, animation durations, breakpoint thresholds.

### Offer an ADR (only when ALL THREE are true)

- Hard to reverse
- Surprising without context
- Real trade-off (alternatives existed)

Use `docs/adr/ADR-FORMAT.md`. Next number = count existing ADRs + 1.

## Output After Grilling

You have:
- [ ] CONTEXT.md updated with all resolved UI terms
- [ ] ADR(s) written for hard trade-off decisions
- [ ] Locked visual spec documented (colors, spacing, motion)
- [ ] Scope boundary explicit (what is NOT being built)
- [ ] Anti-generic-AI-pattern violations caught

## Next Steps

- Design locked, ready to build? → `skills/implementer.md`
- Need a domain-specific grill for this project? → create `skills/<domain>-ui-grill.md`
- Evaluating an existing UI against a spec? → run through the anti-generic checklist above