# layer: service — the corpus read surface

Principles for modifying the service. Read before touching service code.

- The service NEVER writes a meta.yaml. Its only writes are assert/order files
  into the corpus's inbox/. If you open a sidecar for write here, stop.
- The cache is the SOLE writer of derived/catalogue.sqlite, and it is
  rebuildable — never a source of truth. Provenance is never cached: /doc/{id}
  folds the one sidecar live.
- The service watches the tree with its OWN poller. The engine and the service
  are two readers of one filesystem doing different jobs; they never talk. Do
  not factor the poller into a shared running watcher with the engine.
- A torn/unreadable sidecar in the poller is SKIPPED and retried next tick,
  never thrown. This is the one place the no-fallbacks rule yields, and it
  lives on the service side only, because only the reader-that-does-not-write
  meets a file mid-write.
- The fold and its provenance mode are imported from engine/fold.py, never
  reimplemented.
- Bind localhost only. Exposure beyond the machine is 021's job.
