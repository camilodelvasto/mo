#!/usr/bin/env python3
# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Strip person NAMES from Spanish text. Reads the transcript on stdin and
writes it back to stdout with every spaCy `PER` entity replaced by [NOMBRE].
Names only — locations, orgs, dates, etc. are left untouched. Local and
deterministic.

Large transcripts are processed in newline-aligned segments: spaCy's NER needs
~1GB of temporary memory per 100k characters and rejects input over its
max_length (1M chars), so a 1.5M-char document must not be fed in one piece.
Segments split on newlines, so a name is never cut across a boundary.

Requires: spacy + the Spanish model. Install once into the project venv:
    .venv/bin/pip install spacy
    .venv/bin/python -m spacy download es_core_news_lg
"""
import sys

_MODEL = "es_core_news_lg"
_PLACEHOLDER = "[NOMBRE]"
_MAX = 80_000          # per-segment char cap: well under nlp.max_length (1M)
                       # and bounds NER memory (~1GB per 100k chars).


def _segments(text: str):
    """Yield windows ≤ _MAX, cut at the last newline before the cap so a name
    is never split across a segment boundary."""
    i, n = 0, len(text)
    while i < n:
        end = min(i + _MAX, n)
        if end < n:
            nl = text.rfind("\n", i, end)
            if nl > i:
                end = nl + 1
        yield text[i:end]
        i = end


def _redact(nlp, segment: str) -> str:
    doc = nlp(segment)
    parts, last = [], 0
    for ent in doc.ents:               # ents are ordered and non-overlapping
        if ent.label_ == "PER":
            parts.append(segment[last:ent.start_char])
            # an entity the model stretched across a line break would swallow
            # the break and the next line's start (a speaker label); redact
            # each line's piece on its own and keep every newline
            lines = ent.text.split("\n")
            parts.append("\n".join(_PLACEHOLDER if piece.strip() else piece
                                   for piece in lines))
            last = ent.end_char
    parts.append(segment[last:])
    return "".join(parts)


def main() -> None:
    text = sys.stdin.read()
    try:
        import spacy
    except ModuleNotFoundError:
        sys.stderr.write("spacy not installed — run: .venv/bin/pip install spacy\n")
        raise SystemExit(1)
    try:
        # NER only — disabling the parser/lemmatizer cuts memory and time.
        nlp = spacy.load(_MODEL, disable=["morphologizer", "parser",
                                          "attribute_ruler", "lemmatizer"])
    except OSError:
        sys.stderr.write(
            f"{_MODEL} not installed — run: "
            f".venv/bin/python -m spacy download {_MODEL}\n")
        raise SystemExit(1)

    sys.stdout.write("".join(_redact(nlp, seg) for seg in _segments(text)))


if __name__ == "__main__":
    main()
