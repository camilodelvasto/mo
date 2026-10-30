# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Pure renderers for the document screen's four tabs — Fields, Custody, Chunks,
Log — plus the transcript span highlight. No terminal: string/row builders the
DocumentScreen mounts. The service shapes each payload; these only render it (in
particular custody `verified` is service-computed — never recompute hashes here)."""


def _set_str(value) -> str:
    return ", ".join(value) if isinstance(value, list) else str(value)


def _fmt_when(iso) -> str:
    """ISO '2026-06-02T09:42:55Z' -> 'dd.mm.yyyy at hh:mm', '' if absent/unparseable."""
    if not iso:
        return ""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y at %H:%M")
    except ValueError:
        return ""


def doc_inspector(doc: dict) -> list:
    """The default inspector content — same format as the catalogue inspector:
    doc id, status, then field name + value pairs (indented value on next line)."""
    lines = [f"INSPECTOR · {doc['doc_id'][:6]}", "", doc["status"], ""]
    for name, info in doc.get("fields", {}).items():
        lines.append(f"{name}:")
        lines.append(f"  {_set_str(info['value'])}")
    return lines


def field_trail(doc: dict) -> list:
    """(name, value, acquired) per field — the Fields reading as an acquisition
    trail: 'added by <capability/operator> on dd.mm.yyyy at hh:mm · conf?'. The
    timestamp is the contributing entry's `at` (an assert) or `finished` (a model
    stage)."""
    out = []
    for name, info in doc["fields"].items():
        prov = info["provenance"]
        who = prov.get("capability") or prov.get("by", "?")
        trail = f"added by {who}"
        when = _fmt_when(prov.get("at") or prov.get("finished"))
        if when:
            trail += f" on {when}"
        if "confidence" in prov:
            trail += f" · {prov['confidence']:.2f}"
        out.append((name, _set_str(info["value"]), trail))
    return out


def field_provenance(doc: dict, field: str) -> list:
    """The inspector lines for one field: its contributing entry."""
    prov = doc["fields"][field]["provenance"]
    lines = [f"FIELD · {field}", "", f"value: {_set_str(doc['fields'][field]['value'])}",
             f"stage: {prov['stage']}", f"by: {prov['by']}"]
    for key in ("capability", "model", "locality", "via", "at"):
        if key in prov:
            lines.append(f"{key}: {prov[key]}")
    if "confidence" in prov:
        lines.append(f"confidence: {prov['confidence']}")
    return lines


def pipeline_rows(log: dict) -> list:
    """One row per stage — the pipeline reading. Status mark, stage id, the actor
    (model/capability/operator) that ran, timing, and what it contributed (a field,
    a meter, an output artifact, or a parked checklist). Renders the rich /log
    payload the old log_entries threw away."""
    return [_pipeline_row(s) for s in log["entries"]]


def _pipeline_row(s: dict) -> str:
    sid = s["id"]
    if "skipped" in s:
        return f"⊘ {sid:<12} skipped: {s['skipped']}"
    mark = "◌" if (s.get("parked") or s.get("proposed")) else "✓"
    meters = s.get("meters") or {}
    if s.get("by"):
        actor = f"{s['by']} · {s.get('via', '')}".strip(" ·")
    elif s.get("model"):
        actor = s["model"].get("name", "")
    elif s.get("capability"):
        actor = s["capability"].get("id", "")
    else:
        actor = s.get("entrypoint", "")
    conf = ""
    if isinstance(meters.get("confidence"), (int, float)):
        conf = f"  {meters['confidence']:.2f}"
    timing = ""
    if "duration_ms" in meters:
        ms = meters["duration_ms"]
        timing = f"{ms / 1000:.1f}s" if ms >= 1000 else f"{ms}ms"
    contrib = _stage_contribution(s, meters)
    return f"{mark} {sid:<12} {actor}{conf}  {timing:<7} {contrib}".rstrip()


def _stage_contribution(s: dict, meters: dict) -> str:
    fields = s.get("fields") or {}
    if fields:
        return ", ".join(f"{k}: {_set_str(v)}" for k, v in fields.items())
    if s.get("parked"):
        return f"parked: {', '.join(s['parked'])}"
    out = s.get("output") or {}
    if out.get("artifact"):
        return f"→ {out['artifact']}"
    for k in ("chunks", "entities_redacted"):
        if k in meters:
            return f"{meters[k]} {k.replace('_', ' ')}"
    return ""


def distinct_sections(chunks: list) -> list:
    """The document's sections — distinct chunk ast_paths in document order. Many
    chunks share a section, so this is a short outline, not one entry per chunk."""
    seen: list = []
    for c in chunks:
        ap = c["ast_path"]
        if ap not in seen:
            seen.append(ap)
    return seen


def doc_nav_nodes(field_names: list, sections: list, stage_ids: list) -> list:
    """The rail tree shape: the four readings, each with its leaves. Each node and
    leaf carries a (kind, key) `select` the screen dispatches on. document → the
    section outline; fields → field names; pipeline → stage ids; custody → none."""
    return [
        {"label": "document", "select": ("reading", "document"),
         "leaves": [{"label": ap, "select": ("section", ap)} for ap in sections]},
        {"label": "fields", "select": ("reading", "fields"),
         "leaves": [{"label": f, "select": ("field", f)} for f in field_names]},
        {"label": "pipeline", "select": ("reading", "pipeline"),
         "leaves": [{"label": sid, "select": ("stage", sid)} for sid in stage_ids]},
        {"label": "custody", "select": ("reading", "custody"), "leaves": []},
    ]


def custody_links(payload: dict) -> list:
    """One row per chain link. `verified` is the SERVICE's computed boolean —
    rendered, never recomputed here. Artifact-absence is an INDEPENDENT dimension:
    a deleted artifact with an intact chain is verified-and-absent, never broken.
    The chain remembers the hash; the disk does not keep the bytes."""
    out = []
    for link in payload["links"]:
        mark = "[#4cb782]✓ verified[/]" if link["verified"] else "[#d4655a]✗ broken[/]"
        presence = "" if link["artifact_present"] else "  · artifact gone"
        out.append(f"{link['stage']:<12} {link['artifact']:<10} "
                   f"{link['input']} → {link['output']}   {mark}{presence}")
    return out


def chunk_rows(chunks: list) -> list:
    """(ref, ast_path, size) per chunk — the chunk list."""
    return [(c["ref"], c["ast_path"], str(c["size"])) for c in chunks]


def ast_path_filter(chunks: list, query: str) -> list:
    """Client-side substring match over ast_path — a plain `contains`, NOT the
    catalogue's server-side where= grammar. Empty query = all chunks."""
    q = query.strip().lower()
    if not q:
        return chunks
    return [c for c in chunks if q in c["ast_path"].lower()]


