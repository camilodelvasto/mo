# layer: infrastructure — corpus engine

Principles for modifying this shape. Read before touching engine code.

- The engine is the ONLY writer of meta.yaml. The CLI and any future surface
  write assert files into the corpus's inbox/. If you find yourself opening a
  sidecar for write outside engine/, stop.
- A sidecar change the engine did not write is a violation: halt the pair
  loudly. Never process a foreign edit as input — that is the write path the
  inbox exists to close.
- Within a pair, one reaction at a time. The pool parallelizes ACROSS pairs;
  every reaction for one doc_id — stage, assert, rule — is serialized. If you
  are about to run two things against one sidecar concurrently, stop.
- No fallbacks. Every method and every spawned capability throws loud. A
  missing capability is a startup error, not a degraded mode. Do not add
  try/except that swallows and continues.
- Declarative, not imperative. The engine reacts to state (a sidecar, the
  flow, a dropped file) by computing the next step and taking it. It does
  not run a fixed script. New behavior is a new reaction to a state, not a new
  command.
- Filesystem is the state. Location is status. Never add a status field or a
  run-state file that could disagree with where a pair sits.
- The flow.yaml holds no machine specifics. Paths, ports, model tags live
  ONLY in the machine-root capabilities.yaml. If a value would differ between
  two machines, it does not belong in the flow.
- Atomic move for every sidecar append and every area move: write a temp file,
  rename into place. A reader must never see a torn file.
- The fold lives in one module (engine/fold.py) and is imported, never
  reimplemented. Scalar last-write-wins; set union-minus-removes; proposed:
  ignored.
- The integrity block is sidecar.write's alone. Every write re-stamps it; verified reads recompute it; resume reconciles the custody chain. If you assembled a sidecar without sidecar.write, you broke it on purpose.
