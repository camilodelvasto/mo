"""Grove content loader — parse markdown files with YAML frontmatter."""
from pathlib import Path
import yaml


class ParseError(Exception):
    """Raised on invalid content."""
    pass


def load_post(path: Path) -> dict:
    """Parse one .md file with YAML frontmatter. Returns dict with frontmatter fields + body + _source_path."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")

    if not text.startswith("---"):
        raise ParseError(f"No frontmatter delimiter in {path}")

    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ParseError(f"Incomplete frontmatter in {path}")

    raw_yaml = parts[1].strip()
    if not raw_yaml:
        raise ParseError(f"Empty frontmatter in {path}")

    try:
        meta = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as e:
        raise ParseError(f"Malformed YAML in {path}: {e}") from e

    if not isinstance(meta, dict):
        raise ParseError(f"Frontmatter is not a mapping in {path}")

    if "title" not in meta:
        raise ParseError(f"Missing required field 'title' in {path}")

    meta["body"] = parts[2].strip()
    meta["_source_path"] = str(path)

    # Normalize boolean flags — always present, never .get() downstream.
    meta.setdefault("published", False)
    meta.setdefault("unlisted", False)
    meta.setdefault("encrypted", False)
    meta.setdefault("sticky", False)

    return meta


def scan_posts(posts_dir: Path) -> list[dict]:
    """Walk directory, parse all .md files. Adds content_path and is_section_index."""
    posts_dir = Path(posts_dir)
    results = []

    for md_file in sorted(posts_dir.rglob("*.md")):
        post = load_post(md_file)

        rel = md_file.relative_to(posts_dir)
        is_section_index = rel.stem == "index"

        if is_section_index:
            content_path = str(rel.parent)
        else:
            content_path = str(rel.with_suffix(""))

        # Normalize path separators
        content_path = content_path.replace("\\", "/")

        post["content_path"] = content_path
        post["is_section_index"] = is_section_index
        results.append(post)

    return results
