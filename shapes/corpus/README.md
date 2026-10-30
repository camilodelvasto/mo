# Authoring a corpus flow

A **flow** is the portable contract for one corpus: what enters, how it is
processed, what gets characterized, and when it retires. You write a
`flow.yaml`; the engine reacts to it. This is the guide to writing one.

## The schemas are the source of truth

This README teaches; it does not define. The contract is the JSON Schema under
`schemas/`, and `additionalProperties: false` holds at every level — a key not
in the schema is invalid, not ignored.

| Schema | Defines |
|--------|---------|
| `schemas/flow.v1.json` | `flow.yaml` — the contract you author |
| `schemas/corpus.v1.json` | `corpus.yaml` — the folder's id + flow pointer |
| `schemas/capabilities.v1.json` | the machine binding table |
| `schemas/meta.v1.json` | the sidecar the engine writes (read-only to you) |
| `schemas/assert.v1.json` | an inbox assert file |

When this guide and a schema disagree, the schema wins. Validate before you run:

```bash
.venv/bin/python -c "import json,yaml; from jsonschema import Draft7Validator; \
  Draft7Validator(json.load(open('shapes/corpus/schemas/flow.v1.json'))) \
  .validate(yaml.safe_load(open('PATH/TO/flow.yaml')))" && echo ok
```

Schema-valid is necessary, not sufficient: the engine enforces semantics JSON
Schema cannot (a `uses:` name must resolve in `capabilities.yaml`, `proposes:`
must name a real flow field, `confidence_min` only means anything with
`by: model`). The engine is where those rules live. Hold to it, not just to
the schema.

## A corpus is a folder

```
<a-corpus>/
  corpus.yaml         id + ./flow.yaml
  flow.yaml           the contract
  dropbox/            drop files here (one or more entrypoints)
  inbox/              assert files — the only human write path
  working/<stage>/    in-flight and parked pairs (engine-managed)
  failed/<stage>/     failed pairs; failed/inbox/ holds rejected asserts
  corpus/<doc_id>/    completed bundles
  retired/<doc_id>/   withdrawn, custody preserved
```

You create `corpus.yaml`, `flow.yaml`, `dropbox/`, `inbox/`. The engine creates
the rest. **Location is status** — there is no status field to keep in sync.
A complete starting point lives in `preview/corpus-example/`; copy it.

## flow.yaml, part by part

Required keys: `id`, `version`, `entrypoints`, `pipeline`.

```yaml
id: my-corpus
version: 1          # integer ≥ 1. Recorded in every sidecar. Bump on vocab
                    # edits; reprocessing under a new version is deliberate.
```

### entrypoints — the dropboxes

One or more. Each names a folder under the corpus and a glob; the engine tags
each arrival with the entrypoint's `fields:` (omit if you have nothing to tag).

```yaml
entrypoints:
  - id: dropbox
    area: dropbox
    pattern: "*"            # absent = every file
    # fields: { visibility: private }   # only if a stage gates on it
```

### pipeline — the ordered stages

Every stage has `id` and `uses`. Optional: `when`, `with`, `artifact`,
`fields`, `proposes`, `on_<failure>`.

```yaml
pipeline:
  - id: rename                   # optional. A filename is content: a flow
    uses: engine.rename          # that anonymizes refuses the dropped name.
    with: { to: "${doc_id}" }    # stem template; the extension is kept.
    artifact: original           # BEFORE stamp, so the name never enters the
                                 # log. Dropped names are then kept out of
                                 # duplicate-drop entries too.

  - id: stamp
    uses: engine.stamp           # creates the sidecar; first unless rename

  - id: normalize
    uses:                        # dispatch by mime — exactly one route runs
      dispatch_on: mime
      routes:
        audio/*:         local.whisper
        application/pdf: local.markitdown
        image/*:         local.tesseract
        text/markdown:   engine.passthrough
        # no matching route → stage fails (default handler)
    artifact: transcript         # names the artifact this stage produces

  - id: chunk
    uses: engine.chunk-ast
    with: { target_size: 512, max_size: 1024 }
    artifact: chunks
```

- `uses:` is a capability **name** (a builtin `engine.*`, or `local.*`/`api.*`
  bound on the machine) or a `{dispatch_on: mime, routes}` block.
- `when:` skips the stage when false, writing a one-line skip entry so the log
  stays gap-free. Branch by repeating a stage `id` with different `when:`.
- `with:` passes stage params (e.g. an LLM `prompt`, chunk sizes).
- `on_infected: quarantine`, `on_<x>: fail` — the failure handler. Default is
  `fail` (→ `failed/<stage>/`, repaired and retried with `--restart`).

### fields — what gets characterized

A stage declares `fields:` for the facts it contributes. Types: `string`,
`number`, `bool`, `enum` (requires `values:`), `set` (requires `of:`). Each
field names its writer:

```yaml
  - id: characterize
    uses: api.claude
    with:
      prompt: |
        Classify this document. Choose one of ${fields.doc_type.values}.
        Transcript:
        ${artifact.transcript}
    fields:
      doc_type:
        type: enum
        values: [report, interview, other]
        by: model
        confidence_min: 0.8       # at/above → the value lands; below → the
                                  # answer goes to proposed: and the field
                                  # PARKS, waiting for an assert
      audience:
        type: enum
        values: [internal, public]
        by: model
        confidence_min: 0.8
        optional: true            # below the gate → proposed, but does NOT
                                  # park; the document still completes
      doi:
        type: string
        by: operator              # never inferred; parks until a human asserts
```

- `by: model` — the stage's output is the value. With `confidence_min`, a
  below-gate answer is recorded under `proposed:` and the field **parks**.
