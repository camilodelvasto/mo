import json
import pytest
from unittest.mock import MagicMock, patch

from shapes.sheets.src.types import InferenceResult

SAMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "amount": {"type": "number"},
    },
}


class TestOllamaBackend:
    def test_complete_success(self):
        from shapes.sheets.src.backends.ollama import complete

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": '{"name": "Apt A", "amount": 1200}'
        }

        with patch("shapes.sheets.src.backends.ollama.requests.post", return_value=mock_response):
            result = complete("Extract fields", SAMPLE_SCHEMA, model="qwen3:8b")

        assert isinstance(result, InferenceResult)
        assert result.data == {"name": "Apt A", "amount": 1200}
        assert result.backend == "ollama"
        assert result.model == "qwen3:8b"
        assert result.error is None

    def test_complete_invalid_json(self):
        from shapes.sheets.src.backends.ollama import complete

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "not json at all"}

        with patch("shapes.sheets.src.backends.ollama.requests.post", return_value=mock_response):
            result = complete("Extract fields", SAMPLE_SCHEMA, model="qwen3:8b")

        assert result.data is None
        assert result.error is not None


class TestClaudeBackend:
    def test_complete_success(self):
        from shapes.sheets.src.backends.claude import complete

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"name": "Apt A", "amount": 1200}'

        with patch("shapes.sheets.src.backends.claude.subprocess.run", return_value=mock_result):
            result = complete("Extract fields", SAMPLE_SCHEMA)

        assert isinstance(result, InferenceResult)
        assert result.data == {"name": "Apt A", "amount": 1200}
        assert result.backend == "claude"
        assert result.error is None

    def test_complete_nonzero_exit(self):
        from shapes.sheets.src.backends.claude import complete

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error occurred"

        with patch("shapes.sheets.src.backends.claude.subprocess.run", return_value=mock_result):
            result = complete("Extract fields", SAMPLE_SCHEMA)

        assert result.data is None
        assert result.error is not None


class TestAnthropicBackend:
    def test_anthropic_raises_without_key(self):
        from shapes.sheets.src.backends.anthropic import complete
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY not set"):
                complete("Extract fields", SAMPLE_SCHEMA)

    def test_complete_success(self):
        from shapes.sheets.src.backends.anthropic import complete

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": '{"name": "Apt A", "amount": 1200}'}]
        }

        with patch("shapes.sheets.src.backends.anthropic.requests.post", return_value=mock_response), \
             patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            result = complete(
                "Extract fields", SAMPLE_SCHEMA, model="claude-sonnet-4-20250514"
            )

        assert isinstance(result, InferenceResult)
        assert result.data == {"name": "Apt A", "amount": 1200}
        assert result.backend == "anthropic"
        assert result.error is None
