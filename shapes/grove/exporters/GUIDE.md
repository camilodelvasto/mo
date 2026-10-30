# exporters/

Python build pipeline. Each module is a pure function: inputs in, files out.

- `build.py` — content → dist HTML; slug resolution; visibility enforcement
- `incremental.py` — content hash diff; only upload changed files
- `rss.py` — feed.xml (RSS 2.0) + feed.json (JSON Feed 1.1)
- `sitemap.py` — sitemap.xml generation
- `og.py` — Open Graph meta tag injection
- `redirects.py` — _redirects + redirects.caddy from post redirect fields
