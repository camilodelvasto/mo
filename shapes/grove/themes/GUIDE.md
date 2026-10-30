# themes/

One directory per theme.

- `tokens.yaml` — design tokens: palette + color-* semantic mappings, typography, spacing
- `style.css` — optional structural CSS for theme-specific overrides

Token values become CSS custom properties. At build time, `exporters/themes.py` reads both `default/tokens.yaml` and `dark/tokens.yaml` and emits a single `<style id="grove-tokens">` block in each page's `<head>`:

```
:root { ... default tokens ... }
:root[data-theme="dark"] { ... dark tokens ... }
```

This is synchronous — tokens are available before first paint. No fetch, no FOUC. The `data-theme` attribute is set by an inline script in `<head>` that reads `localStorage` / `prefers-color-scheme`. The theme toggle in `renderer/core/theme.js` only flips the attribute.

## Adding a theme variant

Only `default` and `dark` are wired into the shell today. To add a third (e.g., `sepia`):

1. Create `themes/sepia/tokens.yaml` (copy default/ as template)
2. Add a third block to `themes.py::render_theme_css` under `:root[data-theme="sepia"]`
3. Update the toggle in `renderer/core/theme.js` to cycle through the variants

## Structural overrides (`style.css`)

`style.css` is optional. When present, its rules are read by
`exporters/themes.py::render_theme_css` and inlined (pre-paint) after the
token blocks in the same `<style>` element. Absent file → no overrides; no
default fires.

Scope every rule under `[data-theme="<name>"]` (the stubs show the form).
The shared sheets in `renderer/core/` are entirely `var()`-driven and carry
no `[data-theme]` structural rules, so a scoped override out-specifies the
base rule and wins the cascade regardless of source order. Do not use
`!important`.

Resolution is the theme directory `grove.theme` points at (or the shape
default). Corpus-level theme layering is not implemented.
