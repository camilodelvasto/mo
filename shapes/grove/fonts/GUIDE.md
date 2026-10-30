# fonts/

Self-hosted variable fonts. Copied to dist/fonts/ at build time.

`@font-face` with `font-display: swap`. No external requests.

Shares font set with deck: Inter, Fraunces, JetBrains Mono.
Font files are NOT duplicated — grove references the shared fonts directory at build time.