def chunk_inspector(chunk: dict) -> list:
    """The chunk detail. `text == source ✓` is the contiguity guarantee (the
    chunk's text equals transcript[span] when contiguous). The vector state is a
    flat `index: not built` for this whole slice — never a per-chunk ✗ (which
    would later mean 'this one failed to embed')."""
    contig = "✓" if chunk["contiguous"] else "—"
    return [f"CHUNK · {chunk['ref']}", "",
            f"span: {chunk['span'][0]} — {chunk['span'][1]}",
            f"text == source: {contig}",
            f"contiguous: {chunk['contiguous']}",
            "ref: derived from ast_path + text",
            "index: not built"]


def highlight(transcript: str, span: list) -> str:
    """Wrap transcript[span] in the highlight style, the rest normal. `span` is
    a pair of Python str code-point offsets into the UTF-8-decoded transcript
    (the chunker computed them by slicing the decoded string, never by byte) —
    index the same way here. Pure: the scroll-to-span is the screen's job."""
    start, end = span
    before, lit, after = transcript[:start], transcript[start:end], transcript[end:]
    return f"{_markup_escape(before)}[#ffffff on #2d4a6b]{_markup_escape(lit)}[/]{_markup_escape(after)}"


def _markup_escape(s: str) -> str:
    return s.replace("[", "\\[")
