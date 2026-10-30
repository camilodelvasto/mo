# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""engine.* capabilities. The registry maps pipeline names to callables;
every callable has the same contract (see each module)."""
from shapes.corpus.builtins import chunk_ast, passthrough, rename, stamp, strip_media, wrap_md

REGISTRY = {
    "engine.stamp": stamp.run,
    "engine.passthrough": passthrough.run,
    "engine.wrap-md": wrap_md.run,
    "engine.chunk-ast": chunk_ast.run,
    "engine.strip-media": strip_media.run,
    "engine.rename": rename.run,
}
