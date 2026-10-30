# Sheets Importer — Design Spec

### v0.2 — may 2026

Bootstrap a new sheet from CSV/XLSX — deterministic analysis, single LLM editorial pass on metadata only, deterministic write of everything that touches row data.

The architectural backbone: the LLM never sees raw rows. It sees statistical analysis (types, cardinalities, enum value sets, samples, URL flags) and makes editorial decisions (field names, labels, action assignments, which canonical prompt templates apply). Row data flows through the deterministic path only — analyzer reads it, writer writes it, no LLM in between.

---

## Architecture

```
CSV/XLSX file
    │
    ▼
┌──────────────┐
│  Analyzer    │  deterministic — shapes/sheets/src/analyzer.py
│  reads ALL   │  no LLM, no network
│  rows/cols   │
└──────┬───────┘
       │  analysis dict (in-memory, not persisted)
       ▼
┌──────────────┐
│  Composer    │  one LLM call — shapes/sheets/src/composer.py
│  analysis +  │  sees metadata only, never raw rows
│  schema +    │
│  templates   │
└──────┬───────┘
       │  composer_output dict
       ▼
┌──────────────┐
│  Validator   │  deterministic post-LLM checks
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  Writer      │  deterministic — writes sheet.yaml, ops.jsonl,
│              │  exports.yaml, prompts/, runs rebuild
└──────┬───────┘
       │
       ▼
  sheet.yaml + ops.jsonl + exports.yaml + prompts/ + state.sqlite
```

**CLI:** `mo sheets import <file> --corpus <corpus> --name <name> [--sheet <xlsx_sheet>] [--backend <name>]`

**Command adapter:** `shapes/sheets/commands/import_cmd.py`

**Capability registration:** added to `shape.manifest.yaml` verb list.

---

## Phase 1: Analyzer

**File:** `shapes/sheets/src/analyzer.py`

Pure Python. No LLM, no network. Reads CSV (stdlib `csv`) or XLSX (`openpyxl` in read-only mode).

### Per-column analysis

For each column, reads every value and produces:

| Field | Description |
|-------|-------------|
| `header` | Raw header string from the file |
| `position` | Column index (0-based) |
| `type` | Narrowest type that fits all non-empty values |
| `date_format` | Detected format if `type` is date/datetime, else null |
| `nulls` | Count of empty/missing values |
| `unique_count` | Number of distinct values |
| `total_count` | Total non-null rows |
| `is_unique` | `unique_count == total_count` |
| `values` | Full distinct value set if enum candidate |
| `samples` | Up to 5 representative non-null values |
| `looks_like_url` | All non-null values match `https?://` prefix |
| `max_length` | Longest value length (string types only) |
| `malformed_count` | Values that did not parse against the detected type |

### Type inference

Attempts parsing in order: `boolean` → `integer` → `number` → `date` → `datetime` → `string`. Type is the narrowest that fits all non-empty values.

**Strictness: 100%, not 95%.** Any malformed value forces the type to `string`. This is a deliberate change from v0.1. The 95% rule allowed silent type promotion with malformed values stored as strings in ops.jsonl, which would either fail validation on rebuild or get coerced unpredictably. Sheets' posture elsewhere is "no silent data corruption," and the importer matches that. A column with one malformed integer is a string column with mostly-numeric values, and the user can clean it up post-import if they want.

`malformed_count` is still reported so the user sees what's going on. If a column has `type: string` but `malformed_count: 1` and the rest look numeric, the analysis output makes that visible to the composer, which can label the field appropriately ("Account Balance" rather than "Notes").

### Date format detection

Per column. Tries ISO (`YYYY-MM-DD`), US (`MM/DD/YYYY`), EU (`DD.MM.YYYY`), and the datetime variants. Picks the format that parses 100% of non-null values. If no single format parses everything, the column falls back to `string`. The chosen format is recorded as `date_format` and used by the writer when coercing values into ops.jsonl.

### Detection rules

- **Enum:** string column with ≤ 30 distinct values and `unique_count / total_count < 0.5` → enum candidate, full value list included in analysis as `values`.
- **Text vs string:** `max_length > 200` → `text`.
- **Primary key candidate:** first column where `is_unique == true`. If none found, primary key will be synthesized (`id: primary`).
- **URL detection:** all non-null values match `https?://` regex → `looks_like_url: true`.

### Output

Python dict, in-memory only:

