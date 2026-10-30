import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from shapes.sheets.src.processor import process_file
from shapes.sheets.src.types import InferenceResult


def _mock_inference_result(data):
    return InferenceResult(
        data=data,
        backend="ollama",
        model="qwen3:8b",
        latency_ms=500,
        error=None,
        raw_response=json.dumps(data),
    )


def _write_inbox_file(sheet_dir, filename, content):
    path = sheet_dir / "ingest" / "inbox" / filename
    path.write_text(content)
    return path


class TestProcessNew:
    def test_new_creates_insert_op(self, sheet_dir):
        path = _write_inbox_file(
            sheet_dir, "test-new.txt", "NEW\nApt at Vossstrasse 35, 1200 EUR"
        )
        extracted = {"name": "Vossstrasse 35", "amount": 1200, "status": "new"}
        mock_result = _mock_inference_result(extracted)

        with patch("shapes.sheets.src.processor._call_inference", return_value=mock_result), \
             patch("shapes.sheets.src.processor._post_to_api") as mock_api:
            process_file(path, sheet_dir)

        call_args = mock_api.call_args[0][0]
        assert call_args["op"] == "insert"
        assert call_args["values"]["name"] == "Vossstrasse 35"
        assert call_args["values"]["amount"] == 1200

    def test_new_writes_journal_entry(self, sheet_dir):
        path = _write_inbox_file(
            sheet_dir, "test-new.txt", "NEW\nApt at Vossstrasse 35"
        )
        extracted = {"name": "Vossstrasse 35", "status": "new"}
        mock_result = _mock_inference_result(extracted)

        with patch("shapes.sheets.src.processor._call_inference", return_value=mock_result), \
             patch("shapes.sheets.src.processor._post_to_api"):
            process_file(path, sheet_dir)

        journal = (sheet_dir / "ingest" / "journal.jsonl").read_text().strip()
        assert journal != ""
        entry = json.loads(journal)
        assert entry["kind"] == "NEW"
        assert entry["backend"] == "ollama"

    def test_new_removes_inbox_file(self, sheet_dir):
        path = _write_inbox_file(
            sheet_dir, "test-new.txt", "NEW\nApt at Vossstrasse 35"
        )
        mock_result = _mock_inference_result({"name": "x", "status": "new"})

        with patch("shapes.sheets.src.processor._call_inference", return_value=mock_result), \
             patch("shapes.sheets.src.processor._post_to_api"):
            process_file(path, sheet_dir)

        assert not path.exists()


class TestProcessUpdate:
    def test_update_creates_update_op(self, sheet_dir):
        path = _write_inbox_file(
            sheet_dir,
            "test-update.txt",
            "UPDATE row_id=r20260501100000\n@a sent application today at 14:00",
        )
        updated = {"status": "done", "notes": "Applied"}
        mock_result = _mock_inference_result(updated)

        with patch("shapes.sheets.src.processor._call_inference", return_value=mock_result), \
             patch("shapes.sheets.src.processor._post_to_api") as mock_api, \
             patch("shapes.sheets.src.processor._get_row_from_api", return_value={"id": "r20260501100000", "name": "Apt A", "status": "new"}):
            process_file(path, sheet_dir)

        call_args = mock_api.call_args[0][0]
        assert call_args["op"] == "update"
        assert call_args["id"] == "r20260501100000"
        assert call_args["values"]["status"] == "done"


class TestProcessSet:
    def test_set_bypasses_inference(self, sheet_dir):
        path = _write_inbox_file(
            sheet_dir,
            "test-set.txt",
            "SET row_id=r20260501100000\namount = 1500",
        )

        with patch("shapes.sheets.src.processor._post_to_api") as mock_api:
            process_file(path, sheet_dir)

        call_args = mock_api.call_args[0][0]
        assert call_args["op"] == "update"
        assert call_args["id"] == "r20260501100000"
        assert call_args["values"]["amount"] == 1500.0

    def test_set_validates_enum(self, sheet_dir):
        path = _write_inbox_file(
            sheet_dir,
            "test-set.txt",
            "SET row_id=r20260501100000\nstatus = invalid_value",
        )

        with patch("shapes.sheets.src.processor._post_to_api"):
            process_file(path, sheet_dir)

        failed_files = list((sheet_dir / "ingest" / "failed").iterdir())
        assert len(failed_files) > 0


class TestProcessFetch:
    def test_fetch_calls_preprocessor(self, sheet_dir):
        path = _write_inbox_file(
            sheet_dir,
            "test-fetch.txt",
            "FETCH https://example.com/listing/123",
        )
        extracted = {"name": "Example Apt", "status": "new"}
        mock_result = _mock_inference_result(extracted)

        with patch("shapes.sheets.src.processor._call_inference", return_value=mock_result), \
             patch("shapes.sheets.src.processor._post_to_api"), \
             patch("shapes.sheets.src.preprocessors.fetch.preprocess", return_value="Cleaned listing text"):
            process_file(path, sheet_dir)

        assert not path.exists()


