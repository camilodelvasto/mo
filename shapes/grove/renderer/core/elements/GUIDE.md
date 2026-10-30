# renderer/core/elements/

UI element library. Independent of the component layer — usable in post content via directives, in component templates, and in Tauri shell views.

Each element is a plain JS module exporting a factory function. No state management, no lifecycle — DOM creation and event binding only.

- `button.js` — primary, secondary, ghost variants
- `input.js` — text, email, textarea with label binding
- `drawer.js` — slide-in panel with focus trap
- `slideshow.js` — sequential image/content carousel
- `banner.js` — dismissible notification strip

Not in v1. Reserved for Phase 7.
