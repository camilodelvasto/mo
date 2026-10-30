# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The generation completion gate: prove the box can ANSWER, not just that it's up.
The find healthcheck embeds via ollama and spends no Bedrock, so a green health-gate
says nothing about generation. This runs PRE-SHIP — a 1-token converse per configured
model via the resolved profile (a Bedrock call is HTTPS, needs no box; same
profile/model/region the box will use). It catches the IAM-invoke-vs-model-access
gap before first ask. Fail loud → no ship."""


class SmokeError(Exception):
    pass


def model_region_pairs(capabilities: dict) -> set:
    """Distinct (model, region) from each capability's run args."""
    pairs = set()
    for binding in (capabilities or {}).get("capabilities", {}).values():
        run = binding.get("run") or []
        model = region = None
        for i, tok in enumerate(run):
            if tok == "--model" and i + 1 < len(run):
                model = run[i + 1]
            elif tok == "--region" and i + 1 < len(run):
                region = run[i + 1]
        if model and region:
            pairs.add((model, region))
    return pairs


def _converse_1tok(profile: str, model: str, region: str) -> None:
    import boto3
    from botocore.exceptions import ClientError, BotoCoreError
    try:
        client = boto3.Session(profile_name=profile).client(
            "bedrock-runtime", region_name=region)
        client.converse(modelId=model,
                        messages=[{"role": "user", "content": [{"text": "ping"}]}],
                        inferenceConfig={"maxTokens": 1})
    except (ClientError, BotoCoreError) as e:
        raise SmokeError(f"bedrock smoke failed for model {model!r} ({region}): {e}")


def smoke_models(profile: str, capabilities: dict) -> None:
    pairs = model_region_pairs(capabilities)
    if not pairs:
        raise SmokeError("no (model, region) found in capabilities.yaml run args")
    for model, region in sorted(pairs):
        try:
            _converse_1tok(profile, model, region)
        except SmokeError as e:
            raise SmokeError(f"{str(e)} (model: {model})") from e
