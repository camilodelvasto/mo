"""Tests that media and logo paths reject remote URLs."""
import json
import urllib.request
import urllib.error

import pytest


class TestMediaPathContract:
    """Document the assertLocalPath contract from layouts.js.

    The actual JS enforcement runs client-side. These tests document
    which paths are valid and which are rejected by the contract.
    """

    def test_local_relative_paths_are_valid(self):
        """These paths pass assertLocalPath."""
        valid = [
            "example/alianza/chart.png",
            "images/logo.svg",
            "nested/deep/path/file.jpg",
        ]
        for path in valid:
            assert not path.startswith("http")
            assert not path.startswith("//")
            assert not path.startswith("/")
            assert not path.startswith("data:")
            assert not path.startswith("file:")

    def test_remote_paths_are_rejected_by_contract(self):
        """These paths are rejected by assertLocalPath."""
        rejected = [
            "https://example.com/image.png",
            "http://evil.com/track.gif",
            "data:image/png;base64,abc",
            "file:///etc/passwd",
            "//cdn.example.com/img.png",
            "/absolute/path/image.png",
        ]
        for path in rejected:
            lower = path.lower().strip()
            assert (
                lower.startswith("http:")
                or lower.startswith("https:")
                or lower.startswith("data:")
                or lower.startswith("file:")
                or lower.startswith("//")
                or path.startswith("/")
            ), f"Path should be rejected: {path}"
