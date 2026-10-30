# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""corpus engine — declarative corpus preparation.

Module map (one responsibility each; see GUIDE.md before editing):

    fold.py         the projection: log -> flat description. THE shared
                    primitive. Scalar last-write-wins, set union-minus-removes,
                    proposed: ignored. Imported, never reimplemented.

    sidecar.py      read/write meta.yaml. Append-only. Atomic move (temp +
                    rename). The ONLY module that writes a sidecar. Stamps and
                    verifies the embedded integrity block; verify_chain
                    reconciles custody at resume.

    watcher.py      watch the corpus folder; settle (size stable across two
                    ticks); emit reactions for dropbox/, inbox/, and
                    flow.yaml changes. meta.yaml is watched for INTEGRITY
                    only: a foreign write halts the pair; it is never input.

    identity.py     hash a settled file; derive doc_id; detect duplicates.

    capabilities.py load the machine-root capabilities.yaml; resolve a name to
                    argv + reads/emits; VERIFY every name a flow uses is
                    bound and present at startup, else THROW.

    runner.py       run one stage on the worker pool: resolve capability,
                    resolve ${...} placeholders, append the derived output
                    contract to LLM prompts, spawn, interpret per emits:,
                    parse structured output into fields:/meters (malformed ->
                    stage failure, never a partial parse), append the custody
                    entry, move the pair. Throws on failure; the handler
                    decides quarantine/fail. Parking is field-gating, not
                    failure handling.

    reactor.py      the loop. Given a pair (or an inbox file, or a flow
                    change), compute the next step and take it. Re-check parked:
                    and re-evaluate rules: after every appended entry.

    assert_inbox.py validate an assert file against the flow; append one
                    assert entry or move to failed/inbox/ with a .reason.

    rules.py        evaluate flow-level rules: against the projection after
                    every entry; fire reactions (retire).

    errors.py       typed errors. Everything throws; nothing here swallows.
"""