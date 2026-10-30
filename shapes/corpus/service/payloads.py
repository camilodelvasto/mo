# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Pure builders: turn a sidecar doc into the JSON shapes the endpoints
return. No sidecar writes. The only I/O is reading a pair's artifact files
for custody (existence) and chunks. The fold and its provenance mode are
imported from the engine, never reimplemented."""
import json
from pathlib import Path

from shapes.corpus.engine.fold import fold_with_provenance


def _coarse_by(entry: dict) -> str:
    """The row's two-value provenance tag: operator if a human assert wrote
    it, model otherwise. Full provenance lives on /doc/{id}."""
    return "operator" if entry.get("by") == "operator" else "model"


def build_row(doc: dict, declared: set, pending: list) -> dict:
    """A catalogue row: declared-field cells with coarse `by`, unconfirmed
    proposals (with confidence), and pending markers. Absent blocks omitted,
    never null."""
    prov = fold_with_provenance(doc["stages"])
    cells = {name: {"value": info["value"], "by": _coarse_by(info["entry"])}
             for name, info in prov.items() if name in declared}
    row = {"doc_id": doc["doc_id"], "status": doc["status"], "cells": cells}
    if "source_name" in prov:
        row["source_name"] = prov["source_name"]["value"]

    proposals: dict = {}
    for entry in doc["stages"]:
        for name, value in (entry.get("proposed") or {}).items():
            if name in cells:
                continue          # a landed human value stops the re-proposal
            conf = (entry.get("meters") or {}).get("confidence")
            block = dict(value) if isinstance(value, dict) else {"value": value}
            if isinstance(conf, dict) and name in conf:
                block["confidence"] = conf[name]
            elif isinstance(conf, (int, float)):
                block["confidence"] = conf
            proposals[name] = block
    if proposals:
        row["proposals"] = proposals
    if pending:
        row["pending"] = list(pending)
    return row


def build_doc(doc: dict, declared: set) -> dict:
    """The /doc/{id} payload: declared fields with full provenance, intrinsic
    stamp facts in their own block, the flow pin, and the artifact manifest."""
    prov = fold_with_provenance(doc["stages"])
    fields: dict = {}
    intrinsic: dict = {}
    for name, info in prov.items():
        if name in declared:
            fields[name] = {"value": info["value"],
                            "provenance": _provenance(info["entry"], name)}
        else:
            intrinsic[name] = info["value"]
    out = {"doc_id": doc["doc_id"], "status": doc["status"],
           "flow": doc["flow"], "fields": fields}
    if intrinsic:
        out["intrinsic"] = intrinsic
    if doc.get("artifacts"):
        out["artifacts"] = doc["artifacts"]
    return out


def _provenance(entry: dict, field: str) -> dict:
    """The contributing entry, projected to what the Fields tab prints."""
    prov = {"stage": entry["id"], "by": _coarse_by(entry)}
    cap = (entry.get("capability") or {}).get("id")
    if cap:
        prov["capability"] = cap
    for key in ("model", "locality", "via", "at", "finished"):
        if key in entry:
            prov[key] = entry[key]
    conf = (entry.get("meters") or {}).get("confidence")
    if isinstance(conf, dict) and field in conf:
        prov["confidence"] = conf[field]
    elif isinstance(conf, (int, float)):
        prov["confidence"] = conf
    return prov


def build_custody(doc: dict, pair_dir: Path) -> dict:
    """One link per stage that produced an artifact: its input/output hashes,
    whether the input hash matches the prior output (verified), and whether the
    artifact bytes are still on disk. The verification is computed here so a
    renderer only colours it."""
    latest: dict = {}
    links: list = []
    for entry in doc["stages"]:
        if entry.get("id") == "received" and "hash" in entry:
            latest["original"] = entry["hash"]
        inp = entry.get("input")
        out = entry.get("output")
        if isinstance(out, dict) and "artifact" in out and "hash" in out:
            artifact = out["artifact"]
            verified = True
            if isinstance(inp, dict) and "artifact" in inp and "hash" in inp:
                verified = latest.get(inp["artifact"]) == inp["hash"]
            present = _artifact_present(doc, pair_dir, artifact)
            links.append({"stage": entry["id"], "artifact": artifact,
                          "input": (inp or {}).get("hash"),
                          "output": out["hash"],
                          "verified": verified, "artifact_present": present})
            latest[artifact] = out["hash"]
    return {"links": links}


def _artifact_present(doc: dict, pair_dir: Path, artifact: str) -> bool:
    info = (doc.get("artifacts") or {}).get(artifact)
    if not info or "path" not in info:
        return False
    path = info["path"]
    if not path.startswith("./"):
        return True            # dispatched elsewhere (store://…): not local
    return (pair_dir / path[2:]).is_file()


def build_chunks(pair_dir: Path) -> dict:
    """The Chunks tab: the records from chunks.jsonl, each with its size and a
    vector flag (always false until the index tail lands in step 14)."""
    path = pair_dir / "chunks.jsonl"
    chunks: list = []
    if path.is_file():
        for line in path.read_text().splitlines():
            r = json.loads(line)
            chunks.append({"ref": r["ref"], "ast_path": r["ast_path"],
                           "span": r["span"], "contiguous": r["contiguous"],
                           "size": len(r["text"]), "vector": False})
    return {"chunks": chunks}


def build_log(doc: dict) -> dict:
    """The Log tab: the raw entry sequence, the record of record."""
    return {"entries": doc["stages"]}
