# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Pure rendering: a /catalogue row payload -> table columns and cell strings.

The ~ proposal mark and the ◌ pending mark are REQUIRED ENCODINGS — glyph plus
weight, present in the cell text whether or not colour is on (a colourblind
operator, a low-colour terminal). The four status colours are Rich markup that
reinforces; they are never the only carrier. No terminal here — these are pure
string builders, tested by stripping the markup and asserting the glyph."""

# status (or status@stage) -> accent hex. Status is data; these four hues map to
# these four states and are reused for nothing else.
_STATUS_ACCENT = {
    "complete":  "#4cb782",   # green
    "parked":    "#e0a458",   # amber
    "failed":    "#d4655a",   # red
    "retired":   "#76777b",   # muted (a withdrawn doc is not a live state)
    "quarantined": "#d4655a",
}
_PENDING = "◌"
_PROPOSAL = "~"

MIN_COL = 6
# Fixed shares; doc_id/status fixed, the rest split with the long text largest.
_SHARE = {"doc_id": 14, "status": 14}
_DEFAULT_SHARE = 18
_TEXT_SHARE = 36   # the free-text trailing column


def column_widths(columns: list, available: int) -> dict:
    """Integer width per column summing to `available`, proportional to fixed
    shares, the trailing declared column (free text) largest. Never below
    MIN_COL. Remainder lands on the largest column so the row fills exactly."""
    shares = {}
    for i, c in enumerate(columns):
        if c in _SHARE:
            shares[c] = _SHARE[c]
        elif i == len(columns) - 1:
            shares[c] = _TEXT_SHARE
        else:
            shares[c] = _DEFAULT_SHARE
    total = sum(shares.values())
    widths = {c: max(MIN_COL, available * s // total) for c, s in shares.items()}
    drift = available - sum(widths.values())
    widest = max(widths, key=widths.get)
    widths[widest] += drift
    return widths


def table_columns(declared: list) -> list:
    """doc_id, derived status, then the flow's declared fields, de-duplicated and
    order-preserving — a field declared in more than one branch stage (e.g.
    `summary` across the datasheet branches) is ONE column, not two. Intrinsic
    stamp facts are never columns."""
    seen: list = []
    for f in declared:
        if f not in seen:
            seen.append(f)
    return ["doc_id", "status", *seen]


def _status_markup(status: str) -> str:
    base = status.split("@", 1)[0]
    accent = _STATUS_ACCENT.get(base, "#76777b")
    return f"[{accent}]{status}[/]"


def _set_str(value) -> str:
    return ", ".join(value) if isinstance(value, list) else str(value)


def render_row(row: dict, columns: list) -> list:
    """One row payload -> a cell string per column. cells[0] is the bare doc_id;
    cells[1] is the status with its accent; the rest are the declared fields with
    proposal/pending encodings."""
    cells_meta = row.get("cells", {})
    proposals = row.get("proposals", {})
    pending = set(row.get("pending", []))
    out = []
    for col in columns:
        if col == "doc_id":
            out.append(row["doc_id"])
        elif col == "status":
            out.append(_status_markup(row["status"]))
        elif col in cells_meta:
            text = _set_str(cells_meta[col]["value"])
            if col in pending:
                text = f"[#8fb4e3]{_PENDING}[/]{text}"   # blue ring reinforces
            out.append(text)
        elif col in proposals:
            prop = proposals[col]
            val = _set_str(prop.get("add", prop.get("value", "")))
            conf = f" ({prop['confidence']:.2f})" if "confidence" in prop else ""
            out.append(f"[dim italic]{_PROPOSAL}{val}{conf}[/]")
        else:
            out.append("—")
    return out
