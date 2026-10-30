# shapes/deck/themes/

One directory per theme. Each directory contains:

- `tokens.yaml` — design tokens: colors, type scale, spacing, reveal, effects
- `style.css` — structural CSS overrides, scoped to `[data-theme="<name>"]`

## Structure

    shapes/deck/themes/
        default/
            tokens.yaml
            style.css
        pitch/
            tokens.yaml
            style.css
        business/
            tokens.yaml
            style.css

## When to edit YAML vs CSS

**Edit `tokens.yaml` when:**
- Changing colors, fonts, type scale, spacing values
- Adjusting the reveal animation (type, stagger, speed)
- Tuning effect parameters (shimmer colors, underline width, stripe height)

**Edit `style.css` when:**
- Changing typography sizes or weights for specific elements
- Adjusting layout spacing that depends on typography
- Adding decorative treatments (borders, pseudo-elements)
- Overriding any layout behavior specific to this theme

Scope every rule with `[data-theme="<name>"]` so it only applies when this theme is active.

## Adding a new theme

1. Create a new directory matching the theme name
2. Add `tokens.yaml` with your design tokens (see existing themes as templates)
3. Add `style.css` with theme-scoped overrides (can start empty)
4. Reference the theme from a deck YAML: `theme: <name>`

## User overrides

Users customize themes by creating a matching directory at the corpus root: `themes/deck/<name>/`. See `<corpus>/themes/deck/GUIDE.md` for details. Corpus files take precedence over shape files and survive shape upgrades.
