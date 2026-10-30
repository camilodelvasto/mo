# layer: renderer/tui — the corpus catalogue

Principles for modifying the TUI. Read before touching renderer code.

- The renderer is an httpx CLIENT and holds no logic. It GETs the service and
  renders; it never writes a sidecar and never reaches into the engine or the
  cache directly. Logic lives in the service.
- The transport is the only thing that changes: embed = ASGITransport in-process;
  attach/web = a base_url. Never branch a screen on which.
- Spine vs capability: the navigation spine (arrows/tab/enter/esc/q/?) is
  frame-owned and context-dispatched; it is NEVER in the keymap. The keymap binds
  only named capabilities (the registry) to single keys with labels. enter
  descends/commits in context — never bind it as a capability.
- The footer renders from the keymap labels. Do not hardcode footer text.
- The ~/◌ encodings are glyph + weight in render.py's cell text, legible with
  colour off. Colour reinforces; it never carries the encoding alone. Never
  "clean them up" into colour-only.
- The seam method is refetch(target), not refresh (Textual reserves refresh()).
- Visible, not silent: a stopped engine shows in the header; an empty lens shows
  an explicit empty state. Never a blank plane.
- SSE-over-ASGITransport does not work in-process: httpx's ASGITransport blocks
  in receive() waiting for response_complete, which a never-ending StreamingResponse
  never sets. SseTrigger is for the remote transport (real socket); embed uses
  TimerTrigger.
