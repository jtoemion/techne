---
name: ui-physics
description: Write UI prompts with the exact specificity that produces high-fidelity output. Define the math, the physics, the animation lifecycle, and the named design tokens — not vague intentions. Prerequisite for ui-craft and ui-grill.
triggers:
  - ui-physics
  - define the math
  - define the physics
  - too vague
  - generic AI output
  - how specific should this be
---

# UI Physics

**Rule: If you can't describe it in exact values, the LLM will guess wrong.**

This skill teaches the specificity standard that `examplePrompt.md` demonstrates. Before writing any UI prompt — for yourself or for an LLM — apply these constraints.

## The Five Levels of Specificity

| Level | What you wrote | What the LLM produces |
|---|---|---|
| 1 | "a nice green" | Random green, likely #22c55e or similar |
| 2 | "green: #22c55e" | Exact color, but isolated value |
| 3 | "background: #FAFAFA (60%), card: #F4F5F7 (30%), accent: #0066FF (10%)" | 60-30-10 palette with hex |
| 4 | "Moss background (#4A5D23) and Clay button (#C4704A)" | Named tokens, contextually appropriate |
| 5 | "Moss (#4A5D23) card surface, 24px border-radius, inner padding 32px, shadow: 0 4px 24px rgba(74,93,35,0.15)" | Complete component spec |

**Always target Level 5.** Level 3 is acceptable as a starting point. Level 1 is a failure.

## The Math You Must Define

For every UI element, specify:

```
COLOR     → Exact hex or named token (not "a warm tone")
SPACING   → Exact px/rem value (not "generous padding")
RADIUS    → Exact border-radius value (not "rounded")
MOTION    → Exact ms duration + exact easing name (not "smooth")
TYPOGRAPHY → Exact size + weight + line-height (not "readable")
SHADOW    → Exact values: offset-x, offset-y, blur, color, alpha
```

## Animation Lifecycle Template

For any animated element, define the complete sequence:

```
ENTER     → How does it appear? (fade? slide? scale from 0.5?)
MOVE/ACT  → What exactly happens? (cursor: scale-down to 0.95 on mousedown)
STATE     → What does "active" look like? (exact background, border, shadow)
EXIT      → How does it disappear? (fade to opacity: 0 over 200ms)
```

Example from a real prompt:
> "A weekly grid (S M T W T F S) where an automated SVG cursor enters, moves to a day, clicks (visual scale-down to 0.95), activates the day (background transitions to Moss), then moves to the Save button (border: 2px solid Clay) before fading out (opacity: 0, 300ms ease-out)."

## Named Design Tokens Over Raw Values

Use named tokens that carry semantic meaning:

```
MOSS      → #4A5D23 (active states, success indicators)
CLAY      → #C4704A (buttons, warmth accents)
CHARCOAL  → #1A1A1A (text, deep backgrounds)
SALT      → #FAFAFA (primary surfaces)
```

Never say "use green." Say "use Moss (#4A5D23) for active states."

## The Anti-Generic Directive

Include this in every UI prompt:

> "Do not build a website; build a digital instrument. Eradicate all generic AI patterns: no purple gradients on white, no center-aligned hero text, no Lorem ipsum, no linear gradient backgrounds, no Inter font."

## CSS Variable Constraints

Force the LLM to use CSS variables with real values, not undefined tokens:

```
/* Bad */
--button-bg: green;

/* Good */
--button-bg: #0066FF;
--button-bg-hover: #0052CC;
--button-bg-active: #003D99;
```

## Reject Vague Terms

Replace every vague term with its exact equivalent:

| Never say | Say instead |
|---|---|
| "animate nicely" | "fade in over 400ms ease-out-cubic" |
| "rounded" | "border-radius: 16px" |
| "premium feel" | "contrast ratio 8:1, shadow: 0 4px 24px rgba(0,0,0,0.12)" |
| "modern" | "32px heading, 1.5 line-height, 8-point grid spacing" |
| "responsive" | "breakpoints: 640px / 768px / 1024px / 1280px — card goes 3-col → 2-col → 1-col" |
| "accessible" | "WCAG AA, minimum contrast 4.5:1, focus-visible: 2px solid Clay" |

## Output After Physics

You have:
- [ ] Every color → exact hex or named token
- [ ] Every spacing value → exact px/rem
- [ ] Every animation → exact ms + easing name
- [ ] Every component state → defined (default, hover, active, disabled, loading, error)
- [ ] Named design tokens with semantic names
- [ ] Anti-generic directive included

## Next Steps

- Design physics defined? → `skills/ui-craft.md` (prompt the LLM with these constraints)
- Evaluating existing UI? → `skills/ui-grill.md` (force the same specificity on the human)
- Generate handoff spec? → `skills/ui-handoff.md`