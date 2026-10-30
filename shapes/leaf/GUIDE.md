# shapes/leaf/

**Layer:** Interface — instance "leaf"

Web renderer for posts and pages. Serves Markdown content with theme support.

## Structure

- `shape.manifest.yaml` — the contract
- `schemas/` — source schema definitions (deposited to content/schema/ on install)
- `themes/` — named token sets (YAML)
- `styles/` — CSS overrides per theme
- `renderer/core/` — runtime-agnostic vanilla JS
- `renderer/shell-web/` — browser-specific (HTTP server, SSE)
- `renderer/shell-tauri/` — Tauri IPC adaptor (stub)
- `adapters/` — deploy targets (rsync, S3, git-subtree)
- `preview/` — canonical sample bite

## Customization

Edit `themes/default.yaml` to change colors, typography, spacing.
Add `themes/custom.yaml` for a new theme.
Add `styles/custom.css` for structural overrides beyond tokens.
Reference the theme by name in your content's metadata: `theme: custom`.

## Validation

Run `moui check --shape leaf` to validate this shape.
