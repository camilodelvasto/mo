# shapes/grove/

**Layer:** Interface — instance "grove"

Collection shape. Organizes leaf posts into a navigable, deployable static site. A grove has identity, structure, views, components, and a UI element library.

Grove consumes `post.v1.json` content. It does not modify leaf's schema. Extended frontmatter fields (unlisted, encrypted, redirects, og, translations, weight, related, layout, theme override) are read by grove's build pipeline — they pass through post.v1.json validation because that schema permits additional properties.

## Structure

- `shape.manifest.yaml` — the contract
- `schemas/` — grove.v1.json, collection.v1.json
- `config/` — grove.example.yaml + schema
- `renderer/core/layouts/` — post-level layout templates (article, quote, landing, minimal)
- `renderer/core/views/` — page-level views (grid, list, single, collection, archive)
- `renderer/core/components/` — header, footer, sidebar, card, search, form
- `renderer/core/elements/` — UI element library (button, input, drawer, slideshow, banner)
- `renderer/core/search/` — IndexedDB-backed client-side search
- `renderer/shell-web/` — Python dev server + service worker
- `renderer/shell-tauri/` — Tauri IPC adaptor (stub)
- `exporters/` — Python build pipeline (build, rss, sitemap, og, redirects, incremental)
- `adapters/` — deploy targets (hetzner, codeberg, s3, github pages)
- `themes/` — token sets + CSS
- `fonts/` — self-hosted variable fonts (shared with deck, not duplicated)
- `secrets/` — deploy credentials (gitignored)
- `preview/` — sample grove content for validation

## Validation

Run `moui check --shape grove` to validate this shape.
