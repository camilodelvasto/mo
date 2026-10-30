# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Resolve a named AWS profile to a credentials-file string, pulled from the aws
client at deploy time — never written to local disk, never on an argv. The key's
home stays ~/.aws; deploy streams it in-memory to the box. `export-credentials`
returns the same shape for a static access key and an SSO session, so this never
branches on profile type."""
import subprocess


class AwsCredsError(Exception):
    pass


def _export(profile: str) -> str:
    """The env-no-export lines for the profile, or raise AwsCredsError (stderr)."""
    r = subprocess.run(
        ["aws", "configure", "export-credentials", "--profile", profile,
         "--format", "env-no-export"],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise AwsCredsError(
            f"could not resolve aws profile {profile!r}: {r.stderr.strip()}")
    return r.stdout


def resolve_aws_creds(profile: str) -> str:
    env = {}
    for line in _export(profile).splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    akid = env.get("AWS_ACCESS_KEY_ID")
    secret = env.get("AWS_SECRET_ACCESS_KEY")
    if not akid or not secret:
        raise AwsCredsError(f"aws profile {profile!r} returned no key material")
    lines = ["[default]",
             f"aws_access_key_id = {akid}",
             f"aws_secret_access_key = {secret}"]
    if env.get("AWS_SESSION_TOKEN"):
        lines.append(f"aws_session_token = {env['AWS_SESSION_TOKEN']}")
    return "\n".join(lines) + "\n"