```python
{
    "file": "path/to/source.csv",
    "row_count": 1532,
    "columns": [
        {
            "header": "Acct Num",
            "position": 0,
            "type": "string",
            "date_format": null,
            "nulls": 0,
            "unique_count": 1532,
            "total_count": 1532,
            "is_unique": true,
            "values": null,
            "samples": ["A-1001", "A-1002", "B-3301", "C-0012", "D-9981"],
            "looks_like_url": false,
            "max_length": 8,
            "malformed_count": 0
        },
        {
            "header": "Status",
            "position": 1,
            "type": "string",
            "date_format": null,
            "nulls": 12,
            "unique_count": 5,
            "total_count": 1520,
            "is_unique": false,
            "values": ["active", "inactive", "pending", "closed", "suspended"],
            "samples": ["active", "pending", "inactive", "active", "closed"],
            "looks_like_url": false,
            "max_length": 9,
            "malformed_count": 0
        }
    ]
}
```

---

## Phase 2: Composer

**File:** `shapes/sheets/src/composer.py`

One LLM call. Editorial decisions on metadata. Never sees raw rows.

### Backend selection

The composer is a one-shot bootstrap step that runs once per import and produces artifacts (prompts, field labels) that the sheet will use for its lifetime. Quality matters more than cost. The default backend is **not** the corpus's configured inference backend (which is tuned for ongoing NEW/UPDATE ops, often a fast local model).

Backend resolution order:

1. `--backend <name>` CLI flag, if provided
2. `moui.json` corpus-level `import.backend` key, if declared
3. `shape.manifest.yaml` sheets-level `import.default_backend` key
4. Hard default: the strongest backend available (typically a hosted frontier model)

The chosen backend is logged at import start so the user knows what made their sheet.

### Canonical prompt templates ship with the shape

Prompts are **not** authored by the LLM. They are picked from a templates directory in the sheets shape:

```
shapes/sheets/templates/prompts/
  extract.md         # NEW pipeline input — extract structured data from free text
  update.md          # UPDATE pipeline input — update existing row from new info
  fetch.md           # FETCH pipeline input — extract from fetched URL content
  enum_pick.md       # specialized prompt for enum-heavy sheets (not used by default)
  ...
```

Each template uses the same placeholder vocabulary the rest of sheets uses: `{{schema}}`, `{{row}}`, `{{body}}`, `{{now}}`. These templates are battle-tested and version-controlled with the shape.

The composer's job is to **pick** which templates apply, not to write prompt text. For each pipeline input it declares, it references a template by name. The writer copies the referenced templates from the shape's templates directory into the new sheet's `prompts/` directory. The user can then edit the copies freely without affecting the shape's canonical versions.

This eliminates the variability problem (every imported sheet starts with the same proven prompts), removes a class of silent quality degradation (LLM writing bad prompts that then run forever), and makes prompt iteration centralized (improve `extract.md` in the shape, future imports benefit).

### Pipeline input scaffolding

The composer always emits the same starter pipeline inputs unless the analysis indicates otherwise:

- **NEW** — `prompts/extract.md`, key `n`, op `insert`
- **UPDATE** — `prompts/update.md`, key `u`, op `update`, requires `row_id`
- **SET** — bypass_inference, key `e`, op `update`, requires `row_id` and `cell`

This is **opinionated default scaffolding**, not per-sheet intelligence. The composer is not making clever decisions about whether this imported sheet "needs" a NEW flow — it always declares one, and the user removes it from `sheet.yaml` if they don't want it. The spec is explicit about this so the design isn't read as if the LLM is doing more reasoning than it is.

**FETCH** is the exception worth a composer judgment call: it's emitted only if at least one column has `looks_like_url: true` and the field is labeled as a primary lookup target. Otherwise FETCH stays out of the starter scaffolding.

### LLM input

A single prompt containing:

