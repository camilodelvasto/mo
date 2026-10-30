"""Assign download priority to rendered content entries.

Priority 0: app shell dependencies — index page, archive. Downloaded first.
Priority 1: recent posts (first priority_count by date), featured, section indexes.
Priority 2: everything else. Background download.
"""


def assign_priorities(entries: list[dict], priority_count: int) -> list[dict]:
    """Assign priority field to each entry based on type, date, and featured flag.

    entries must have: url_path, type. Posts must also have publish_date, featured.
    Returns the same list with 'priority' added to each entry.
    """
    for entry in entries:
        entry_type = entry.get("type", "post")

        if entry_type in ("index", "archive"):
            entry["priority"] = 0
            continue

        if entry_type == "section_index":
            entry["priority"] = 1
            continue

        if entry.get("featured"):
            entry["priority"] = 1
            continue

        # Default for posts — will be refined below
        entry["priority"] = 2

    # Assign priority 1 to the most recent priority_count posts (by date)
    posts = [e for e in entries if e.get("type") == "post" and e["priority"] == 2]
    posts.sort(key=lambda p: p.get("publish_date") or "", reverse=True)
    for post in posts[:priority_count]:
        post["priority"] = 1

    return entries
