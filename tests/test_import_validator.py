import pytest
from shapes.sheets.src.validator import validate_composer_output, ValidationError


def _base_analysis():
    return {
        "file": "test.csv",
        "row_count": 3,
        "columns": [
            {
                "header": "Name",
                "position": 0,
                "type": "string",
                "date_format": None,
                "nulls": 0,
                "unique_count": 3,
                "total_count": 3,
                "is_unique": True,
                "values": None,
                "samples": ["Alice", "Bob", "Charlie"],
                "looks_like_url": False,
                "max_length": 7,
                "malformed_count": 0,
            },
            {
                "header": "Status",
                "position": 1,
                "type": "string",
                "date_format": None,
                "nulls": 0,
                "unique_count": 2,
                "total_count": 3,
                "is_unique": False,
                "values": ["active", "inactive"],
                "samples": ["active", "inactive", "active"],
                "looks_like_url": False,
                "max_length": 8,
                "malformed_count": 0,
            },
        ],
    }


def _base_composer_output():
    return {
        "title": "Test Sheet",
        "description": "A test sheet.",
        "header_map": {
            "Name": "name",
            "Status": "status",
        },
        "fields": {
            "id": "primary",
            "name": {"type": "string", "label": "Name"},
            "status": {
                "type": "enum",
                "values": ["active", "inactive"],
                "label": "Status",
            },
            "created_at": "datetime",
            "updated_at": "datetime",
        },
        "pipeline": {
            "inputs": {
                "NEW": {
                    "prompt_template": "extract",
                    "op": "insert",
                    "key": "n",
                    "description": "Create from text",
                },
                "SET": {
                    "bypass_inference": True,
                    "op": "update",
                    "key": "e",
                    "description": "Edit cell",
                    "context": {"row_id": "required", "cell": "required"},
                },
            }
        },
        "keys": {"view": "v", "search": "/", "toggle_hidden": "H", "open": "o"},
        "view": {},
    }


class TestValidatorPasses:
    def test_valid_output_passes(self, tmp_path):
        templates = tmp_path / "prompts"
        templates.mkdir()
        (templates / "extract.md").write_text("template")
        validate_composer_output(
            _base_composer_output(), _base_analysis(), templates
        )


class TestHeaderMapValidation:
    def test_missing_source_header(self, tmp_path):
        templates = tmp_path / "prompts"
        templates.mkdir()
        (templates / "extract.md").write_text("template")
        output = _base_composer_output()
        output["header_map"]["NonExistent"] = "nope"
        with pytest.raises(ValidationError, match="NonExistent"):
            validate_composer_output(output, _base_analysis(), templates)

    def test_uncovered_source_column(self, tmp_path):
        templates = tmp_path / "prompts"
        templates.mkdir()
        (templates / "extract.md").write_text("template")
        output = _base_composer_output()
        del output["header_map"]["Status"]
        with pytest.raises(ValidationError, match="Status"):
            validate_composer_output(output, _base_analysis(), templates)

    def test_duplicate_field_names(self, tmp_path):
        templates = tmp_path / "prompts"
        templates.mkdir()
        (templates / "extract.md").write_text("template")
        output = _base_composer_output()
        output["header_map"]["Status"] = "name"  # collision with Name->name
        with pytest.raises(ValidationError, match="duplicate"):
            validate_composer_output(output, _base_analysis(), templates)

    def test_null_mapped_column_allowed(self, tmp_path):
        templates = tmp_path / "prompts"
        templates.mkdir()
        (templates / "extract.md").write_text("template")
        output = _base_composer_output()
        output["header_map"]["Status"] = None
        del output["fields"]["status"]
        validate_composer_output(output, _base_analysis(), templates)


class TestPrimaryKeyValidation:
    def test_no_primary_key_fails(self, tmp_path):
        templates = tmp_path / "prompts"
        templates.mkdir()
        (templates / "extract.md").write_text("template")
        output = _base_composer_output()
        del output["fields"]["id"]
        with pytest.raises(ValidationError, match="primary"):
            validate_composer_output(output, _base_analysis(), templates)


class TestKeyCollisionValidation:
    def test_duplicate_keys_fail(self, tmp_path):
        templates = tmp_path / "prompts"
        templates.mkdir()
        (templates / "extract.md").write_text("template")
        output = _base_composer_output()
        output["pipeline"]["inputs"]["NEW"]["key"] = "v"  # collides with keys.view
        with pytest.raises(ValidationError, match="collision"):
            validate_composer_output(output, _base_analysis(), templates)


class TestEnumIntegrity:
    def test_invented_enum_value_fails(self, tmp_path):
        templates = tmp_path / "prompts"
        templates.mkdir()
        (templates / "extract.md").write_text("template")
        output = _base_composer_output()
        output["fields"]["status"]["values"] = ["active", "inactive", "invented"]
        with pytest.raises(ValidationError, match="enum.*invented"):
            validate_composer_output(output, _base_analysis(), templates)

    def test_dropped_enum_value_fails(self, tmp_path):
        templates = tmp_path / "prompts"
        templates.mkdir()
        (templates / "extract.md").write_text("template")
        output = _base_composer_output()
        output["fields"]["status"]["values"] = ["active"]
        with pytest.raises(ValidationError, match="enum.*inactive"):
            validate_composer_output(output, _base_analysis(), templates)


class TestPromptTemplateValidation:
    def test_missing_template_fails(self, tmp_path):
        templates = tmp_path / "prompts"
        templates.mkdir()
        # No extract.md created
        with pytest.raises(ValidationError, match="extract"):
            validate_composer_output(
                _base_composer_output(), _base_analysis(), templates
            )


class TestTypeCompatibility:
    def test_string_to_enum_with_values_ok(self, tmp_path):
        templates = tmp_path / "prompts"
        templates.mkdir()
        (templates / "extract.md").write_text("template")
        validate_composer_output(
            _base_composer_output(), _base_analysis(), templates
        )

    def test_string_to_number_fails(self, tmp_path):
        templates = tmp_path / "prompts"
        templates.mkdir()
        (templates / "extract.md").write_text("template")
        output = _base_composer_output()
        output["fields"]["name"] = {"type": "number", "label": "Name"}
        with pytest.raises(ValidationError, match="type.*compat"):
            validate_composer_output(output, _base_analysis(), templates)
