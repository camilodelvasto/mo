# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Hash a settled file; derive doc_id; find documents anywhere in the tree."""
import hashlib
from collections.abc import Iterator
from pathlib import Path

from shapes.corpus.engine import errors

# the corpus tree. Location is status; these are the locations.
STAGED_AREAS = ("working", "failed")          # area/<stage>/<doc_id>/
FLAT_AREAS = ("quarantine", "corpus", "retired")   # area/<doc_id>/
ALL_AREAS = STAGED_AREAS + FLAT_AREAS


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return f"sha256:{h.hexdigest()}"


def doc_id_for(path: Path) -> str:
    return sha256_file(path).removeprefix("sha256:")[:12]


def iter_pairs(corpus_dir: Path, areas=ALL_AREAS) -> Iterator[Path]:
    """Yield every meta.yaml under the given areas."""
    for area in areas:
        base = corpus_dir / area
        if not base.is_dir():
            continue
        depth = "*/*" if area in STAGED_AREAS else "*"
        for pair_dir in sorted(base.glob(depth)):
            meta = pair_dir / "meta.yaml"
            if meta.is_file():
                yield meta


def find_pair(corpus_dir: Path, doc_id: str) -> Path | None:
    """The drop-dedup lookup: an existing pair with this doc_id means a
    new drop of the same bytes is a duplicate, not a second document."""
    for meta in iter_pairs(corpus_dir):
        if meta.parent.name == doc_id:
            return meta
    return None


def find_orphans(corpus_dir: Path) -> list[dict]:
    """Audit the managed areas for absence. Two kinds of finding:
    {"kind": "missing-sidecar", "pair_dir": Path}   — a pair directory with no meta.yaml
    {"kind": "missing-file", "meta": Path, "path": str}  — a manifest ./ path with no file
    Orphans are reported, never moved (see the design doc: Absence is flagged)."""
    # sidecar imports identity lazily inside verify_chain, so this import is safe.
    from shapes.corpus.engine import sidecar

    findings: list[dict] = []
    for area in ALL_AREAS:
        base = corpus_dir / area
        if not base.is_dir():
            continue
        depth = "*/*" if area in STAGED_AREAS else "*"
        for pair_dir in sorted(base.glob(depth)):
            if not pair_dir.is_dir():
                continue
            if pair_dir.name.startswith("."):
                continue
            meta = pair_dir / "meta.yaml"
            if not meta.is_file():
                findings.append({"kind": "missing-sidecar", "pair_dir": pair_dir})
                continue
            # sidecar present: check every artifact path in the manifest
            try:
                doc = sidecar.read(meta)
            except errors.SidecarError:
                findings.append({"kind": "torn-sidecar", "meta": meta})
                continue       # the audit reports unreadable truth; it never dies on it
            for artifact_name, info in doc.get("artifacts", {}).items():
                if artifact_name == "meta":
                    continue
                path_str = info.get("path", "")
                if not path_str.startswith("./"):
                    continue
                artifact_path = pair_dir / path_str   # Path drops the leading ./
                if not artifact_path.is_file():
                    findings.append({"kind": "missing-file", "meta": meta, "path": path_str})
    return findings