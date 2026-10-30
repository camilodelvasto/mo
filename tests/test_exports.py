from pathlib import Path

import pytest
import yaml

from shapes.sheets.src.exports import load_exports, validate_exports, ExportsError, resolve_output_path


def _write_exports(sheet_dir, exports_dict):
    (sheet_dir / "exports.yaml").write_text(
        yaml.dump({"exports": exports_dict}, sort_keys=False)
    )


def test_load_exports_returns_dict(sheet_dir):
    _write_exports(sheet_dir, {"local": {"formats": ["csv"]}})
    exports = load_exports(sheet_dir)
    assert "local" in exports
    assert exports["local"]["formats"] == ["csv"]


def test_load_exports_missing_file_raises(sheet_dir):
    with pytest.raises(ExportsError, match="exports.yaml not found"):
        load_exports(sheet_dir)


def test_validate_unknown_format(sheet_dir):
    config = {"bad": {"formats": ["pdf"]}}
    field_names = ["name", "amount"]
    with pytest.raises(ExportsError, match="Unknown format.*pdf"):
        validate_exports(config, field_names)


def test_validate_unknown_field(sheet_dir):
    config = {"local": {"formats": ["csv"], "fields": ["name", "typo_field"]}}
    field_names = ["name", "amount"]
    with pytest.raises(ExportsError, match="Unknown field.*typo_field"):
        validate_exports(config, field_names)


def test_validate_unknown_locale():
    config = {"local": {"formats": ["csv"], "locale": "xx_XX"}}
    field_names = ["name"]
    with pytest.raises(ExportsError, match="Unknown locale"):
        validate_exports(config, field_names)


def test_validate_multi_format_template_without_format_var():
    config = {
        "bad": {
            "formats": ["csv", "xlsx"],
            "output": "~/exports/{sheet}-{date}.txt",
        }
    }
    field_names = ["name"]
    with pytest.raises(ExportsError, match="must contain.*\\{format\\}"):
        validate_exports(config, field_names)


def test_validate_multi_format_template_with_format_var():
    config = {
        "ok": {
            "formats": ["csv", "xlsx"],
            "output": "~/exports/{sheet}.{format}",
        }
    }
    field_names = ["name"]
    validate_exports(config, field_names)


def test_validate_unknown_substitution():
    config = {"bad": {"formats": ["csv"], "output": "~/exports/{bogus}.csv"}}
    field_names = ["name"]
    with pytest.raises(ExportsError, match="Unknown substitution.*bogus"):
        validate_exports(config, field_names)


def test_validate_valid_config():
    config = {
        "local": {"formats": ["csv", "xlsx"]},
        "partner": {
            "formats": ["xlsx"],
            "fields": ["name", "amount"],
            "locale": "de_DE",
            "output": "~/exports/{sheet}-{date}.{format}",
        },
    }
    field_names = ["name", "amount", "status"]
    validate_exports(config, field_names)


def test_default_output_path():
    path = resolve_output_path(
        export_name="local",
        export_config={"formats": ["csv"]},
        sheet_dir=Path("/content/suchprotokoll"),
        sheet_name="suchprotokoll",
        fmt="csv",
    )
    assert path == Path("/content/suchprotokoll/exports/local/suchprotokoll.csv")


def test_output_directory_override():
    path = resolve_output_path(
        export_name="shared",
        export_config={"formats": ["csv"], "output": "/tmp/exports"},
        sheet_dir=Path("/content/suchprotokoll"),
        sheet_name="suchprotokoll",
        fmt="csv",
    )
    assert path == Path("/tmp/exports/suchprotokoll.csv")


def test_output_template_override():
    path = resolve_output_path(
        export_name="partner",
        export_config={
            "formats": ["xlsx"],
            "output": "/tmp/{sheet}-{date}.{format}",
        },
        sheet_dir=Path("/content/suchprotokoll"),
        sheet_name="suchprotokoll",
        fmt="xlsx",
    )
    assert path.parent == Path("/tmp")
    assert path.name.startswith("suchprotokoll-")
    assert path.name.endswith(".xlsx")
    assert len(path.stem.split("-")) == 4


def test_output_template_with_name_and_datetime():
    path = resolve_output_path(
        export_name="backup",
        export_config={
            "formats": ["csv"],
            "output": "/tmp/{name}-{datetime}.{format}",
        },
        sheet_dir=Path("/content/test"),
        sheet_name="test",
        fmt="csv",
    )
    assert path.parent == Path("/tmp")
    assert path.name.startswith("backup-")
    assert path.suffix == ".csv"


def test_output_tilde_expansion():
    path = resolve_output_path(
        export_name="local",
        export_config={"formats": ["csv"], "output": "~/exports"},
        sheet_dir=Path("/content/test"),
        sheet_name="test",
        fmt="csv",
    )
    assert "~" not in str(path)
    assert path.name == "test.csv"
