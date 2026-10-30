"""S3-compatible storage deploy adapter."""
import subprocess
from pathlib import Path

from shapes.shared.adapters.outcome import Live


class S3Error(Exception):
    pass


# capabilities the deploy rail injects into config — none
REQUIRES = ()


REQUIRED_FIELDS = ("bucket", "endpoint")


def validate_config(config: dict) -> None:
    for key in REQUIRED_FIELDS:
        if key not in config:
            raise S3Error(f"S3 config missing '{key}'")
        if not config[key]:
            raise S3Error(f"S3 config has empty '{key}'")


def build_sync_command(dist_path: str, config: dict, publish_path: str) -> list[str]:
    validate_config(config)
    bucket = config["bucket"]
    endpoint = config["endpoint"]
    s3_prefix = f"s3://{bucket}{publish_path}"
    cmd = ["aws", "s3", "sync", str(dist_path) + "/", s3_prefix, "--delete",
           "--endpoint-url", endpoint]
    return cmd


def deploy(dist_path: Path, config: dict, publish_path: str, *, force: bool = False, spa: bool = False) -> Live:
    cmd = build_sync_command(str(dist_path), config, publish_path)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise S3Error(f"S3 sync failed: {result.stderr}")

    endpoint = config["endpoint"]
    bucket = config["bucket"]
    return Live(f"{endpoint}/{bucket}{publish_path}")


def unpublish(config: dict, publish_path: str) -> None:
    validate_config(config)
    bucket = config["bucket"]
    endpoint = config["endpoint"]
    s3_prefix = f"s3://{bucket}{publish_path}"
    cmd = ["aws", "s3", "rm", s3_prefix, "--recursive", "--endpoint-url", endpoint]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise S3Error(f"S3 unpublish failed: {result.stderr}")
