# renderer/core/layouts/

Post-level layout templates. Each layout defines the HTML shell a single post is wrapped in. Layouts control structure (what surrounds the content), not styling (that's the theme's job). They compose with themes: any layout works with any theme.

- `article.js` — default: heading, body, TOC sidebar, related strip, prev/next
- `quote.js` — large typographic treatment, centered, minimal chrome. Content is markdown-body-driven (quote text + attribution written in markdown, no extra frontmatter fields)
- `landing.js` — full-bleed sections, suppresses standard header/footer
- `minimal.js` — body only, no TOC, no related, no prev/next

Declared in post frontmatter: `layout: quote`. Default: `article` (inherits grove default if absent).

Not implemented in Phase 1. Templates built in Phase 5.
