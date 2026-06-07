---
name: ui-craft
description: Get high-fidelity UI from a basic LLM by treating it like an inexperienced junior designer. Section-by-section prompting, forced visual math (60-30-10 rule, exact spacing), iterative refinement loop. Use when generating, iterating, or evaluating UI code from an LLM.
triggers:
  - ui-craft
  - prompt an LLM for UI
  - get better UI from LLM
  - treat LLM like junior designer
  - high fidelity UI from LLM
---

# UI Craft

Get high-fidelity UI from a basic LLM. Treat the LLM like an inexperienced junior designer — break everything down, force the math, iterate.

## The 60-30-10 Rule (forced on every prompt)

Every color palette you give the LLM must specify:
- **60%** — dominant background surface (exact hex)
- **30%** — secondary surfaces, cards (exact hex)
- **10%** — CTA, active states, accents (exact hex)

Example:
> "Background: #FFFFFF (60%). Card surface: #F4F5F7 (30%). Primary button: #0066FF (10%)."

Never let the LLM pick its own palette. Lock it before generating.

## The Four-Step Workflow

```
1. SECTION-BY-SECTION   — Never ask for an entire page at once
2. LAYOUT BLOCKS         — Define spacing before asking for content
3. CONSTRAINTS FIRST     — Colors, type scale, grid, then content
4. REFINE LOOP           — Critique specific values, not vague quality
```

### Step 1: Section-by-Section

Bad: "Build a login page."
Good: "Build the header. Logo left, nav right. 64px height. Sticky. Border-bottom: 1px solid #E5E7EB."

Do the same for: Hero → Content blocks → Sidebar → Footer. One section at a time.

### Step 2: Layout Blocks (ASCII wireframes work)

```
┌──────────────────────────────────────┐
│ HEADER: 64px, sticky, 1px border    │
├──────────────────────────────────────┤
│ HERO: 100vh - 64px, center content  │
│   Card: 480px max-w, 32px padding   │
│   Card: 24px border-radius          │
├──────────────────────────────────────┤
│ FEATURES: 3-col grid, 8px gap        │
│   Each card: 16px padding           │
└──────────────────────────────────────┘
```

Give the LLM this before any code. Forces spatial reasoning.

### Step 3: Constraints First (always)

Lock these before asking for content:

| Constraint | Example |
|---|---|
| Color palette | 60-30-10 with exact hex values |
| Typography | Inter, 32/24/18px headings, 14px body, 1.5 line-height |
| Spacing grid | 8-point grid for all margins/padding |
| Border-radius | Exact values, not "rounded" |
| Breakpoints | Mobile first, then 768px, 1024px, 1280px |
| Animation | Duration + easing curve, not "animate nicely" |

### Step 4: Refine Loop (specific corrections)

Bad: "The button looks bad."
Good: "Gap between buttons is 8px — change to 16px. Primary button needs `box-shadow: 0 2px 8px rgba(0,102,255,0.25)`. Border-radius on card is 16px, not 8px."

Each correction must name the specific property and value, not a quality judgment.

## LLM Constraint Checklist

Before sending any prompt to an LLM, verify:
- [ ] 60-30-10 palette with hex values included
- [ ] Typography scale with exact sizes
- [ ] Spacing grid defined (8-point)
- [ ] Border-radius values specified
- [ ] Animation durations and easing defined
- [ ] Responsive breakpoints listed
- [ ] Design system referenced (Tailwind UI, Material 3, Shadcn, etc.)
- [ ] Section boundaries defined (not "build a page")

## Design System Anchoring

If you have a reference screenshot or existing UI you like:

1. Analyze it: "What are the exact padding values, color contrast ratios, font sizes?"
2. Convert to constraints: "Heading: 32px Inter Bold. Card padding: 24px. Border-radius: 16px."
3. Feed to LLM: "Apply the same styling rules from the reference to this new form."

Reference UI libraries the LLM must follow (pick one):
- Tailwind UI
- Material Design 3
- Shadcn UI
- Radix UI primitives

## Anti-Generic Output Rejection

When the LLM produces output, reject anything with:
- Linear gradient backgrounds (solid + noise texture only)
- "Lorem ipsum" text
- Generic placeholder images (must provide specific Unsplash URLs)
- Undefined CSS variables (must have actual values)
- Center-aligned hero text with no visual weight

## Iterative Refinement Template

```
CURRENT OUTPUT:
[paste code or describe what rendered]

ISSUE 1: [specific problem]
FIX: [exact property + value]

ISSUE 2: [specific problem]
FIX: [exact property + value]

REMAINING: [what still needs work]
```

Repeat until locked.

## Output After Crafting

You have:
- [ ] Palette locked (60-30-10 with hex)
- [ ] Type scale locked (exact sizes + font)
- [ ] Spacing system locked (8-point grid)
- [ ] Section layouts defined (ASCII wireframe)
- [ ] Animation values defined (ms + easing)
- [ ] Refinement loop completed
- [ ] Anti-generic violations caught and corrected

## Next Steps

- Design locked? → `skills/ui-grill.md` (stress-test the decisions you just made)
- Ready to build? → `skills/implementer.md`
- Need domain-specific design constraints? → create `skills/<domain>-design.md`