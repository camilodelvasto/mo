# layer: infrastructure — corpus access engine

Principles for modifying this shape. Read before touching engine code.

- This engine NEVER writes a meta.yaml. The corpus engine owns the sidecar;
  this engine owns index/ and sessions/. If you find yourself opening a
  sidecar for write, stop — you are in the wrong engine.
- The bundles in corpus/ are canonical. index/corpus.db is a derived cache.
  Any disagreement is resolved by rebuilding the db from the bundles, never
  the reverse. Never treat a vector or a projection row as a source of truth.
- The flow is the schema. Filterable fields, types, and enum vocabularies are
  READ from flow.yaml. Never hardcode a field name, never redefine a
  vocabulary this shape does not own.
- Every ask reconciles before it answers. Do not add a path that queries a
  stale index to save a diff — the diff is the consent guarantee.
- The passport is load-bearing. Open verifies the embedder identity against
  it. Never re-embed silently on mismatch; throw and let reindex be the
  deliberate act.
- A declared `where:` scope narrows; a caller can narrow further but NEVER
  widen it. A scope the surface can override is not a scope.
- The citation check is a gate, not a warning. An answer with a fabricated
  marker is not returned with a caveat — the ask throws.
- No fallbacks. Missing capability, passport mismatch, bad filter, failed
  check — each throws loud and names itself. Do not add try/except that
  swallows and continues.
- Declarative, not imperative. Retrieval modes and control profiles are
  contract, not engine branches. New behavior is a new declaration in
  ask.yaml, not a new flag in the engine.
