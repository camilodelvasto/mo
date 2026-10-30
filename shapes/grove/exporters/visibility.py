"""Grove visibility filter — published/unlisted/encrypted rules.

Production builds gate on published=True. Serve mode includes drafts
so authors can preview unpublished posts locally.
"""


def _is_published(post: dict) -> bool:
    return post["published"] is True


def _is_draft(post: dict) -> bool:
    return post["published"] is not True


def _is_unlisted(post: dict) -> bool:
    return post["unlisted"] is True


def _is_encrypted(post: dict) -> bool:
    return post["encrypted"] is True


def _published_only(posts: list[dict]) -> list[dict]:
    return [p for p in posts if _is_published(p)]


def _published_not_unlisted(posts: list[dict]) -> list[dict]:
    return [p for p in posts if _is_published(p) and not _is_unlisted(p)]


def _published_not_unlisted_not_encrypted(posts: list[dict]) -> list[dict]:
    return [p for p in posts if _is_published(p) and not _is_unlisted(p) and not _is_encrypted(p)]


def _all_posts(posts: list[dict]) -> list[dict]:
    return list(posts)


def _not_unlisted(posts: list[dict]) -> list[dict]:
    return [p for p in posts if not _is_unlisted(p)]


# Public API — named for intent, backed by shared predicates

# Production: only published posts reach the output
filter_for_build = _published_only
filter_for_index = _published_not_unlisted
filter_for_feed = _published_not_unlisted
filter_for_sitemap = _published_not_unlisted_not_encrypted
filter_for_search = _published_not_unlisted_not_encrypted

# Serve: drafts included so authors can preview locally
filter_for_serve_build = _all_posts
filter_for_serve_index = _not_unlisted
