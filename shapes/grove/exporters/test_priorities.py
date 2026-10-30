"""Tests for priority assignment."""
from priorities import assign_priorities


def test_index_gets_priority_0():
    posts = [{"url_path": "/", "type": "index"}]
    result = assign_priorities(posts, priority_count=12)
    assert result[0]["priority"] == 0


def test_archive_gets_priority_0():
    posts = [{"url_path": "/archive/", "type": "archive"}]
    result = assign_priorities(posts, priority_count=12)
    assert result[0]["priority"] == 0


def test_recent_posts_get_priority_1():
    posts = [
        {"url_path": "/post-1/", "type": "post", "publish_date": "2026-04-28",
         "featured": False},
        {"url_path": "/post-2/", "type": "post", "publish_date": "2026-04-27",
         "featured": False},
    ]
    result = assign_priorities(posts, priority_count=12)
    assert result[0]["priority"] == 1
    assert result[1]["priority"] == 1


def test_featured_post_gets_priority_1():
    posts = [
        {"url_path": "/old-featured/", "type": "post", "publish_date": "2020-01-01",
         "featured": True},
    ]
    result = assign_priorities(posts, priority_count=12)
    assert result[0]["priority"] == 1


def test_overflow_posts_get_priority_2():
    posts = [
        {"url_path": f"/post-{i}/", "type": "post", "publish_date": f"2026-04-{28-i:02d}",
         "featured": False}
        for i in range(15)
    ]
    result = assign_priorities(posts, priority_count=3)
    priorities = [p["priority"] for p in result]
    assert priorities[:3] == [1, 1, 1]
    assert all(p == 2 for p in priorities[3:])


def test_section_index_gets_priority_1():
    posts = [{"url_path": "/architecture/", "type": "section_index"}]
    result = assign_priorities(posts, priority_count=12)
    assert result[0]["priority"] == 1
