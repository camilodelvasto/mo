# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Run one stage on a pair: resolve capability, resolve ${...} placeholders,
append the derived output contract to LLM prompts, spawn, interpret per
emits:, parse structured output into fields:/meters (malformed -> stage
failure, never a partial parse), append the custody entry. Throws on failure;
the reactor applies the handler."""
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from shapes.corpus.builtins import REGISTRY
from shapes.corpus.engine import capabilities, identity, sidecar
from shapes.corpus.engine.errors import ContractError, IntegrityError, StageFailure
from shapes.corpus.engine.fold import fold

ARTIFACT_FILES = {"transcript": "transcript.md", "chunks": "chunks.jsonl"}

_FAILURE_TAIL = 2000  # bound captured output; a tool can dump a lot on failure


def _spawn_failure_reason(proc) -> str:
    """A capability that exits non-zero may report on EITHER stream — claude -p
    writes 'Prompt is too long' to stdout, clamscan writes to stderr. Capture
    both (bounded), so the meta sidecar's failed: reason says WHY, not just the
    exit code. Falls back to the exit code only when both streams are empty."""
    err = proc.stderr.decode(errors="replace").strip()
    out = proc.stdout.decode(errors="replace").strip()
    detail = "  ".join(part for part in (err, out) if part)
    return detail[-_FAILURE_TAIL:] or f"exit {proc.returncode}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_stage(pair_dir: Path, stage: dict, contract: dict, table: dict, observer) -> dict:
    meta_path = pair_dir / "meta.yaml"
    doc = sidecar.read_verified(meta_path)
    projection = fold(doc["stages"])
    input_name, input_path = _input_artifact(pair_dir, doc)
    # Capture the input hash NOW — a stage that rewrites its own artifact in
    # place (e.g. anonymize: transcript → transcript) overwrites input_path, so
    # hashing it after the capability runs would record the output as the input
    # and break the custody chain.
    input_hash = identity.sha256_file(input_path)
    cap_name = _resolve_uses(stage, projection)
    started = _now()

    if cap_name.startswith("engine."):
        result = REGISTRY[cap_name](pair_dir, stage, input_path)
        raw_fields, output = result["fields"], result["output"]
        meters, proposed, confidence = result["meters"], {}, {}
        locality = "local"
        prompt_block = None
        prompt_text = response_text = None
    else:
        binding = capabilities.resolve(cap_name, table)
        (raw_fields, proposed, confidence, output, meters, prompt_block,
         prompt_text, response_text) = _spawn(pair_dir, stage, binding, input_path)
        locality = "api" if cap_name.startswith("api.") else "local"

    fields, entry_proposed, parked, proposed_conf = _gate(
        stage, raw_fields, proposed, confidence)
    entry = {
        "id": stage["id"],
        "capability": {"id": cap_name},
        "locality": locality,
        "input": {"artifact": input_name, "hash": input_hash},
        "started": started,
        "finished": _now(),
        "meters": meters,
        "fields": fields,
    }
    if stage.get("when"):
        entry["when_matched"] = stage["when"]
    if prompt_block is not None:
        entry["prompt"] = prompt_block
    if output is not None:
        artifact = stage["artifact"]  # a stage that produces output declares it
        entry["output"] = {"artifact": artifact, "hash": identity.sha256_file(output)}
        doc.setdefault("artifacts", {})[artifact] = {"path": f"./{output.name}"}
    else:
        entry["output"] = {"hash": entry["input"]["hash"]}  # reads, never alters
    if entry_proposed:
        entry["proposed"] = entry_proposed
    if parked:
        entry["parked"] = parked
    if proposed_conf:
        entry["meters"] = {**entry["meters"], "confidence": proposed_conf}

    doc["stages"].append(entry)
    sidecar.write(meta_path, doc)

    if prompt_block is not None:
        observer.emit("llm-call", doc_id=pair_dir.name, stage=stage["id"],
                      capability=cap_name, duration_ms=meters.get("duration_ms"),
                      fields=fields, confidence=confidence, parked=parked,
                      gates={n: d["confidence_min"]
                             for n, d in (stage.get("fields") or {}).items()
                             if "confidence_min" in d},
                      prompt=prompt_text, response=response_text)
    else:
        observer.emit("stage-done", doc_id=pair_dir.name, stage=stage["id"],
                      capability=cap_name, locality=locality,
                      duration_ms=meters.get("duration_ms"))
    return entry


def _input_artifact(pair_dir: Path, doc: dict) -> tuple[str, Path]:
    """transcript once one exists, original before that (plan decision 8)."""
    artifacts = doc.get("artifacts", {})
    name = "transcript" if "transcript" in artifacts else "original"
    if name not in artifacts:
        raise ContractError(f"pair {pair_dir} has no original artifact")
    path = pair_dir / Path(artifacts[name]["path"]).name
    if not path.is_file():
        raise IntegrityError(f"input artifact {name!r} missing from {pair_dir}")
    return name, path


def _resolve_uses(stage: dict, projection: dict) -> str:
    uses = stage["uses"]
    if isinstance(uses, str):
        return uses
    value = projection.get(uses["dispatch_on"])
    routes = uses["routes"]
    if value in routes:
        return routes[value]
    if value:
        family = value.split("/")[0] + "/*"
        if family in routes:
            return routes[family]
    raise StageFailure(stage["id"], f"no route for {uses['dispatch_on']} {value}")


def _spawn(pair_dir: Path, stage: dict, binding: dict, input_path: Path):
    is_llm = bool((stage.get("with") or {}).get("prompt"))
    prompt_block = None
    prompt_text = response_text = None
    if is_llm:
        prompt = _resolve_prompt(stage, pair_dir)
        prompt_block = {"hash": "sha256:" + hashlib.sha256(prompt.encode()).hexdigest()}
        prompt_text = prompt
        payload = prompt.encode()
    else:
        payload = input_path.read_bytes()

    out_path = None
    argv = []
    for arg in binding["run"]:
        if arg == "${input}":
            argv.append(str(input_path))
        elif arg == "${output}":
            out_path = pair_dir / ARTIFACT_FILES[stage["artifact"]]
            argv.append(str(out_path))
        elif arg == "${prompt}":
            if not is_llm:
                raise ContractError("${prompt} in a binding requires a stage prompt")
            argv.append(prompt)
        else:
            argv.append(arg)

    stdin = payload if binding["reads"] == "stdin" else None
    timeout = binding.get("timeout")
    started = datetime.now(timezone.utc)
    try:
        proc = subprocess.run(argv, input=stdin, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise StageFailure(stage["id"], f"timed out after {timeout}s") from None
    duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    meters = {"duration_ms": duration_ms}

    emits = binding["emits"]
    if emits == "exit_code":
        mapped = binding["map"].get(str(proc.returncode))
        if mapped is None:
            raise StageFailure(stage["id"], f"unmapped exit code {proc.returncode}: "
                               f"{proc.stderr.decode(errors='replace').strip()}")
        field_name = _single_enum_field(stage)
        return {field_name: mapped}, {}, {}, None, meters, prompt_block, prompt_text, response_text

    if proc.returncode != 0:
        raise StageFailure(stage["id"], _spawn_failure_reason(proc))

    if emits == "transcript":
        if out_path is None or not out_path.is_file():
            raise StageFailure(stage["id"], "emits: transcript but no ${output} file produced")
        return {}, {}, {}, out_path, meters, prompt_block, prompt_text, response_text

    # emits: stdout
    text = proc.stdout.decode(errors="replace")
    if is_llm:
        response_text = text
        fields, proposed, confidence = _parse_llm(stage, text)
        return fields, proposed, confidence, None, meters, prompt_block, prompt_text, response_text
    if "artifact" in stage:
        out_path = pair_dir / ARTIFACT_FILES[stage["artifact"]]
        out_path.write_text(text)
        return {}, {}, {}, out_path, meters, prompt_block, prompt_text, response_text
    return {}, {}, {}, None, meters, prompt_block, prompt_text, response_text


def _resolve_prompt(stage: dict, pair_dir: Path) -> str:
    """${fields.<name>.values} from the stage's declarations,
    ${artifact.<name>} from the pair's files; then the derived contract."""
    import re
    template = stage["with"]["prompt"]

    def sub(match):
        path = match.group(1).split(".")
        if path[0] == "fields" and path[-1] == "values":
            return ", ".join(stage["fields"][path[1]]["values"])
        if path[0] == "artifact":
            return (pair_dir / ARTIFACT_FILES[path[1]]).read_text()
        raise ContractError(f"unknown placeholder ${{{match.group(1)}}}")

    prompt = re.sub(r"\$\{([^}]+)\}", sub, template)
    return prompt + "\n\n" + _output_contract(stage)


