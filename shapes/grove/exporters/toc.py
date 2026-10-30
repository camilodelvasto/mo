"""TOC extraction from rendered HTML."""
import re

_HEADING_RE = re.compile(r'<h([2-6])(?:\s+id="([^"]*)")?[^>]*>(.*?)</h\1>', re.DOTALL)
_TAG_RE = re.compile(r'<[^>]+>')


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub('', text)


def _slugify(text):
    text = _strip_tags(text)
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text.strip('-')


def extract_toc(html):
    """Extract h2-h6 headings from HTML. Returns list of {id, text, level}."""
    entries = []
    for match in _HEADING_RE.finditer(html):
        level = int(match.group(1))
        heading_id = match.group(2)
        text = _strip_tags(match.group(3)).strip()
        if not heading_id:
            heading_id = _slugify(text)
        entries.append({"id": heading_id, "text": text, "level": level})
    return entries
