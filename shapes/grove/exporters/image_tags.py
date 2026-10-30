"""Image HTML post-processing — transform <img> to <picture> with responsive variants.

Operates on rendered HTML string (after markdown-it). Uses the image manifest
to build <picture> elements with <source> tags for each format/width.

Standalone images (sole child of <p>) get <figure> + <figcaption>.
Inline images get <picture> without wrapping.
SVG/GIF passthrough: <figure> wrapping but no <picture>.
External URLs: skipped entirely (no manifest lookup).

Alt text conventions for alignment/width:
  ![Caption|right](src)  → <figure class="align-right">
  ![Caption|80%](src)    → <figure style="max-width:80%">
  ![Caption|right|60%]   → both
"""
import re
from xml.sax.saxutils import escape
from images import FORMAT_TO_MIME

# Match <p> containing only an <img> (standalone detection)
_STANDALONE_RE = re.compile(
    r'<p>\s*(<img\s[^>]+>)\s*</p>',
    re.DOTALL,
)

# Match any <img> tag
_IMG_RE = re.compile(r'<img\s([^>]+)>')

# Extract src and alt from img attributes
_SRC_RE = re.compile(r'src="([^"]*)"')
_ALT_RE = re.compile(r'alt="([^"]*)"')

# Convention suffixes
_ALIGN_VALUES = {"left", "right", "center"}
_WIDTH_RE = re.compile(r'^\d+%$')

_SIZES_ATTR = '(max-width: 600px) 100vw, 600px'


def _parse_alt_conventions(alt: str) -> tuple[str, str | None, str | None]:
    """Parse alt text for convention suffixes.

    Returns (caption, alignment, width_pct).
    """
    if "|" not in alt:
        return alt, None, None

    parts = alt.split("|")
    caption = parts[0]
    alignment = None
    width_pct = None

    for part in parts[1:]:
        stripped = part.strip()
        if stripped in _ALIGN_VALUES:
            alignment = stripped
        elif _WIDTH_RE.match(stripped):
            width_pct = stripped

    return caption, alignment, width_pct


def _build_picture(src: str, alt: str, entry: dict, loading: str,
                   base_path: str = "") -> str:
    """Build a <picture> element from manifest entry."""
    variants = entry.get("variants", [])

    # Group variants by format
    by_format: dict[str, list] = {}
    for v in variants:
        by_format.setdefault(v["format"], []).append(v)

    sources = []
    # WebP first (preferred), then original format
    for fmt in sorted(by_format.keys(), key=lambda f: (0 if f == "webp" else 1)):
        fmt_variants = sorted(by_format[fmt], key=lambda v: v["width"])
        srcset_parts = [f'{base_path}/{v["path"]} {v["width"]}w' for v in fmt_variants]
        mime = FORMAT_TO_MIME.get(fmt, f"image/{fmt}")
        sources.append(
            f'<source type="{mime}" '
            f'srcset="{", ".join(srcset_parts)}" '
            f'sizes="{_SIZES_ATTR}">'
        )

    resolved_src = f"{base_path}/{src}"
    sources_html = "\n    ".join(sources)
    return (f'<picture>\n'
            f'    {sources_html}\n'
            f'    <img src="{escape(resolved_src)}" alt="{escape(alt)}" loading="{loading}">\n'
            f'  </picture>')


def _build_figure(inner: str, caption: str, alignment: str | None,
                  width_pct: str | None) -> str:
    """Wrap content in <figure> with optional alignment/width and caption."""
    attrs = []
    if alignment:
        attrs.append(f'class="align-{alignment}"')
    if width_pct:
        attrs.append(f'style="max-width:{width_pct}"')

    attr_str = " " + " ".join(attrs) if attrs else ""
    caption_html = f"\n  <figcaption>{escape(caption)}</figcaption>" if caption else ""

    return f'<figure{attr_str}>\n  {inner}{caption_html}\n</figure>'


def transform_images(html: str, manifest: dict, base_path: str = "") -> str:
    """Transform <img> elements in rendered HTML using the image manifest.

    base_path — URL prefix for deployed sites (e.g. "/grove"). Empty for root.
    All asset paths in src/srcset are prefixed so they resolve from any page URL.

    - Standalone images (<p> with only <img>) → <figure> with <picture>
    - Inline images → <picture> in place
    - Passthrough (SVG/GIF) → <figure> without <picture>
    - External URLs → unchanged
    - Not in manifest → unchanged
    """
    image_count = 0

    def _handle_img(img_tag: str, standalone: bool) -> str | None:
        nonlocal image_count

        src_match = _SRC_RE.search(img_tag)
        if not src_match:
            return None
        src = src_match.group(1)

        # External URL check first
        if src.startswith("http://") or src.startswith("https://") or src.startswith("//"):
            return None

        # Manifest lookup
        entry = manifest.get(src)
        if entry is None:
            return None

        alt_match = _ALT_RE.search(img_tag)
        alt = alt_match.group(1) if alt_match else ""
        caption, alignment, width_pct = _parse_alt_conventions(alt)

        loading = "eager" if image_count == 0 else "lazy"
        image_count += 1

        is_passthrough = entry.get("passthrough", False)
        has_variants = bool(entry.get("variants"))

        if is_passthrough or not has_variants:
            # SVG/GIF or small image: figure wrap with plain <img>, no <picture>
            resolved_src = f"{base_path}/{src}"
            img_html = f'<img src="{escape(resolved_src)}" alt="{escape(caption)}" loading="{loading}">'
            if standalone:
                return _build_figure(img_html, caption, alignment, width_pct)
            return None  # inline passthrough stays as-is

        # Build <picture> element
        picture_html = _build_picture(src, caption, entry, loading, base_path=base_path)

        if standalone:
            return _build_figure(picture_html, caption, alignment, width_pct)
        return picture_html

    # First pass: standalone images
    def _replace_standalone(match):
        img_tag = match.group(1)
        result = _handle_img(img_tag, standalone=True)
        if result is not None:
            return result
        return match.group(0)

    html = _STANDALONE_RE.sub(_replace_standalone, html)

    # Second pass: remaining inline <img> tags not already inside <picture>/<figure>
    def _replace_inline(match):
        # Skip if already inside a <picture> or <figure> element
        preceding = html[:match.start()]
        # Count open/close tags to determine nesting
        in_picture = preceding.count('<picture>') > preceding.count('</picture>')
        in_figure = preceding.count('<figure') > preceding.count('</figure>')
        if in_picture or in_figure:
            return match.group(0)
        result = _handle_img(match.group(0), standalone=False)
        if result is not None:
            return result
        return match.group(0)

    html = _IMG_RE.sub(_replace_inline, html)

    return html