1. The full analysis dict (all columns: types, cardinalities, enum values, samples, URL flags, malformed counts)
2. The sheet.v1.json schema (so the LLM knows what's valid)
3. Field option reference: `action`, `key`, `width`, `align`, `log`, `description`
4. Pipeline input type reference: NEW, FETCH, UPDATE, LOG, SET — what each does
5. The list of available prompt templates in `shapes/sheets/templates/prompts/` with one-line descriptions
6. The sheet name and corpus name

The LLM does not see row data. The largest payload it sees is the enum value sets (capped at 30 values per column) and up to 5 samples per column.

### LLM output

```json
{
    "title": "Account Directory",
    "description": "Customer accounts with status and contact info.",
    "header_map": {
        "Acct Num": "account_number",
        "Status": "status",
        "Website URL": "website",
        "Notes": "notes"
    },
    "fields": {
        "id": "primary",
        "account_number": {
            "type": "string",
            "label": "Account Number",
            "width": 12
        },
        "status": {
            "type": "enum",
            "values": ["active", "inactive", "pending", "closed", "suspended"],
            "label": "Status"
        },
        "website": {
            "type": "string",
            "label": "Website",
            "action": "open"
        },
        "notes": {
            "type": "text",
            "label": "Notes"
        },
        "created_at": "datetime",
        "updated_at": "datetime"
    },
    "pipeline": {
        "inputs": {
            "NEW": {
                "prompt_template": "extract",
                "op": "insert",
                "key": "n",
                "description": "Create from text"
            },
            "UPDATE": {
                "prompt_template": "update",
                "op": "update",
                "key": "u",
                "description": "Smart update",
                "context": { "row_id": "required" }
            },
            "SET": {
                "bypass_inference": true,
                "op": "update",
                "key": "e",
                "description": "Edit cell",
                "context": { "row_id": "required", "cell": "required" }
            }
        }
    },
    "keys": {
        "view": "v",
        "search": "/",
        "toggle_hidden": "H",
        "open": "o"
    },
    "view": {
        "notes_field": "notes"
    }
}
```

Pipeline inputs reference templates by name (`prompt_template: "extract"`), not by content. The writer resolves the name to a path in the generated sheet (`prompts/extract.md`) and copies the file.

---

## Phase 3: Validator

**File:** `shapes/sheets/src/composer.py` (same file, separate function)

Runs against the LLM output before anything touches disk. Every check is a hard fail — no partial imports.

1. **Schema validation.** LLM response validates against sheet.v1.json. JSON schema errors include the path to the offending field.
2. **header_map keys exist in source.** Every key in `header_map` is a header in the source file's first row.
3. **header_map covers all columns.** Every header in the source file appears as a key in `header_map`. No silent column drops. (If the LLM intentionally wants to drop a column, it declares the mapping value as `null`; the writer skips null-mapped columns and the validator allows them.)
4. **header_map values are unique.** No two source columns map to the same field name. Catches normalization collisions like `First Name` and `first name` both becoming `first_name`.
5. **Primary key exists.** Either a `primary` field is declared in `fields` or `id: primary` is present.
6. **Key collision check.** All keyboard bindings across `pipeline.inputs[].key`, `keys.*`, and `fields[].key` are distinct. Single-character collisions are a hard fail — schema-level enum checks don't catch this because it's cross-field. The error message lists the colliding bindings with their sources so the user can fix `sheet.yaml` post-import.
7. **Enum value integrity.** For every field declared as `type: enum`, the `values` list matches the analyzer's detected enum values for the mapped source column exactly. The LLM didn't invent values that aren't in the data, and didn't drop values that are.
8. **Prompt template references resolve.** Every `pipeline.inputs[].prompt_template` name refers to a file that exists in `shapes/sheets/templates/prompts/`.
9. **Field type compatibility.** For each mapped column, the field type the LLM chose is compatible with the analyzer's detected type. The LLM can narrow (analyzer says `string`, LLM says `enum` with values from the detected set — fine). It can't broaden a `string` column to `number`, or relabel a `datetime` column as `boolean`. A compatibility matrix lives in the validator.

If any check fails, the validator throws with a structured error pointing at the offending field. No retry on failure — the user re-runs the import after addressing the cause, which usually means the source file has an issue (mixed types, missing headers) the analyzer surfaced and the LLM tried to paper over.

---

## Phase 4: Writer

**File:** `shapes/sheets/src/writer.py`

All disk writes happen here. Deterministic. No LLM.

1. **Create target directory** `content/<corpus>/<name>/`. Throws if it already exists (no `--force` in v1; see "not covered").
2. **Write `sheet.yaml`** — bite metadata (`instance: sheets`, `version: 0.1.0`, `schema: sheet.v1.json`) plus title, description, fields, pipeline, keys, view from the composer output.
3. **Write `exports.yaml`** — defaults: `formats: [csv, xlsx]`, all non-system fields included, no filters. The exports.yaml shape is verified against the current exports schema; if it has fields the importer doesn't generate, those are omitted with a comment in the file pointing to documentation.
4. **Copy prompt templates** from `shapes/sheets/templates/prompts/<name>.md` to the sheet's `prompts/<name>.md` for every template referenced in `pipeline.inputs[].prompt_template`. Templates that aren't referenced aren't copied.
5. **Generate `ops.jsonl`** — one insert op per source row. Field names mapped via `header_map`. Values coerced per the analyzer's detected type (using `date_format` for date/datetime columns). Null-mapped columns are skipped. Coercion failures during writing (which shouldn't happen given the 100% strictness rule, but defense in depth) fall back to the raw string and are counted in an import report.
6. **Row IDs** — ULIDs, one per row, generated in source order. ULIDs sort naturally and don't require the 1-second stagger hack. Matches the row ID scheme used elsewhere in the sheets shape.
7. **created_at / updated_at** — if these fields are declared, all rows get the same value: the import timestamp. Not the row ID's embedded timestamp. The semantic is "all rows were created at import time," because that's what's true. Per-row creation times would be a lie about the source data's history.
8. **Empty ingest folders** — `ingest/inbox/`, `ingest/staging/`, `ingest/failed/` created empty.
9. **Run rebuild** — invoke the existing rebuild pipeline to generate `state.sqlite` from `ops.jsonl`. If rebuild fails, the import is left in a broken state on disk and the writer surfaces the rebuild error. The user can inspect the partial output, fix the underlying issue, delete the directory, and re-import.

