"""Tests for S3 deploy adapter."""
import pytest
from shapes.shared.adapters.s3 import validate_config, build_sync_command, S3Error


class TestS3:
    def test_valid_config(self):
        validate_config({"bucket": "my-grove", "endpoint": "https://s3.example.com"})

    def test_missing_bucket_throws(self):
        with pytest.raises(S3Error, match="bucket"):
            validate_config({"endpoint": "https://s3.example.com"})

    def test_missing_endpoint_throws(self):
        with pytest.raises(S3Error, match="endpoint"):
            validate_config({"bucket": "b"})

    def test_empty_bucket_throws(self):
        with pytest.raises(S3Error, match="empty"):
            validate_config({"bucket": "", "endpoint": "https://s3.example.com"})

    def test_empty_endpoint_throws(self):
        with pytest.raises(S3Error, match="empty"):
            validate_config({"bucket": "b", "endpoint": ""})

    def test_sync_command_includes_publish_path(self):
        cmd = build_sync_command("/dist", {"bucket": "my-grove", "endpoint": "https://s3.example.com"}, "/blog")
        assert "s3://my-grove/blog" in cmd

    def test_endpoint_always_present(self):
        cmd = build_sync_command("/dist", {"bucket": "b", "endpoint": "https://s3.example.com"}, "/")
        assert "--endpoint-url" in cmd
        assert "https://s3.example.com" in cmd


def test_deploy_returns_live(monkeypatch, tmp_path):
    import types
    from shapes.shared.adapters import s3
    from shapes.shared.adapters.outcome import Live
    monkeypatch.setattr(s3.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=0, stderr=""))
    out = s3.deploy(tmp_path, {"bucket": "b", "endpoint": "https://s3.example.com"}, "/blog")
    assert out == Live("https://s3.example.com/b/blog")
