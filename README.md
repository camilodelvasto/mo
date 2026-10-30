# moui

A personal computing platform where your data, your interfaces, and your infrastructure are separate things. Replace any layer — the others survive.

Your content lives as files on disk. Shapes turn those files into presentations, websites, documents, and structured data. Themes control how things look. The CLI validates, serves, builds, deploys, and processes. None of these layers depend on each other — swap one, the rest hold.

## What this is

This is a working prototype. It merges four shapes into a single unified workspace:

| Shape | What it does |
|-------|-------------|
| **deck** | Presentations — composable layouts, visual effects, encryption, PDF/PPTX export |
| **leaf** | Blog posts — Markdown with frontmatter, theme support |
| **grove** | Websites — static sites from collections of posts, full-text search, RSS |
| **sheets** | Structured data — ingestion pipeline, inference backends, web and terminal renderers, CSV/XLSX export |

One CLI (`mo`), one corpus manifest (`moui.json`), one schema system, four shapes.

## Install

Requires Python 3.12+.

```bash
# From the repo
pip install -e ".[dev]"

# Or with pipx (editable, changes reflect immediately)
pipx install -e path/to/018-workspace
```

This gives you the `mo` command with core dependencies. Each shape declares its own optional dependencies (PDF export, encryption, XLSX, etc.) in its manifest. Install them per shape:

```bash
# Core deps only
mo deck install

# Core + all optional capabilities (encryption, PDF export, PPTX)
mo deck install --all

# Same for other shapes
mo grove install --all
mo sheets install --all
```

## Quick start

```bash
# Validate corpus structure, schemas, and shapes
mo check

# Serve a presentation
mo deck serve content/decks/my-deck.yaml

# Serve a website
mo grove serve content/website/en/

# Serve structured data (web renderer)
mo sheets serve content/my-sheet

# Serve structured data (terminal)
mo sheets tui content/my-sheet

# Scaffold a new sheet
mo sheets new content/new-sheet

# Import from CSV/XLSX (untested — see note below)
mo sheets import data.csv --corpus personal --name my-sheet

# Build static output
mo grove build content/website/en/

# Export to PDF
mo deck export content/decks/my-deck.yaml --format pdf

# Export sheet data to CSV
mo sheets export my-sheet local

# Deploy
mo deploy content/website/en codeberg/website
```

## Data model

Every file is a **bite** — a piece of structured data with embedded metadata. The metadata declares what shape renders it, what schema validates it, and what theme styles it.

Shapes don't own data. They own rendering. You can delete a shape and your content survives. You can swap a shape for a different one and the data doesn't move.

## Shapes

Each shape is a self-contained directory with a declared contract:

```
shapes/
├── deck/          # Presentations
│   ├── shape.manifest.yaml
│   ├── renderer/
│   ├── exporters/
│   ├── themes/
│   └── schemas/
├── leaf/          # Posts
├── grove/         # Sites
├── sheets/        # Structured data
│   ├── shape.manifest.yaml
│   ├── commands/      # CLI adapters (serve, tui, ingest, export, ...)
│   ├── src/           # Processing pipeline, API, backends
│   ├── renderer/      # Web (Tabulator), TUI (Textual), CSV, XLSX
│   ├── schemas/
│   └── templates/
└── shared/        # Cross-shape utilities
```

The shape manifest declares capabilities, schemas, permissions, and dependencies. The CLI reads the manifest and routes commands accordingly. Shapes that declare a capability for a command verb get their own adapter called; shapes that don't fall through to generic handlers.

## Themes

Themes separate structure from appearance. Each theme is a `tokens.yaml` (design tokens) and a `style.css` (visual rules). Override individual tokens in your content file without touching the theme.

Resolution chain: content override > corpus theme > shape default.

## Schema system

Base types live in `schema/` (bite, manifest, shape, publish). Each shape defines its own content schemas (deck defines slide and deck, sheets defines sheet and ops). Schemas are validated at serve time and during `mo check`.

The manifest schema (`manifest.v1.json`) validates `moui.json`. The shape schema (`shape.v1.json`) validates every `shape.manifest.yaml`. Shapes can declare arbitrary capability verbs — the schema accepts them as long as they provide an adapter.

## Import (untested)

Sheets can bootstrap a new sheet from a CSV or XLSX file. The importer analyzes every column deterministically (types, enums, URLs, dates), sends the statistical analysis to an LLM for editorial decisions (field names, labels, actions, pipeline config), then writes the full sheet directory (sheet.yaml, ops.jsonl, exports.yaml, prompts, state.sqlite).

```bash
mo sheets import data.csv --corpus personal --name my-sheet
mo sheets import data.xlsx --corpus work --name accounts --sheet "Sheet1" --backend claude
```

The LLM never sees raw row data — only column statistics. 60 unit and integration tests pass, but the end-to-end flow with a real LLM backend has not been manually verified yet. Spec: `docs/sheets-importer-spec-v0.2.md`.

## Inference

Sheets uses a pluggable inference pipeline for processing ingested content. Backends are swappable:

- **ollama** — local models via Ollama
- **anthropic** — Claude API
- **json_extract** — pattern-based extraction, no model needed

Configure the default in `moui.json`:

```json
{
  "inference": {
    "default": { "backend": "ollama", "model": "qwen3:8b" }
  }
}
```

## Project structure

```
moui.json              corpus manifest — declares installed shapes
pyproject.toml         Python package with merged dependencies
cli/                   the mo command — dispatcher, loader, checker, resolver
schema/                base type schemas (bite, manifest, shape, publish)
shapes/                installed shapes (deck, leaf, grove, sheets, shared)
components/            reusable interactive components
content/               your data (gitignored)
infrastructure/        deploy targets and remotes (gitignored)
secrets/               encrypted credentials (gitignored)
tests/                 pytest suite
```

## Architecture

Three principles hold the architecture together:

**Contracts, not logic.** The system is held together by contracts between parts, not by business rules or coupled logic. Each boundary is a defined interface. Swap any part, the system holds.

**Declarative over imperative.** A manifest declares what exists. A resolver matches input to entries. A handler does the work. The router is just the pipe.

**Everything is plug and play.** Every piece that does something is replaceable. A fuzzy matcher, a resolver, a handler, an inference backend — each has a contract. The contract stays. The implementation swaps.

## Principles

This prototype is an expression of a broader set of ideas about what personal computing should be:

- Your data should be yours to move, verify, and protect
- Privacy by architecture, not by policy
- Data, interface, and infrastructure should be separable
- Local first, network when necessary
- Intelligence in service of agency
- Joy without extraction
- Design for the future

The full articulation lives in the moui manifesto and philosophy corpus, published separately.

## License

Copyright (C) 2026 Sensata Research GmbH

Licensed under the GNU Affero General Public License v3.0. See [LICENSE](LICENSE) and [COPYRIGHT](COPYRIGHT).
