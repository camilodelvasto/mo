# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""mo corpus verify <path> — probe the corpus's passport against THIS machine's
live capabilities binding, without touching the index. Exits 0 if the box that
runs this can bind the corpus; raises PassportError (non-zero) naming the
divergence otherwise. Used by the sync rail's pre-flip verify, in the serve's
own container context."""
from pathlib import Path

from shapes.corpus.access import passport
from shapes.corpus.access.askfile import declared_embedder
from shapes.corpus.commands._read import resolve_corpus


def run(corpus_root: Path, instance: str, args: list) -> None:
    corpus = resolve_corpus(args)
    lexical = declared_embedder(corpus) is None
    identity = passport.verify(corpus, corpus_root, lexical=lexical)
    if lexical:
        print("passport verified: lexical")
    else:
        print(f"passport verified: {identity['model']} dim {identity['dimension']}")
