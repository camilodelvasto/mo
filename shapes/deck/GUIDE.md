# shapes/deck/

**Layer:** Interface — instance "deck"

Slideshow renderer with multi-theme support and document export.

## Structure

- `shape.manifest.yaml` — the contract
- `schemas/` — source schema definitions (deposited to content/schema/ on install)
- `themes/` — named themes: default, business, personal, pitch, sensata. Each has `tokens.yaml` + `style.css`
- `fonts/` — bundled woff2 families, auto-served via `build_fonts_css`
- `renderer/core/` — runtime-agnostic vanilla JS (layouts, theme resolution, markdown, effects)
- `renderer/shell-web/` — browser-specific (HTTP server, SSE)
- `renderer/shell-tauri/` — Tauri IPC adaptor (stub)
- `exporters/` — pptx.py, pdf.py (scaffold, not in v1)
- `preview/` — canonical sample bite

## Customization

Each theme lives in `themes/<name>/` with two files:

- `tokens.yaml` — design tokens: colors, type scale, spacing, reveal, effects
- `style.css` — structural CSS overrides, scoped to `[data-theme="<name>"]`

Reference a theme in your deck's metadata: `theme: sensata`. Users override themes at the corpus level — see `themes/GUIDE.md`.

## Validation

Run `moui check --shape deck` to validate this shape.
