# shapes/leaf/themes/

Theme definitions for the leaf shape. One directory per theme.

## Structure

    themes/
        default/
            tokens.yaml    design tokens (colors, typography, spacing)
            style.css      visual rules, scoped to [data-theme="default"]
        dark/
            tokens.yaml
            style.css

## What goes where

- **`tokens.yaml`** — values. Colors, fonts, sizes, spacing. Anything a user might want to change by editing a number or a hex code.
- **`style.css`** — structure. Layout, selectors, pseudo-elements, rules that depend on HTML shape. Every selector must be scoped with `[data-theme="<name>"]`.

If changing a number is enough, edit the YAML. If you need new selectors or layout rules, edit the CSS. Both live in the same directory so they stay in sync.

## No JS in themes

Themes are tokens and CSS. Behavior — interactive widgets, client-side filtering, syntax highlighting — belongs in content artifacts or in the reserved `shapes/leaf/components/` directory (not implemented in v1). A theme file never contains JavaScript.

## Adding a theme

1. Create `themes/<name>/`.
2. Add `tokens.yaml` with the same top-level keys as `default/tokens.yaml`.
3. Add `style.css` with selectors scoped to `[data-theme="<name>"]`.
4. Reference it in content frontmatter: `theme: <name>`.

## Corpus overrides

User-level theme overrides live at `themes/leaf/<name>/` at the corpus root, not here. Files there take precedence over this directory. See `themes/leaf/GUIDE.md` at the corpus root for details.
