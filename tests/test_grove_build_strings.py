"""Tests for CHAT_STRING_KEYS in the grove build gate."""
from shapes.grove.exporters.build import CHAT_STRING_KEYS


def test_chat_stop_is_required():
    assert "chat_stop" in CHAT_STRING_KEYS
