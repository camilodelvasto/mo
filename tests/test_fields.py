import pytest

from shapes.sheets.src.fields import Field, parse_fields, auto_label


class TestAutoLabel:
    def test_simple_name(self):
        assert auto_label("kaltmiete") == "Kaltmiete"

    def test_underscore_name(self):
        assert auto_label("last_action_at") == "Last Action At"

    def test_single_char(self):
        assert auto_label("id") == "Id"


class TestParseFieldsShortForm:
    def test_string_field(self):
        fields = parse_fields({"fields": {"name": "string"}})
        assert len(fields) == 1
        f = fields[0]
        assert f.name == "name"
        assert f.type == "string"
        assert f.label == "Name"
        assert f.align == "left"
        assert f.values is None

        assert f.description is None

    def test_number_field_aligns_right(self):
        fields = parse_fields({"fields": {"amount": "number"}})
        assert fields[0].align == "right"

    def test_primary_field(self):
        fields = parse_fields({"fields": {"id": "primary"}})
        assert fields[0].type == "primary"
        assert fields[0].label == "Id"

    def test_inline_enum(self):
        fields = parse_fields({"fields": {"status": "enum [new, done]"}})
        f = fields[0]
        assert f.type == "enum"
        assert f.values == ["new", "done"]

    def test_preserves_order(self):
        fields = parse_fields({"fields": {
            "id": "primary",
            "name": "string",
            "amount": "number",
        }})
        assert [f.name for f in fields] == ["id", "name", "amount"]


class TestParseFieldsLongForm:
    def test_with_label(self):
        fields = parse_fields({"fields": {
            "kaltmiete": {"type": "number", "label": "Kaltmiete (EUR)"}
        }})
        f = fields[0]
        assert f.name == "kaltmiete"
        assert f.type == "number"
        assert f.label == "Kaltmiete (EUR)"
        assert f.align == "right"

    def test_enum_with_values(self):
        fields = parse_fields({"fields": {
            "status": {
                "type": "enum",
                "values": ["neu", "beworben", "absage"],
                "label": "Status",
            }
        }})
        f = fields[0]
        assert f.type == "enum"
        assert f.values == ["neu", "beworben", "absage"]
        assert f.label == "Status"

    def test_with_align(self):
        fields = parse_fields({"fields": {
            "adresse": {"type": "string", "align": "left"}
        }})
        f = fields[0]
        assert f.align == "left"

    def test_with_description(self):
        fields = parse_fields({"fields": {
            "kaltmiete": {
                "type": "number",
                "label": "Kaltmiete",
                "description": "Base rent in EUR",
            }
        }})
        assert fields[0].description == "Base rent in EUR"

    def test_label_defaults_to_auto(self):
        fields = parse_fields({"fields": {
            "groesse_qm": {"type": "number"}
        }})
        assert fields[0].label == "Groesse Qm"

    def test_number_align_override(self):
        fields = parse_fields({"fields": {
            "amount": {"type": "number", "align": "center"}
        }})
        assert fields[0].align == "center"


class TestParseFieldsKey:
    def test_boolean_field_with_key(self):
        fields = parse_fields({"fields": {
            "starred": {"type": "boolean", "label": "★", "key": "s"}
        }})
        f = fields[0]
        assert f.name == "starred"
        assert f.type == "boolean"
        assert f.key == "s"

    def test_field_without_key(self):
        fields = parse_fields({"fields": {"name": "string"}})
        assert fields[0].key is None

    def test_long_form_without_key(self):
        fields = parse_fields({"fields": {
            "amount": {"type": "number", "label": "Amount"}
        }})
        assert fields[0].key is None


class TestEnumValidation:
    def test_enum_without_values_raises(self):
        import pytest
        with pytest.raises(ValueError, match="no values"):
            parse_fields({"fields": {"status": {"type": "enum"}}})

    def test_enum_with_values_ok(self):
        fields = parse_fields({"fields": {"status": {"type": "enum", "values": ["a", "b"]}}})
        assert fields[0].values == ["a", "b"]

    def test_inline_enum_without_values_raises(self):
        """'enum' short-form without brackets has no values — should raise."""
        import pytest
        with pytest.raises(ValueError, match="no values"):
            parse_fields({"fields": {"status": "enum"}})


class TestParseFieldsMixed:
    def test_short_and_long_together(self):
        fields = parse_fields({"fields": {
            "id": "primary",
            "created_at": "datetime",
            "kaltmiete": {
                "type": "number",
                "label": "Kaltmiete (EUR)",
            },
            "status": "enum [new, done]",
            "notes": "text",
        }})
        assert len(fields) == 5
        assert fields[0].type == "primary"
        assert fields[2].label == "Kaltmiete (EUR)"
        assert fields[3].type == "enum"
        assert fields[3].values == ["new", "done"]
