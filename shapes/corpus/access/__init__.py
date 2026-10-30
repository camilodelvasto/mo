# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""corpus access engine — declarative corpus querying (018z).

Module map (one responsibility each; see GUIDE.md before editing):

    index.py      open index/corpus.db inside the corpus. sqlite-vec + FTS5 +
                  projection cache. The ONLY module that opens the db.
    passport.py   write/probe/verify index/passport.yaml. Mismatch THROWS —
                  never re-embed silently across vector spaces.
    reconcile.py  the only WRITER of index/. Diff corpus/ + retired/ vs the db;
                  embed new chunks (ref-keyed), drop retired, refresh changed
                  projections. Idempotent. Runs before every ask.
    filter.py     compile a filter expression against the flow's declared
                  vocabulary; fold to a doc_id set over the projection cache.
                  Undeclared field / invalid enum THROWS. Imports the flow
                  reader; never redefines the vocabulary.
    retrieve.py   mode dispatch (vector|lexical|hybrid|none) + rrf, scoped to a
                  doc_id set. Uniform ranked result with per-chunk provenance.
    run_ask.py    the ask pipeline: reconcile -> resolve ask -> compose where ->
                  filter -> retrieve -> resolve prompt + prepend profile ->
                  spawn synthesize -> check citations -> return the record.
    askfile.py    load + validate ask.yaml referenced from corpus.yaml.

The fold and the flow-vocabulary reader are imported from shapes.corpus.engine,
never reimplemented.
"""
