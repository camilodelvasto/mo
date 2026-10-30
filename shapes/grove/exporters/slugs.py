"""Grove slug resolver — derive URL paths from content, enforce uniqueness."""


class SlugConflictError(Exception):
    """Raised on duplicate URL paths."""
    pass


def resolve_slugs(posts: list[dict]) -> list[dict]:
    """Assign url_path to each post. Throws SlugConflictError on duplicates."""
    seen: dict[str, str] = {}  # url_path -> source_path

    for post in posts:
        slug = post.get("slug")  # optional frontmatter override
        base = slug if slug else post["content_path"]
        url_path = f"/{base.strip('/')}/"

        source = post["_source_path"]  # required — set by scan_posts
        if url_path in seen:
            raise SlugConflictError(
                f"Duplicate URL path '{url_path}' from {source} "
                f"(conflicts with {seen[url_path]})"
            )
        seen[url_path] = source
        post["url_path"] = url_path

    return posts
