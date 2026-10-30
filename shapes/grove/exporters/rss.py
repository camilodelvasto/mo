"""Grove RSS/JSON feed generator — RSS 2.0 XML and JSON Feed 1.1."""
import json
from xml.sax.saxutils import escape


def generate_rss_xml(posts: list[dict], grove: dict, base_url: str) -> str:
    """Generate RSS 2.0 XML string. base_url is build-derived, not in grove."""
    base_url = base_url.rstrip("/")
    max_items = grove["rss"]["max_items"]
    limited = posts[:max_items]

    items = []
    for post in limited:
        link = f"{base_url}{post['url_path']}"
        excerpt = post.get("excerpt")  # optional
        publish_date = post.get("publish_date")  # optional

        desc_xml = f"\n      <description>{escape(excerpt)}</description>" if excerpt else ""
        date_xml = f"\n      <pubDate>{escape(publish_date)}</pubDate>" if publish_date else ""

        items.append(f"""    <item>
      <title>{escape(post['title'])}</title>
      <link>{escape(link)}</link>{desc_xml}{date_xml}
    </item>""")

    items_xml = "\n".join(items)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{escape(grove['title'])}</title>
    <link>{escape(base_url)}</link>
    <description>{escape(grove['description'])}</description>
    <language>{escape(grove['lang'])}</language>
{items_xml}
  </channel>
</rss>"""


def generate_json_feed(posts: list[dict], grove: dict, base_url: str) -> str:
    """Generate JSON Feed 1.1 string. base_url is build-derived, not in grove."""
    base_url = base_url.rstrip("/")
    max_items = grove["rss"]["max_items"]
    limited = posts[:max_items]

    items = []
    for post in limited:
        entry = {
            "id": post["content_path"],
            "title": post["title"],
            "url": f"{base_url}{post['url_path']}",
        }
        excerpt = post.get("excerpt")  # optional
        if excerpt is not None:
            entry["summary"] = excerpt
        publish_date = post.get("publish_date")  # optional
        if publish_date is not None:
            entry["date_published"] = publish_date
        items.append(entry)

    feed = {
        "version": "https://jsonfeed.org/version/1.1",
        "title": grove["title"],
        "home_page_url": base_url,
        "feed_url": f"{base_url}/feed.json",
        "description": grove["description"],
        "language": grove["lang"],
        "items": items,
    }

    return json.dumps(feed, indent=2, ensure_ascii=False)