- `optional: true` (model fields only) — changes the below-gate outcome: the
  value is still kept under `proposed:`, but the field does **not** park, so a
  low-confidence answer never blocks completion. For a field that applies to
  only some documents — take it when the model is confident, skip it otherwise.
- `by: operator` — a human judgment; the stage parks until an assert fills it.
- Parking is not failure: a parked pair sits in `working/<stage>/` with a
  `parked:` checklist and waits for a human. A failed pair waits for a repair.
- The LLM prompt resolves `${fields.X.values}` and `${artifact.Y}`; the engine
  appends the JSON output contract derived from `fields:`. Edit the enum, the
  prompt follows.

Top-level `fields:` (not under a stage) are assert-only vocabulary — columns
filled only by humans. A stage may `proposes: [tags]` to suggest values without
parking anything.

### rules — reactions that outlive the pipeline

Evaluated after every appended entry, for the document's whole life. The only
action is `retire`.

```yaml
rules:
  - when: fields.consent == declined
    do: retire           # bundle moves to retired/<doc_id>/, custody intact
```

### artifacts and areas — optional

`artifacts:` declares what to keep and where (`{ keep: true, to: bundle }`).
`areas:` overrides the default folder names. Omit both to take the defaults.

## Capabilities — the machine binding (capabilities.yaml)

The flow names capabilities; it binds none, so it stays portable. The binding
table is one file at the **018 root** (`capabilities.yaml`), gitignored,
shared by every corpus on the machine. The engine refuses to start until every
name a flow uses is bound here **and its binary is present** — a missing
capability is a startup error, never a degraded run.

```yaml
capabilities:
  local.whisper:                              # AUDIO → transcript
    run:   [whisper-transcribe, "${input}", "${output}"]
    reads: artifact                           # engine passes the input path
    emits: transcript                         # writes the transcript artifact

  local.markitdown:                           # PDF → markdown
    run:   [markitdown, "${input}"]
    reads: artifact
    emits: stdout                             # stdout becomes the transcript

  api.claude:                                 # LLM
    run:     [claude, -p]
    reads:   stdin                            # prompt piped in, NEVER argv
    emits:   stdout
    timeout: 600                              # optional; absent = unbounded

  local.clamscan:                             # exit-code tool
    run:   [clamscan, --no-summary, "${input}"]
    reads: artifact
    emits: exit_code
    map:   { "0": clean, "1": infected }      # exit_code only

  engine.stamp:       { builtin: true }       # builtins need no binding beyond
  engine.chunk-ast:   { builtin: true }       # declaring they are builtins
  engine.passthrough: { builtin: true }
  engine.wrap-md:     { builtin: true }
```

- `reads:` — `artifact` (path substituted as `${input}`), `prompt`
  (`${prompt}`, short only), or `stdin` (bytes piped in). Long prompts go on
  **stdin**, never argv.
- `emits:` — `transcript` (requires `${output}` in `run:`; the engine
  substitutes the path it expects and verifies the file exists), `stdout`, or
  `exit_code` (pair with `map:` to translate codes to the field's enum value).
- `local.*` runs on the machine, `api.*` sends content off it — the engine does
  not police this; locality is the operator's choice, expressed by where you
  route a stage. Keep private content on `local.*` because you wrote the flow
  that way.

## System dependencies

The engine itself needs only Python 3.12+ and the package installed
(`pip install -e ".[dev]"` from the 018 root). Everything else is whatever your
`capabilities.yaml` binds — install only the tools your flow's stages name:

```bash
# whichever of these your flow uses, on macOS:
pip install 'markitdown[pdf]'          # local.markitdown — PDF/office → markdown
                                       # (plain `markitdown` lacks PDF deps and
                                       #  fails the normalize stage on any .pdf)
brew install tesseract                 # local.tesseract  — image OCR
brew install tesseract-lang            #   + non-English language packs (e.g. spa)
brew install ffmpeg                    # whisper's audio decoding dependency
pip install openai-whisper             # local.whisper (or whisper.cpp / faster-whisper)
# Intel (x86_64) Macs: openai-whisper's Metal path produces gibberish — use
# whisper-ctranslate2 instead (CPU/CTranslate2, no Metal):
.venv/bin/pip install whisper-ctranslate2
# whisper-ctranslate2 writes <stem>.txt into --output_dir, not to a single
# file, so bind local.whisper to a wrapper (see bin/whisper-transcribe) whose
# run: ends in "${output}" — emits: transcript requires that path to appear.
brew install clamav                    # local.clamscan — virus scan
.venv/bin/pip install spacy && .venv/bin/python -m spacy download es_core_news_lg
#                                      # local.anonymize — bin/anonymize-names.py (spaCy PER)
# ollama pull qwen3.5:9b               # local.anonymize-llm — bin/anonymize-llm: the model
#                                      # identifies spans, the wrapper redacts them
# api.claude → the `claude` CLI; ollama models → `ollama pull <model>`
```

`engine.*` builtins (`stamp`, `passthrough`, `wrap-md`, `chunk-ast`, `strip-media`, `rename`) ship with
the shape and need nothing installed. A name with no binding, or a bound binary
not on the machine, stops the engine at startup and tells you which one.

## Run it

```bash
mo corpus watch  <path-to-corpus>          # start; resumes working/ on restart
mo corpus watch  <path-to-corpus> --restart  # also re-run failed/ pairs
mo corpus status <path>                    # counts per area
mo corpus tasks  <path>                    # the actionable queue + parked checklists
mo corpus ls     <path>                    # one folded row per completed document
mo corpus show   <path> <doc_id>           # one document in full, with provenance
mo corpus assert <path> <doc_id> <field>=<value> ...   # answer a parked field
#   set fields:  tags+=housing,tenancy   adds      tags-=draft   removes
```
