---
name: ui-handoff
description: Generate developer handoff specs from a locked UI design. Covers layout, design tokens, component props, interaction states, responsive breakpoints, edge cases, animation details, and accessibility. Use when a design is ready for engineering.
triggers:
  - ui-handoff
  - handoff spec
  - design spec
  - developer handoff
  - spec sheet
---

# UI Handoff

Generate a developer-ready spec from a locked UI design. Every value must be exact — no undefined tokens, no "TBD."

## Prerequisite

Design must pass `ui-physics` before handing off. All values defined at Level 5 specificity.

## The Handoff Spec Format

```markdown
## Handoff Spec: [Feature/Screen Name]

### Overview
[What this screen does. User context. Tech stack if relevant.]

### Layout
[Grid system, column count, gutter values, max-width]
[ASCII wireframe if complex]

### Design Tokens

| Token | Hex / Value | Usage |
|-------|-------------|-------|
| `color-moss` | #4A5D23 | Active state background |
| `color-clay` | #C4704A | Button fill, warmth accents |
| `color-charcoal` | #1A1A1A | Primary text |
| `color-salt` | #FAFAFA | Primary surface |
| `radius-card` | 24px | Card border-radius |
| `shadow-card` | 0 4px 24px rgba(74,93,35,0.15) | Card elevation |
| `spacing-card-inner` | 32px | Card inner padding |
| `spacing-section` | 64px | Vertical section gap |
| `font-heading` | Inter Bold, 32px / 1.2 | Page headings |
| `font-body` | Inter Regular, 14px / 1.5 | Body copy |
| `motion-ease-out` | cubic-bezier(0.16, 1, 0.3, 1) | Default easing |
| `motion-duration-fast` | 150ms | Micro-interactions |
| `motion-duration-base` | 300ms | Transitions |
| `motion-duration-slow` | 500ms | Page-level reveals |

### Components

| Component | Variant | Props | States | Notes |
|-----------|---------|-------|--------|-------|
| Button | Primary | `size: sm\|md\|lg`, `disabled: bool` | default, hover, active, disabled, loading | Background slides in from left on hover (overflow: hidden) |
| Card | Default | `padding: 24px\|32px` | default, hover (shadow lift) | Inner padding 32px on desktop, 24px on mobile |
| Input | Text | `label: string`, `error: string\|null` | default, focus, error, disabled | Focus: 2px solid Clay border |
| ... | ... | ... | ... | ... |

### Responsive Behavior

| Breakpoint | Width | Layout Changes |
|------------|-------|----------------|
| Mobile | <640px | Single column, 16px padding |
| Tablet | 640-1023px | 2-column grid |
| Desktop | 1024-1279px | 3-column grid, 32px gap |
| Wide | ≥1280px | Max-width 1280px, centered |

### States and Interactions

| Element | State | Behavior | Animation |
|---------|-------|----------|-----------|
| Primary Button | Hover | Scale 1.02, shadow lift | 150ms ease-out |
| Primary Button | Active | Scale 0.98 | 100ms ease-in |
| Card | Hover | Shadow deepens, translateY -2px | 200ms ease-out |
| SVG Cursor | Enter | Fade in from opacity 0 | 300ms |
| SVG Cursor | Click | Scale 0.95 | 80ms |
| ... | ... | ... | ... |

### Edge Cases

- **Empty state**: [What to show when no data]
- **Long text**: Truncate with ellipsis at [N] characters
- **Slow connection**: Skeleton with [N]px blur, not spinner
- **Error**: Red border (#DC2626), error message below, 14px
- **Overflow**: Horizontal scroll, no text wrap

### Animation / Motion

| Element | Trigger | Animation | Duration | Easing |
|---------|---------|-----------|----------|--------|
| Page load | mount | Staggered fade + translateY(16px) | 500ms | ease-out-cubic |
| Card hover | mouseenter | shadow lift + translateY(-2px) | 200ms | ease-out |
| Button click | mousedown | scale(0.98) | 80ms | ease-in |
| Cursor | sequence | enter → move → click → move → fade | see lifecycle | linear |

### Accessibility

- Focus order: [defined tab sequence]
- ARIA labels: [list all labels needed]
- Keyboard: [Tab / Enter / Escape behavior]
- Contrast: [Minimum ratio, e.g. 4.5:1 for body, 3:1 for large text]
- Reduced motion: `@media (prefers-reduced-motion: reduce)` must disable all transitions

## Principles

1. **Don't assume** — If it's not specified, the developer will guess wrong. Specify everything.
2. **Use tokens, not values** — `spacing-md` not `16px` in the spec, but tokens must resolve to exact values in the token table.
3. **Show all states** — Default, hover, active, disabled, loading, error, empty.
4. **Describe the why** — "Collapses on mobile because users primarily use one-handed" helps developers make good calls.
5. **No TBD** — If a value is unknown, it must be resolved before handoff, not marked TBD.

## Output After Handoff

You have:
- [ ] All design tokens with exact hex/values
- [ ] Component spec with all states documented
- [ ] Responsive breakpoints with exact layout changes
- [ ] Animation lifecycle for every animated element
- [ ] Edge cases covered (empty, error, loading, overflow, i18n)
- [ ] Accessibility checklist complete
- [ ] No undefined tokens, no TBD values

## Next Steps

- Handoff spec complete? → `skills/implementer.md` (build from spec)
- Need to validate the spec against implementation? → `skills/ui-grill.md`
- Refine the design before handoff? → `skills/ui-physics.md`