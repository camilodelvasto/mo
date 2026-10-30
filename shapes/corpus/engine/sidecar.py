# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Read/write meta.yaml. Append-only. Atomic move (temp + rename).

The ONLY module that writes a sidecar. Every write stamps an integrity block
— sha256 of the document-minus-the-block plus the write moment — so a hand
edit that changes a value without recomputing the hash fails on the next
read, in this session or any later one. read_verified() checks the in-memory
digest first (fast path for the running session), then recomputes and
compares the embedded block (cross-session guarantee). verify_chain()
reconciles one pair's full custody chain at resume: doc_id against the
original's hash, artifact hashes on disk, and entry input/output links.
"""
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

from shapes.corpus.engine.errors import IntegrityError, SidecarError

# digest of the bytes the engine last wrote, per resolved path. In-memory:
# a fresh process trusts the tree it starts from; the chain stays verifiable
# from the recorded hashes.
_written: dict[str, str] = {}

_DUMP_OPTS = dict(sort_keys=False, allow_unicode=True)


def _serialize(doc: dict) -> str:
    return yaml.safe_dump(doc, **_DUMP_OPTS)


def read(meta_path: Path) -> dict:
    try:
        doc = yaml.safe_load(meta_path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise SidecarError(f"unreadable sidecar {meta_path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise SidecarError(f"sidecar {meta_path} is not a mapping")
    return doc


def read_verified(meta_path: Path) -> dict:
    """Read, raising IntegrityError if integrity cannot be confirmed.

    In-memory check first: if this process wrote the sidecar, compare the
    stored digest against the bytes on disk (fast path, catches foreign writes
    in the running session). Then embedded check: parse the doc, pop the
    integrity block, recompute, compare (cross-session guarantee).
    """
    expected = _written.get(str(meta_path.resolve()))
    if expected is not None:
        actual = hashlib.sha256(meta_path.read_bytes()).hexdigest()
        if actual != expected:
            raise IntegrityError(
                f"sidecar {meta_path} changed outside the engine; "
                "human input goes through inbox/, full stop"
            )
    doc = read(meta_path)
    _verify_embedded(meta_path, doc)
    return doc


def _verify_embedded(meta_path: Path, doc: dict) -> None:
    """Recompute the integrity block and raise IntegrityError on mismatch."""
    block = doc.get("integrity")
    if not block or not isinstance(block, dict):
        raise IntegrityError(
            f"sidecar {meta_path} has no integrity block; "
            "only sidecar.write may produce a valid sidecar"
        )
    recorded_hash = block.get("hash", "")
    at = block.get("at", "")
    # Reconstruct exactly what write() hashed.
    clean = {k: v for k, v in doc.items() if k != "integrity"}
    payload = _serialize(clean)
    digest = hashlib.sha256((payload + at).encode()).hexdigest()
    expected_hash = f"sha256:{digest}"
    if recorded_hash != expected_hash:
        raise IntegrityError(
            f"sidecar {meta_path} integrity check failed; "
            "a value was edited without recomputing the hash"
        )


def write(meta_path: Path, doc: dict) -> str:
    # Strip any pre-existing integrity block so the payload is deterministic.
    clean = {k: v for k, v in doc.items() if k != "integrity"}
    at = datetime.now(timezone.utc).isoformat()
    payload = _serialize(clean)
    digest = hashlib.sha256((payload + at).encode()).hexdigest()
    doc_with_integrity = dict(clean)
    doc_with_integrity["integrity"] = {"hash": f"sha256:{digest}", "at": at}
    text = _serialize(doc_with_integrity)
    # Update the caller's dict in-place so downstream code sees the block.
    doc["integrity"] = doc_with_integrity["integrity"]
    tmp = meta_path.parent / f".{meta_path.name}.tmp"
    tmp.write_bytes(text.encode())
    os.replace(tmp, meta_path)
    file_digest = hashlib.sha256(text.encode()).hexdigest()
    _written[str(meta_path.resolve())] = file_digest
    return file_digest


def append(meta_path: Path, entry: dict) -> dict:
    doc = read_verified(meta_path)
    doc["stages"].append(entry)
    write(meta_path, doc)
    return doc


def forget(meta_path: Path) -> None:
    """Drop the expected digest when a pair moves (the path changes)."""
    _written.pop(str(meta_path.resolve()), None)


def verify_chain(pair_dir: Path) -> None:
    """Reconcile one pair's custody chain. IntegrityError on the first break.

    Checks (in order):
    (a) doc_id matches the first 12 hex of the original artifact's hash
        (skipped if no 'original' artifact with a local path in the manifest);
    (b) each artifact with a local ./ path whose name appears as an
        output.artifact in any entry has a file on disk whose current hash
        equals the latest recorded output hash for that artifact;
    (c) every entry with input: {artifact: X, hash: H} has H equal to the
        latest prior output hash for X, where the 'received' entry's hash
        anchors the 'original' artifact.
    """
    from shapes.corpus.engine import identity  # avoid circular at module level

    meta_path = pair_dir / "meta.yaml"
    doc = read_verified(meta_path)
    doc_id = doc["doc_id"]
    artifacts = doc.get("artifacts", {})
    stages = doc.get("stages", [])

    # Build the latest output hash per artifact name from the log.
    # The 'received' entry's hash anchors the 'original' artifact.
    latest_output: dict[str, str] = {}
    for entry in stages:
        if entry.get("id") == "received" and "hash" in entry:
            latest_output["original"] = entry["hash"]
        out = entry.get("output")
        if isinstance(out, dict) and "artifact" in out and "hash" in out:
            latest_output[out["artifact"]] = out["hash"]

    # (a) doc_id vs original hash.
    if "original" in latest_output:
        expected_doc_id = latest_output["original"].removeprefix("sha256:")[:12]
        if doc_id != expected_doc_id:
            raise IntegrityError(
                f"pair {pair_dir}: doc_id {doc_id!r} does not match "
                f"the first 12 hex of the original hash "
                f"(expected {expected_doc_id!r})"
            )

    # (b) artifacts on disk vs latest recorded output hashes.
    output_artifact_names = {
        entry["output"]["artifact"]
        for entry in stages
        if isinstance(entry.get("output"), dict) and "artifact" in entry["output"]
    }
    for name, info in artifacts.items():
        path_str = info.get("path", "")
        if not path_str.startswith("./"):
            continue
        if name == "meta":
            continue
        artifact_path = pair_dir / path_str[2:]
        if name in output_artifact_names:
            # Produced-artifact check: on-disk hash must match the latest
            # recorded output hash for that artifact.
            if not artifact_path.exists():
                raise IntegrityError(
                    f"pair {pair_dir}: artifact {name!r} at {path_str!r} "
                    "is missing from disk"
                )
            recorded = latest_output.get(name)
            if recorded is None:
                continue
            actual = identity.sha256_file(artifact_path)
            if actual != recorded:
                raise IntegrityError(
                    f"pair {pair_dir}: artifact {name!r} on disk hash {actual!r} "
                    f"does not match recorded {recorded!r}"
                )
        elif name == "original" and "original" in latest_output:
            # Original-artifact check: not produced by any stage, but the
            # 'received' entry anchors its hash.  A swapped original must fail.
            if not artifact_path.exists():
                raise IntegrityError(
                    f"pair {pair_dir}: artifact 'original' at {path_str!r} "
                    "is missing from disk"
                )
            recorded = latest_output["original"]
            actual = identity.sha256_file(artifact_path)
            if actual != recorded:
                raise IntegrityError(
                    f"pair {pair_dir}: artifact 'original' on disk hash {actual!r} "
                    f"does not match received hash {recorded!r}"
                )

    # (c) entry input links: input.hash must equal the latest prior output hash.
    running_output: dict[str, str] = {}
    for entry in stages:
        if entry.get("id") == "received" and "hash" in entry:
            running_output["original"] = entry["hash"]
        inp = entry.get("input")
        if isinstance(inp, dict) and "artifact" in inp and "hash" in inp:
            artifact_name = inp["artifact"]
            expected = running_output.get(artifact_name)
            if expected is None:
                raise IntegrityError(
                    f"pair {pair_dir}: entry {entry.get('id')!r} references "
                    f"input artifact {artifact_name!r} with no prior output"
                )
            if inp["hash"] != expected:
                raise IntegrityError(
                    f"pair {pair_dir}: entry {entry.get('id')!r} input hash "
                    f"{inp['hash']!r} does not match prior output {expected!r}"
                )
        out = entry.get("output")
        if isinstance(out, dict) and "artifact" in out and "hash" in out:
            running_output[out["artifact"]] = out["hash"]