def _output_contract(stage: dict) -> str:
    lines = ["Respond with ONLY a JSON object, no prose, of this exact shape:",
             '{"fields": {...}, "proposed": {...}, "confidence": {...}}']
    for name, decl in (stage.get("fields") or {}).items():
        if not _model_writes(decl.get("by", "model")):
            continue
        kind = decl["type"]
        spec = f"one of: {', '.join(decl['values'])}" if kind == "enum" else kind
        lines.append(f'- fields.{name}: {spec}')
        if "confidence_min" in decl:
            lines.append(f"- confidence.{name}: your confidence, 0 to 1")
    for name in stage.get("proposes", []):
        lines.append(f"- proposed.{name}: suggested values (list of strings)")
    return "\n".join(lines)


def _unfence(text: str) -> str:
    """Some models wrap the answer in a markdown code fence despite the
    contract. Unwrap one outer ```/```json fence; anything else is untouched
    and must parse as-is."""
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        stripped = stripped[3:-3]
        if stripped.startswith("json"):
            stripped = stripped[4:]
        return stripped.strip()
    return text


def _parse_llm(stage: dict, text: str):
    try:
        answer = json.loads(_unfence(text))
        fields = answer["fields"]
        proposed = answer.get("proposed", {})
        confidence = answer.get("confidence", {})
        assert isinstance(fields, dict) and isinstance(proposed, dict), "fields and proposed must be JSON objects"
    except (json.JSONDecodeError, KeyError, AssertionError, TypeError) as exc:
        raise StageFailure(stage["id"], f"malformed model output: {exc}") from exc
    return fields, proposed, confidence


