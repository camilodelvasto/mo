"""Shared font utilities — weight/style mapping and @font-face CSS generation.

One table, one location. Every consumer (server, build, pptx) imports from here.
"""
from pathlib import Path


SUFFIX_TO_WEIGHT_STYLE = {
    "-VariableItalic": ("100 900", "italic"),
    "-Variable":       ("100 900", "normal"),
    "-Regular":        ("400",     "normal"),
    "-BoldItalic":     ("700",     "italic"),
    "-Bold":           ("700",     "normal"),
    "-Italic":         ("400",     "italic"),
}


def parse_font_filename(stem: str) -> tuple[str, str]:
    """Return (weight, style) based on the filename suffix after the family.

    Examples: 'Montserrat-Variable' -> ('100 900', 'normal')
              'Lato-Regular'        -> ('400',     'normal')
              'Lato-BoldItalic'     -> ('700',     'italic')

    Raises ValueError if the suffix is unknown.
    """
    for suffix, (weight, style) in SUFFIX_TO_WEIGHT_STYLE.items():
        if stem.endswith(suffix):
            return weight, style
    raise ValueError(
        f"Unrecognized font filename suffix: '{stem}.woff2'. "
        f"Expected one of: {sorted(SUFFIX_TO_WEIGHT_STYLE.keys())}"
    )


def build_fonts_css(fonts_dir: Path, url_prefix: str = "/fonts") -> str:
    """Walk fonts_dir one level deep, emit @font-face for every .woff2.

    Family name = subdirectory name. Weight/style derived from filename
    suffix via parse_font_filename.

    Args:
        fonts_dir: directory containing family subdirectories
        url_prefix: URL prefix for src paths (e.g., '/fonts' or '.' for relative)
    """
    if not fonts_dir.is_dir():
        raise FileNotFoundError(f"Fonts directory not found: {fonts_dir}")
    rules = []
    for family_dir in sorted(fonts_dir.iterdir()):
        if not family_dir.is_dir():
            continue
        family = family_dir.name
        for woff in sorted(family_dir.glob("*.woff2")):
            weight, style = parse_font_filename(woff.stem)
            src = f"{url_prefix}/{family}/{woff.name}"
            rules.append(
                f"@font-face {{ "
                f"font-family: {family}; "
                f"src: url('{src}') format('woff2'); "
                f"font-weight: {weight}; "
                f"font-style: {style}; "
                f"font-display: swap; "
                f"}}"
            )
    return "\n".join(rules) + "\n"
