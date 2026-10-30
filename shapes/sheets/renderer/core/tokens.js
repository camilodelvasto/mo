/**
 * tokens.js — fetches /api/tokens and applies as CSS custom properties.
 */
export async function applyTokens() {
  const resp = await fetch('/api/tokens');
  const tokens = await resp.json();
  const root = document.documentElement;
  for (const [key, value] of Object.entries(tokens)) {
    root.style.setProperty(`--${key}`, value);
  }
}
