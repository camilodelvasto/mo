# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""engine.rename — give the original artifact a name the flow chooses.

A filename is content. "Entrevista Juan Carlos.docx" names a person as surely
as the transcript does, and the engine writes that name into the bundle (the
file on disk), into stamp's `source_name`, and into every catalogue row. A flow
that anonymizes must be able to refuse the dropped name. This stage renames the
original on disk and reports the new path as the `original` artifact; the log
records bytes (the hash is unchanged), never the name that was dropped.

Place it BEFORE stamp. `received` records no name; stamp records the name it
sees. Placed after stamp, the dropped name is already in the append-only log.

    - id: rename
      uses: engine.rename
      with: { to: "${doc_id}" }      # the stem; the extension is preserved
      artifact: original             # (stamp reads mime from it)

`to:` is a stem template. `${doc_id}` is the only placeholder. The extension is
always kept. `${doc_id}` makes a name unique across bundles; a fixed stem cannot
collide either, since every bundle is its own folder — collisions can only come
from exporting bundles into one flat folder, and `${doc_id}` is the answer there.
Idempotent: a file already so named is reported as-is.
"""
import re
from pathlib import Path

from shapes.corpus.engine.errors import ContractError, StageFailure

_PLACEHOLDER = re.compile(r"\$\{([^}]*)\}")
_KNOWN = {"doc_id"}


def names_originals(flow: dict) -> bool:
    """True when the flow renames originals — the engine then keeps dropped
    names out of the log everywhere, including duplicate-drop entries."""
    return any(s.get("uses") == "engine.rename" for s in flow["pipeline"])


def _stem(stage: dict, pair_dir: Path) -> str:
    sid = stage["id"]
    template = (stage.get("with") or {}).get("to")
    if not isinstance(template, str):
        raise ContractError(f"{sid}: engine.rename requires with: {{ to: <stem template> }}")
    if stage.get("artifact") != "original":
        raise ContractError(f"{sid}: engine.rename must declare artifact: original")
    unknown = [m for m in _PLACEHOLDER.findall(template) if m not in _KNOWN]
    if unknown:
        raise ContractError(
            f"{sid}: unknown placeholder ${{{unknown[0]}}} in to: — "
            f"only ${{doc_id}} is defined")
    stem = _PLACEHOLDER.sub(lambda m: pair_dir.name, template)
    if not stem or "/" in stem or "\\" in stem or stem in (".", ".."):
        raise ContractError(f"{sid}: to: resolved to {stem!r}, not a file stem")
    return stem


def run(pair_dir: Path, stage: dict, input_path: Path) -> dict:
    target = pair_dir / (_stem(stage, pair_dir) + input_path.suffix)
    if target != input_path:
        if target.exists():
            raise StageFailure(stage["id"], f"{target.name} already exists in the pair")
        input_path.rename(target)
    return {"fields": {}, "output": target, "meters": {}}
