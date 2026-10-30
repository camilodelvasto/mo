# renderer/core/views/

Page-level view modules. Each exports a render function: data in, DOM out. Views control how the grove index, sections, and archives are rendered — not how individual posts are wrapped (that's layouts/).

- `grid.js` — masonry card layout (CSS columns)
- `list.js` — dense chronological list
- `single.js` — post page (selects layout, renders content within it)
- `collection.js` — curated sequence
- `archive.js` — filterable chronological list
