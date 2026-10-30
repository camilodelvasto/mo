# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Pure builder: a /facets payload + a label function -> the rail tree shape.
Category labels (status, the enum field names) resolve through the label fn;
leaf labels are the raw values (corpus data, never relabelled). Each leaf
carries `select` = (facet_key, value), the exact selection the catalogue
filter consumes. No Textual here — the tree shape is unit-tested as data."""


def facet_nodes(payload: dict, label) -> list:
    nodes = []
    for facet in payload["facets"]:
        key = facet["key"]
        leaves = [{"label": v["value"], "count": v["count"],
                   "select": (key, v["value"])} for v in facet["values"]]
        nodes.append({"label": label(key), "leaves": leaves})
    return nodes
