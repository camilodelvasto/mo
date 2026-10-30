# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Typed errors for the access engine. Everything throws; nothing swallows."""


class AccessError(Exception):
    """Base for all access-engine failures."""


class PassportError(AccessError):
    """The bound embedder's identity diverges from the index passport."""


class FilterError(AccessError):
    """A filter expression names an undeclared field, an invalid enum, or does not parse."""


class CitationError(AccessError):
    """The model emitted a [doc:chunk] marker absent from the retrieval set."""


class AskError(AccessError):
    """The corpus declares no ask.yaml, or names an undeclared ask/profile."""


class SynthesisError(AskError):
    """A synthesize or condense capability spawn failed (non-zero exit). A subclass
    of AskError so existing handlers still catch it, but distinguishable for the
    wire kind `synthesis_failed`."""


class EmbedError(AccessError):
    """The embedder returned a short, ragged, or misaligned batch."""


class TitleError(SynthesisError):
    """A `titled` ask's synthesis did not yield a usable {answer, title} JSON: the
    result was not the expected object, or the title or answer was missing or empty.
    A subclass of SynthesisError — it IS a synthesis failure, so it carries the wire
    kind `synthesis_failed` (502), not `unknown_ask` (404), and existing AskError
    handlers still catch it."""


class HistoryError(AccessError):
    """The conversation history does not strictly alternate user/assistant, opening
    with the user and closing with the assistant. The provider refuses any other
    shape; the engine refuses it first, by name, instead of merging or dropping
    turns. Wire kind `history_malformed`."""


class AttachmentError(AccessError):
    """A rejected attachment. `kind` is a stable, named reason the HTTP/stream layer
    maps to a status/error event: too_large, wrong_type, too_many, undecodable,
    no_attachments_policy, attachment_untrusted."""
    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.kind = kind
