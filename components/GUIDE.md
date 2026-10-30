# Corpus-Level Components

Components are named, reusable content patterns with their own schema, rendering, and styles.

## Resolution Chain

1. `components/<name>/` at corpus root — highest precedence
2. `shapes/<shape>/components/<name>/` — shape-specific
3. Error if not found — no silent fallback

## Component Contract

Each component directory contains:
- `component.yaml` — name, description, fields schema, theme-requires
- `render.js` — exports `render(data, themeData) → DOM fragment`
- `style.css` — scoped styles, reads `--palette-*` and `--space-*` vars

## Theme Dependencies

If a component needs specific theme tokens, declare them in `theme-requires`.
`mo check` validates that the deck's theme defines all required tokens.
No fallbacks — if the theme doesn't have the token, it doesn't support the component.
