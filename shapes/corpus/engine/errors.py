# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Typed errors. Everything throws; nothing here swallows."""


class CorpusError(Exception):
    """Base for every corpus engine error."""


class SidecarError(CorpusError):
    """A sidecar could not be read or written (torn file, bad YAML)."""


class IntegrityError(CorpusError):
    """A sidecar changed outside the engine, or the custody chain broke."""


class ContractError(CorpusError):
    """corpus.yaml or flow.yaml is missing, invalid, or unresolvable."""


class CapabilityError(CorpusError):
    """A name the flow uses is unbound or its binary is missing. Startup error."""


class AssertRejected(CorpusError):
    """An assert file failed validation against the flow."""


class StageFailure(CorpusError):
    """A bound, present capability rejected one input. Fails the pair, not the corpus."""

    def __init__(self, stage_id: str, reason: str):
        self.stage_id = stage_id
        self.reason = reason
        super().__init__(f"stage '{stage_id}' failed: {reason}")


class LockError(CorpusError):
    """A corpus lock is held by a live process, or by an unverifiable host."""
