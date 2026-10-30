"""Grove index generators — first-load metadata index and search index with tokens."""
import json
import re

_WORD_RE = re.compile(r"[a-z0-9]+")

REQUIRED_INDEX_FIELDS = ("title", "url_path", "content_path")
OPTIONAL_INDEX_FIELDS = ("excerpt", "publish_date", "tags")


def _tokenize(*texts: str) -> list[str]:
    """Extract unique lowercase word tokens from text strings."""
    tokens = set()
    for text in texts:
        tokens.update(_WORD_RE.findall(text.lower()))
    return sorted(tokens)


def generate_first_load_index(posts: list[dict], limit: int = 12, base_path: str = "") -> str:
    """JSON string of metadata-only entries, limited to `limit` posts.

    url_path is emitted with base_path prefix so JS consumers can navigate
    directly without needing to prefix at render time.
    """
    limited = posts[:limit]
    entries = []
    for post in limited:
        entry = {}
        for field in REQUIRED_INDEX_FIELDS:
            entry[field] = post[field]  # throws KeyError if missing
        if base_path:
            entry["url_path"] = base_path + entry["url_path"]
        for field in OPTIONAL_INDEX_FIELDS:
            value = post.get(field)
            if value is not None:
                entry[field] = value
        entries.append(entry)
    return json.dumps(entries, indent=2, ensure_ascii=False)


def generate_first_load_index_data(posts: list[dict], limit: int = 12, base_path: str = "") -> list:
    """Return first-load index entries as a list (not JSON string)."""
    limited = posts[:limit]
    entries = []
    for post in limited:
        entry = {}
        for field in REQUIRED_INDEX_FIELDS:
            entry[field] = post[field]
        if base_path:
            entry["url_path"] = base_path + entry["url_path"]
        for field in OPTIONAL_INDEX_FIELDS:
            value = post.get(field)
            if value is not None:
                entry[field] = value
        entries.append(entry)
    return entries


def generate_search_index_data(posts: list[dict], base_path: str = "") -> list:
    """Return search index entries as a list (not JSON string)."""
    entries = []
    for post in posts:
        title = post["title"]
        url_path = base_path + post["url_path"]
        content_path = post["content_path"]
        tags = post.get("tags")
        excerpt = post.get("excerpt")
        body = post.get("body")
        publish_date = post.get("publish_date")

        tokens = _tokenize(
            title,
            excerpt or "",
            body or "",
            " ".join(tags) if tags else "",
        )

        entry = {
            "path": content_path,
            "title": title,
            "url_path": url_path,
            "tokens": tokens,
        }
        if excerpt is not None:
            entry["excerpt"] = excerpt
        if tags is not None:
            entry["tags"] = tags
        if publish_date is not None:
            entry["date"] = publish_date

        entries.append(entry)
    return entries


def generate_search_index(posts: list[dict], base_path: str = "") -> str:
    """JSON string of all posts with tokenized content for client-side search.

    url_path is emitted with base_path prefix — same reasoning as
    generate_first_load_index.
    """
    REQUIRED_SEARCH_FIELDS = ("title", "url_path", "content_path")
    OPTIONAL_SEARCH_FIELDS = ("excerpt", "publish_date", "tags", "body")

    entries = []
    for post in posts:
        # Required fields — throws KeyError if missing
        title = post["title"]
        url_path = base_path + post["url_path"]
        content_path = post["content_path"]

        # Optional fields
        tags = post.get("tags")
        excerpt = post.get("excerpt")
        body = post.get("body")
        publish_date = post.get("publish_date")

        tokens = _tokenize(
            title,
            excerpt or "",
            body or "",
            " ".join(tags) if tags else "",
        )

        entry = {
            "path": content_path,
            "title": title,
            "url_path": url_path,
            "tokens": tokens,
        }
        if excerpt is not None:
            entry["excerpt"] = excerpt
        if tags is not None:
            entry["tags"] = tags
        if publish_date is not None:
            entry["date"] = publish_date

        entries.append(entry)
    return json.dumps(entries, indent=2, ensure_ascii=False)