def _gate(stage: dict, raw_fields: dict, proposed_in: dict, confidence: dict):
    """Apply by:/confidence_min. Returns (fields, proposed, parked, proposed_conf)
    where proposed_conf maps each proposed-by-gate field to its confidence."""
    declared = stage.get("fields") or {}
    proposed_conf: dict = {}
    if not declared:
        return dict(raw_fields), dict(proposed_in), [], proposed_conf
    fields: dict = {}
    proposed: dict = dict(proposed_in)
    parked: list = []
    for name, decl in declared.items():
        by = decl.get("by", "model")
        if not _model_writes(by):
            # operator-only field: the model must not write it; it parks for a human
            if name in raw_fields:
                raise StageFailure(stage["id"], f"model emitted operator field {name}")
            parked.append(name)
            continue
        if name not in raw_fields:
            raise StageFailure(stage["id"], f"model output missing declared field {name}")
        value = raw_fields[name]
        gate = decl.get("confidence_min")
        if gate is not None:
            if name not in confidence:
                raise StageFailure(stage["id"], f"no confidence reported for gated field {name}")
            if confidence[name] < gate:
                proposed[name] = value
                proposed_conf[name] = confidence[name]
                if not decl.get("optional"):   # optional: keep as a proposal,
                    parked.append(name)        # never park — the doc completes
                continue
        fields[name] = value
    # builtins put intrinsic (undeclared) fields straight through (stamp's open set)
    for name, value in raw_fields.items():
        if name not in declared and name not in fields:
            fields[name] = value
    return fields, proposed, parked, proposed_conf


def _model_writes(by) -> bool:
    """`by:` may be a string or a list. The model may write a field whose `by:`
    admits 'model' — a field listing both writers (`[model, operator]`) is the
    model's to classify through its gate AND the operator's to override later.
    Only a field the model may NOT write (operator-only) parks at the stage."""
    return by == "model" if isinstance(by, str) else "model" in by


def _single_enum_field(stage: dict) -> str:
    enums = [n for n, d in (stage.get("fields") or {}).items() if d["type"] == "enum"]
    if len(enums) != 1:
        raise ContractError(
            f"stage {stage['id']}: emits: exit_code needs exactly one enum field")
    return enums[0]
