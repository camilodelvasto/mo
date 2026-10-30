"""Tests for grove OG enforcer."""
import pytest
from og import validate_grove_og, OGError

class TestValidateGroveOg:
    def test_valid_og_passes(self):
        grove = {"og": {"title": "T", "description": "D", "image": "img.png"}}
        validate_grove_og(grove)

    def test_missing_og_throws(self):
        with pytest.raises(OGError, match="og"):
            validate_grove_og({})

    def test_missing_title_throws(self):
        with pytest.raises(OGError, match="title"):
            validate_grove_og({"og": {"description": "D", "image": "img.png"}})

    def test_missing_description_throws(self):
        with pytest.raises(OGError, match="description"):
            validate_grove_og({"og": {"title": "T", "image": "img.png"}})

    def test_missing_image_throws(self):
        with pytest.raises(OGError, match="image"):
            validate_grove_og({"og": {"title": "T", "description": "D"}})
