# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""engine.chunk-ast — structural boundaries only. Markdown AST blocks,
greedily packed toward target_size, hard-capped at max_size, split on SOURCE
offsets so each chunk's text is the exact transcript slice it spans. Chunking
is custody (frozen in the bundle); embedding is someone else's rebuildable
tail.

Each record locates itself: `ast_path` is the heading hierarchy, `span` is
[start, end) characters into the transcript, `text` is transcript[span] (so
transcript[span] == text and `contiguous` is always true for this chunker —
it only joins consecutive blocks), and `ref` is a content hash of ast_path +
normalized text, deterministic and stable across reprocess. Refs are unique
per document: downstream keys by ref (the embedder re-attaches vectors by it,
the index inserts by it), so a repeated identical block under the same section
gets its occurrence ordinal salted into the hash. First occurrence hashes as
before; occurrence order follows the transcript, so refs stay stable.
"""
import hashlib
import json
from pathlib import Path

from markdown_it import MarkdownIt

from shapes.corpus.engine.errors import StageFailure


def run(pair_dir: Path, stage: dict, input_path: Path) -> dict:
    with_ = stage.get("with") or {}
    target = with_["target_size"]    # no defaults: the flow declares both
    max_size = with_["max_size"]
    text = input_path.read_text(encoding="utf-8")
    blocks = _blocks(text)
    if not blocks:
        raise StageFailure(stage["id"], "empty transcript — nothing to chunk")
    chunks = _pack(blocks, target, max_size)
    out = pair_dir / "chunks.jsonl"
    seen: dict[str, int] = {}
    out.write_text(
        "".join(json.dumps(_record(c, text, seen)) + "\n" for c in chunks))
    return {"fields": {}, "output": out, "meters": {"chunks": len(chunks)}}


def _line_starts(text: str) -> list[int]:
    """Char offset of the start of each line, plus a final entry == len(text),
    so a markdown-it map end-line indexes the char after the block."""
    starts = [0]
    for line in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    return starts


def _blocks(text: str) -> list[dict]:
    """Top-level blocks as {ast_path, start, end} in source-char offsets.
    A heading updates the heading stack and carries the path including itself;
    every following block inherits the current stack until the next heading."""
    md = MarkdownIt()
    line_starts = _line_starts(text)
    last = len(line_starts) - 1

    def char(line: int) -> int:
        return line_starts[min(line, last)]

    tokens = md.parse(text)
    blocks: list[dict] = []
    stack: list[tuple[int, str]] = []   # (heading level, heading text)
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        is_block = tok.level == 0 and tok.map and (
            tok.type.endswith("_open")
            or tok.type in ("fence", "hr", "html_block"))
        if tok.level == 0 and tok.map and tok.type == "heading_open":
            level = int(tok.tag[1])     # h1 -> 1
            heading_text = tokens[i + 1].content if i + 1 < len(tokens) else ""
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading_text))
            start, end = tok.map
            blocks.append({"ast_path": " > ".join(h for _, h in stack),
                           "start": char(start), "end": char(end)})
        elif is_block:
            start, end = tok.map
            blocks.append({"ast_path": " > ".join(h for _, h in stack),
                           "start": char(start), "end": char(end)})
        i += 1
    return blocks


def _pack(blocks: list[dict], target: int, max_size: int) -> list[dict]:
    """Greedy pack of consecutive blocks toward target on source length; one
    oversized run is hard-split on source offsets. A chunk never spans two
    sections — a block whose ast_path differs flushes the current chunk, so
    ast_path always names the section the chunk's text actually came from.
    Every chunk stays a contiguous source range, so transcript[span] == text
    holds."""
    chunks: list[dict] = []
    cur: dict | None = None
    for b in blocks:
        if cur is None:
            cur = dict(b)
        elif b["ast_path"] != cur["ast_path"] or b["end"] - cur["start"] > target:
            chunks.append(cur)
            cur = dict(b)
        else:
            cur["end"] = b["end"]
        while cur["end"] - cur["start"] > max_size:
            split = cur["start"] + max_size
            chunks.append({"ast_path": cur["ast_path"],
                           "start": cur["start"], "end": split})
            cur = {"ast_path": cur["ast_path"], "start": split, "end": cur["end"]}
    if cur is not None:
        chunks.append(cur)
    return chunks


def _record(c: dict, text: str, seen: dict[str, int]) -> dict:
    body = text[c["start"]:c["end"]]
    norm = " ".join(body.split())
    key = c["ast_path"] + "\x00" + norm
    n = seen.get(key, 0)
    seen[key] = n + 1
    if n:                               # repeat of an identical block: salt the
        key += "\x00" + str(n)          # occurrence ordinal so the ref is unique
    ref = "c" + hashlib.sha256(key.encode()).hexdigest()[:8]
    return {"ref": ref, "ast_path": c["ast_path"], "span": [c["start"], c["end"]],
            "contiguous": True, "text": body}
