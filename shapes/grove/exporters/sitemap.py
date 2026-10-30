"""Grove sitemap generator — sitemap.xml output."""
from xml.sax.saxutils import escape


def generate_sitemap(posts: list[dict], base_url: str) -> str:
    """Generate sitemap.xml string."""
    base_url = base_url.rstrip("/")

    urls = []
    for post in posts:
        loc = f"{base_url}{post['url_path']}"
        date = post.get("publish_date", "")
        urls.append(f"""  <url>
    <loc>{escape(loc)}</loc>
    <lastmod>{escape(date)}</lastmod>
  </url>""")

    urls_xml = "\n".join(urls)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls_xml}
</urlset>"""