### Import report

After successful import, the CLI prints a summary:

```
Imported 1532 rows from source.csv into content/work/accounts/
  Columns: 4 → fields: 4 + id + created_at + updated_at
  Enums detected: 1 (status: 5 values)
  Pipeline inputs: NEW, UPDATE, SET
  Prompts copied: extract.md, update.md
  Backend used for composition: claude-3-7-sonnet
  Rebuild: ok (state.sqlite written)

Open with: mo sheets serve content/work/accounts/
```

---

## File reading

- **CSV:** Python stdlib `csv.DictReader`. Encoding: UTF-8 with BOM detection. Other encodings (Latin-1, Windows-1252) detected via `chardet` if available, else error with a clear message asking the user to convert the file.
- **XLSX:** `openpyxl` in read-only mode. First sheet only by default, or `--sheet <name>` to pick one. First row is headers. Cells with formulas are read as their cached value, not the formula text — `openpyxl` does this by default in read-only mode.

---

## Output structure

```
content/<corpus>/<name>/
├── sheet.yaml
├── exports.yaml
├── ops.jsonl
├── state.sqlite          (generated by rebuild)
├── prompts/
│   ├── extract.md        (copied from shape template)
│   └── update.md         (copied from shape template)
└── ingest/
    ├── inbox/
    ├── staging/
    └── failed/
```

---

## CLI interface

```
mo sheets import <file> --corpus <corpus> --name <name> [--sheet <xlsx_sheet>] [--backend <name>]
```

- `<file>` — path to CSV or XLSX
- `--corpus` — target corpus directory name
- `--name` — sheet instance name (directory name under corpus)
- `--sheet` — XLSX sheet/tab name (defaults to first sheet)
- `--backend` — override backend selection for the composer LLM call

Throws if `content/<corpus>/<name>/` already exists.

---

## Dependencies

- `openpyxl` — already a dependency (used by XLSX export)
- `csv` — stdlib
- `chardet` — optional, for non-UTF-8 CSV encoding detection
- Inference backend — reuses existing `shapes/sheets/src/inference.py` and configured backends, with the import-specific resolution order described above

---

## What this does NOT cover (v1)

- **Appending to existing sheets.** Re-running on a fresh CSV against an existing sheet directory throws. v1.1 may add `--update` for ops.jsonl-only refresh keeping the existing sheet.yaml.
- **Interactive column-by-column refinement.** The composer makes its decisions in one shot. v1.1 may add a confirmation step where the user reviews and edits the composer output before writing.
- **Multiple XLSX sheets per import.** Use `--sheet` to pick one, run multiple times.
- **`--force` to overwrite.** Always throws on existing directory. Delete by hand to re-import.
- **Streaming for very large files.** The analyzer reads the whole file into memory. v1 ceiling is around 100k rows / 50MB.
