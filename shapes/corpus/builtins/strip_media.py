# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""engine.strip-media — remove embedded base64 data: media from the transcript.

A text corpus should not carry (or chunk, or embed, or ship to an LLM) base64
image blobs. This drops data: payloads in the three forms a markdown exporter
emits, leaving a short placeholder so structure and figure positions survive:

  1. reference defs   [image1]: <data:...>   -> line removed; the body's
                                                 [image1] label stays as the
                                                 placeholder.
  2. inline images    ![alt](data:...)       -> [alt]  (or [image] if no alt)
  3. HTML images      <img src="data:..." …> -> [alt]  (or [image])

Only data: URIs are stripped; real-URL image links are left untouched.
Idempotent: a transcript with no data: media is returned unchanged.
"""
import re
from pathlib import Path

# A markdown reference-style definition whose target is a data: URI, e.g.
#   [image1]: <data:image/png;base64,iVBOR...>
# The whole line goes; the body's [image1] reference remains as the placeholder.
_REF_DEF = re.compile(r'(?m)^[ \t]*\[[^\]\n]+\]:[ \t]*<?data:[^\n]*$\n?')
# An inline image with a data: URI:  ![alt](data:...)
_INLINE = re.compile(r'!\[([^\]]*)\]\(\s*data:[^)]*\)')
# An HTML <img> whose src is a data: URI (attrs in any order):
_IMG = re.compile(r'<img\b[^>]*\bsrc=["\']data:[^"\']*["\'][^>]*>', re.I)
_ALT = re.compile(r'\balt=["\']([^"\']*)["\']', re.I)


def run(pair_dir: Path, stage: dict, input_path: Path) -> dict:
    text = input_path.read_text(encoding="utf-8")
    before = len(text)
    counts = {"n": 0}

    text, n_ref = _REF_DEF.subn("", text)
    counts["n"] += n_ref

    def _inline(m):
        counts["n"] += 1
        alt = m.group(1).strip()
        return f"[{alt}]" if alt else "[image]"

    text = _INLINE.sub(_inline, text)

    def _img(m):
        counts["n"] += 1
        alt_m = _ALT.search(m.group(0))
        alt = alt_m.group(1).strip() if alt_m else ""
        return f"[{alt}]" if alt else "[image]"

    text = _IMG.sub(_img, text)

    if not text.endswith("\n"):
        text += "\n"
    out = pair_dir / "transcript.md"
    out.write_text(text, encoding="utf-8")
    return {"fields": {}, "output": out, "meters": {
        "media_removed": counts["n"],
        "bytes_removed": before - len(text),
        "text_remaining": len(text),
    }}
