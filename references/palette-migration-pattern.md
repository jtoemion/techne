# Palette Migration Pattern — Variable Aliasing + Component Sweep

A two-phase technique for replacing a design system's color palette without
breaking any component references.

## Phase 1 — Variable Aliasing Layer

The core insight: **never change component code for a pure-value palette swap.**
If your project uses CSS variables, you can define the old names as aliases
pointing to new value variables, and nothing breaks.

```css
/* — Step 1: define new canonical tokens — */
:root {
  --color-deep-green:      #1A3328;
  --color-antique-gold:    #B3914F;
  --color-cream:           #F5F4F0;
  --color-text-on-dark:    #D8D6CC;
}

/* — Step 2: alias old names to new values — */
:root {
  --green-900:  var(--color-deep-green);
  --green-800:  var(--color-deep-green-soft);
  --gold:       var(--color-antique-gold);
  --gold-light: var(--color-antique-gold-hover);
  --off-white:  var(--color-cream);
  --ink:        var(--color-deep-green);
}
```

**Benefits:**
- Zero component changes. Every `var(--gold)` in component scoped styles
  automatically picks up the new antique gold.
- Gradual migration allowed. Rename component references to the new names
  over time, at your own pace.
- Rollback is a single `:root` edit. No need to revert 50 component files.

## Phase 2 — Hardcoded Hex + RGBA Sweep

The variable alias covers all component references to the old CSS variables.
But component scoped styles (Svelte `<style>`, Vue `<style scoped>`, CSS
Modules) often have **hardcoded hex values** and **rgba() references** that
are invisible to the alias layer.

### What to search for

```bash
# Step 1: hardcoded hex values of the OLD palette
grep -r '#C9A84C\|#e8d49a\|#4a5568\|#d1d5db\|#203828\|#1c3b2a' src/

# Step 2: rgba() references to the OLD palette (most commonly missed)
grep -r 'rgba(201,168,76\|rgba(201, 168, 76' src/

# Step 3: any remaining hardcoded body-text or border colors
grep -r '#4a5568\|#d1d5db' src/
```

### Common misses

| What | Why it's missed |
|---|---|
| Button shadow `rgba(201,168,76,0.35)` | Not a hex value — only visible in an rgba grep |
| Outline button hover overlay `rgba(201,168,76,0.12)` | Same — rgba rather than hex |
| Body text `#4a5568` in section intros | Not connected to any CSS variable — hardcoded string |
| Form border `#d1d5db` | Light gray border — looks neutral but doesn't match new palette |
| Focus ring on inputs | Often uses a hardcoded hex that matches the old accent |

### Fix pattern

Replace each hardcoded value with either:
1. **A new CSS variable** (preferred — keeps the design token system intact)
2. **An rgba() tint of the new palette color** (for borders/shadows that need
   transparency, e.g. `rgba(26, 51, 40, 0.15)` for a deep-green tinted border)

## Phase 3 — Contrast Verification

After the swap, verify every new color pairing against WCAG 2.1 AA:

| Pairing | Formula | Min ratio |
|---|---|---|
| Text on background | `(L1 + 0.05) / (L2 + 0.05)` | 4.5:1 (normal text), 3:1 (large) |
| UI components | Same | 3:1 |

**Critical rule for palette migrations:** The accent color (gold, brand color)
will often fail contrast when placed as small text on a light/cream background.
This is expected — gold/amber tones have low relative luminance (~0.15–0.25)
against cream (~0.85). The solution is NOT to brighten the gold (which changes
the brand), but to **reserve the accent for dark-background contexts only**
(badges on dark sections, icon strokes, dividers, buttons on dark).

## When to use this pattern

- Client-requested palette refresh ("make it match the printed flyer")
- Brand consolidation after a merger/acquisition
- Dark mode implementation (mirror the technique with `:root [data-theme="dark"]`)
- Accessibility-driven color updates (increase contrast ratios globally)