class TestParseContext:
    def test_parse_key_value_context(self, sheet_dir):
        path = _write_inbox_file(
            sheet_dir,
            "test-ctx.txt",
            "UPDATE row_id=r20260501100000\n@a sent application today",
        )
        updated = {"status": "done"}
        mock_result = _mock_inference_result(updated)

        with patch("shapes.sheets.src.processor._call_inference", return_value=mock_result), \
             patch("shapes.sheets.src.processor._post_to_api") as mock_api, \
             patch("shapes.sheets.src.processor._get_row_from_api", return_value={"id": "r20260501100000", "name": "Apt A", "status": "new"}):
            process_file(path, sheet_dir)

        call_args = mock_api.call_args[0][0]
        assert call_args["op"] == "update"
        assert call_args["id"] == "r20260501100000"


class TestProcessAppend:
    def test_append_creates_log_entry(self, sheet_dir):
        path = _write_inbox_file(
            sheet_dir, "test-log.txt",
            "LOG row_id=r20260501100000\n@alex sent application today"
        )

        with patch("shapes.sheets.src.processor._post_to_api") as mock_api:
            process_file(path, sheet_dir)

        call_args = mock_api.call_args[0][0]
        assert call_args["op"] == "append"
        assert call_args["field"] == "activity"
        assert call_args["entry"]["by"] == "alex"
        assert call_args["entry"]["text"] == "@alex sent application today"
        assert call_args["entry"]["ts"] is not None

    def test_append_extracts_mention(self, sheet_dir):
        path = _write_inbox_file(
            sheet_dir, "test-log.txt",
            "LOG row_id=r20260501100000\n@a attended viewing"
        )

        with patch("shapes.sheets.src.processor._post_to_api") as mock_api:
            process_file(path, sheet_dir)

        entry = mock_api.call_args[0][0]["entry"]
        assert entry["by"] == "a"

    def test_append_no_mention(self, sheet_dir):
        path = _write_inbox_file(
            sheet_dir, "test-log.txt",
            "LOG row_id=r20260501100000\nsent application by email"
        )

        with patch("shapes.sheets.src.processor._post_to_api") as mock_api:
            process_file(path, sheet_dir)

        entry = mock_api.call_args[0][0]["entry"]
        assert entry["by"] == ""

    def test_append_skips_email_mention(self, sheet_dir):
        path = _write_inbox_file(
            sheet_dir, "test-log.txt",
            "LOG row_id=r20260501100000\ncontacted via foo@bar.com"
        )

        with patch("shapes.sheets.src.processor._post_to_api") as mock_api:
            process_file(path, sheet_dir)

        entry = mock_api.call_args[0][0]["entry"]
        assert entry["by"] == ""

    def test_append_removes_inbox_file(self, sheet_dir):
        path = _write_inbox_file(
            sheet_dir, "test-log.txt",
            "LOG row_id=r20260501100000\n@alex test"
        )

        with patch("shapes.sheets.src.processor._post_to_api"):
            process_file(path, sheet_dir)

        assert not path.exists()


class TestProcessFailure:
    def test_inference_error_moves_to_failed(self, sheet_dir):
        path = _write_inbox_file(
            sheet_dir, "test-fail.txt", "NEW\nGarbled content"
        )
        failed_result = InferenceResult(
            data=None,
            backend="ollama",
            model="qwen3:8b",
            latency_ms=500,
            error="JSON parse error",
            raw_response="not json",
        )

        with patch("shapes.sheets.src.processor._call_inference", return_value=failed_result):
            process_file(path, sheet_dir)

        assert not path.exists()
        failed_files = list((sheet_dir / "ingest" / "failed").iterdir())
        assert any(f.name.endswith(".error") for f in failed_files)

    def test_empty_inference_data_moves_to_failed(self, sheet_dir):
        path = _write_inbox_file(
            sheet_dir, "test-empty.txt", "NEW\nSome listing text"
        )
        empty_result = _mock_inference_result({"name": "", "status": None, "amount": None})

        with patch("shapes.sheets.src.processor._call_inference", return_value=empty_result), \
             patch("shapes.sheets.src.processor._post_to_api") as mock_api:
            process_file(path, sheet_dir)

        mock_api.assert_not_called()
        assert not path.exists()
        failed_dir = sheet_dir / "ingest" / "failed"
        error_files = [f for f in failed_dir.iterdir() if f.name.endswith(".error")]
        assert len(error_files) > 0
        assert "empty values" in error_files[0].read_text()
