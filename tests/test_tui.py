from shapes.sheets.renderer.tui.app import SheetsApp


def test_tui_instantiates(sheet_dir):
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    assert app is not None
    assert app.sheet_dir == sheet_dir


def test_tui_parses_columns_from_schema(sheet_dir):
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    columns = app._get_columns()
    assert "name" in columns
    assert "amount" in columns
    assert "status" in columns
    assert "id" in columns


def test_tui_uses_labels_for_display(sheet_dir):
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    labels = [f.label for f in app._fields]
    assert "Name" in labels
    assert "Amount (EUR)" in labels
    assert "Status" in labels


def test_tui_reads_pipeline_keys(sheet_dir):
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    actions = app._pipeline_actions
    assert "n" in actions
    assert actions["n"]["kind"] == "NEW"
    assert "l" in actions
    assert actions["l"]["kind"] == "UPDATE"
    assert actions["l"]["context"] == {"row_id": "required"}


def test_tui_builds_help_text(sheet_dir):
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    help_text = app._build_help_text()
    assert "n" in help_text
    assert "NEW" in help_text
    assert "Create from text" in help_text
    assert "l" in help_text
    assert "Log entry" in help_text


def test_tui_writes_inbox_file_no_context(sheet_dir):
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    app._write_inbox_file("NEW", {}, "2-Zimmer Wohnung Vossstrasse 35")
    inbox = sheet_dir / "ingest" / "inbox"
    files = list(inbox.iterdir())
    assert len(files) == 1
    content = files[0].read_text()
    assert content.startswith("NEW\n")
    assert "Vossstrasse" in content


def test_tui_writes_inbox_file_with_context(sheet_dir):
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    app._write_inbox_file("UPDATE", {"row_id": "r20260502120000"}, "@alex sent application")
    inbox = sheet_dir / "ingest" / "inbox"
    files = list(inbox.iterdir())
    assert len(files) == 1
    content = files[0].read_text()
    assert content.startswith("UPDATE row_id=r20260502120000\n")
    assert "@alex" in content


def test_tui_writes_set_file_with_cell(sheet_dir):
    """SET file must have 'field = value' in body, NOT 'cell=field' in header."""
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    app._write_inbox_file("SET", {"row_id": "r20260502120000"}, "amount = 1500")
    inbox = sheet_dir / "ingest" / "inbox"
    files = list(inbox.iterdir())
    assert len(files) == 1
    content = files[0].read_text()
    first_line = content.splitlines()[0]
    assert first_line == "SET row_id=r20260502120000", f"First line has extra context: {first_line}"
    assert "cell=" not in first_line, "cell should not appear in file header"
    assert "amount = 1500" in content


def test_tui_writes_via_staging(sheet_dir):
    """Files go through staging/ then move to inbox/ atomically."""
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    app._write_inbox_file("NEW", {}, "test content")
    # File should be in inbox, not staging
    inbox = sheet_dir / "ingest" / "inbox"
    staging = sheet_dir / "ingest" / "staging"
    assert len(list(inbox.iterdir())) == 1
    assert len(list(staging.iterdir())) == 0


def test_tui_status_bar_shows_pipeline_keys(sheet_dir):
    """The status bar text must include pipeline key hints."""
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    status_text = app._build_status_text(0, 0, 0)
    assert "n=" in status_text
    assert "l=" in status_text
    assert "f=" in status_text
    assert "e=" in status_text
    assert "?=help" in status_text
    assert "q=quit" in status_text


def test_tui_status_bar_shows_counts(sheet_dir):
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    status_text = app._build_status_text(3, 1, 2)
    assert "3 rows" in status_text
    assert "1 pending" in status_text
    assert "2 failed" in status_text


def test_action_modal_uses_shift_enter(sheet_dir):
    """ActionModal must use shift+enter to submit, not ctrl+d."""
    from shapes.sheets.renderer.tui.app import ActionModal
    modal = ActionModal("NEW", "Create from text", use_textarea=True)
    binding_keys = [b.key for b in modal.BINDINGS]
    assert "shift+enter" in binding_keys or "alt+enter" in binding_keys
    assert "ctrl+d" not in binding_keys


def test_help_text_shows_shift_enter_hint(sheet_dir):
    """Help text must mention shift+enter for submit."""
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    help_text = app._build_help_text()
    assert "shift" in help_text.lower(), f"No shift+enter hint in help text: {help_text}"


def test_tui_open_url_binding(sheet_dir):
    """The TUI must have an 'o' binding reserved for opening URLs."""
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    status_text = app._build_status_text(0, 0, 0)
    assert "o=open" in status_text


def test_field_action_parsed(sheet_dir):
    """Fields with action: declared should be parsed into Field.action."""
    import yaml
    sheet = yaml.safe_load((sheet_dir / "sheet.yaml").read_text())
    # Add action to a field in the test fixture
    sheet["fields"]["name"] = {"type": "string", "action": "open"}
    (sheet_dir / "sheet.yaml").write_text(yaml.dump(sheet, sort_keys=False))

    from shapes.sheets.src.fields import parse_fields
    fields = parse_fields(sheet)
    name_field = next(f for f in fields if f.name == "name")
    assert name_field.action == "open"


def test_resolve_modal_mode_is_shared(sheet_dir):
    """_resolve_modal_mode is a single function used by both table and detail view.
    It maps field type to modal configuration declaratively."""
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    from shapes.sheets.src.fields import parse_fields
    fields = parse_fields(app.sheet)
    field_map = {f.name: f for f in fields}

    # enum → options list
    mode = app._resolve_modal_mode(field_map["status"])
    assert mode["options"] == ["new", "done"]
    assert mode["use_textarea"] is False

    # boolean → true/false options
    mode = app._resolve_modal_mode(field_map["starred"])
    assert mode["options"] == ["true", "false"]

    # number → single-line input
    mode = app._resolve_modal_mode(field_map["amount"])
    assert mode["options"] is None
    assert mode["use_textarea"] is False

    # text → textarea
    mode = app._resolve_modal_mode(field_map["notes"])
    assert mode["use_textarea"] is True
    assert mode["options"] is None

    # None (freeform, NEW/UPDATE) → textarea
    mode = app._resolve_modal_mode(None)
    assert mode["use_textarea"] is True


def test_tui_no_footer_widget(sheet_dir):
    """Footer was removed — status bar handles everything."""
    from textual.widgets import Footer
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    widgets = list(app.compose())
    assert not any(isinstance(w, Footer) for w in widgets)


def test_tui_reads_boolean_toggle_keys(sheet_dir):
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    toggles = app._boolean_toggles
    assert "s" in toggles
    assert toggles["s"].name == "starred"
    assert toggles["s"].type == "boolean"
    assert "x" in toggles
    assert toggles["x"].name == "hidden"


def test_tui_help_includes_toggle_keys(sheet_dir):
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    help_text = app._build_help_text()
    assert "s" in help_text
    assert "★" in help_text or "starred" in help_text
    assert "x" in help_text


def test_tui_status_bar_includes_toggle_keys(sheet_dir):
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    status = app._build_status_text(5, 0, 0)
    assert "s=" in status
    assert "x=" in status


def test_tui_status_bar_shows_hidden_count(sheet_dir):
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    status = app._build_status_text(5, 0, 0, hidden_count=2)
    assert "hiding 2" in status


def test_tui_has_search_method(sheet_dir):
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    assert hasattr(app, "action_search")


def test_tui_has_toggle_hidden_method(sheet_dir):
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    assert hasattr(app, "action_toggle_hidden")


def test_tui_key_collision_raises(tmp_path_factory):
    """Pipeline input declaring a reserved key should raise at startup."""
    import pytest
    import yaml
    tmp = tmp_path_factory.mktemp("collision")
    sheet = {
        "title": "Test",
        "pipeline": {"inputs": {
            "QUIT": {"op": "insert", "key": "q", "description": "Quit"},
        }},
        "fields": {"id": "primary", "notes": "text"},
    }
    (tmp / "sheet.yaml").write_text(yaml.dump(sheet, sort_keys=False))
    (tmp / "ops.jsonl").write_text("")
    (tmp / "ingest").mkdir()
    (tmp / "ingest" / "inbox").mkdir()
    (tmp / "ingest" / "failed").mkdir()
    (tmp / "ingest" / "staging").mkdir()
    (tmp / "ingest" / "journal.jsonl").write_text("")

    with pytest.raises(ValueError, match="reserved"):
        SheetsApp(tmp, api_url="http://127.0.0.1:4200")


def test_tui_visibility_field_from_view_config(sheet_dir):
    """Hidden row filtering should use the declared visibility_field, not hardcoded 'hidden'."""
    import yaml
    sheet = yaml.safe_load((sheet_dir / "sheet.yaml").read_text())
    sheet["view"] = {"visibility_field": "hidden"}
    (sheet_dir / "sheet.yaml").write_text(yaml.dump(sheet, sort_keys=False))

    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    assert app._visibility_field == "hidden"


def test_tui_no_visibility_field_means_no_filtering(sheet_dir):
    """Without visibility_field declared, no rows are hidden."""
    import yaml
    sheet = yaml.safe_load((sheet_dir / "sheet.yaml").read_text())
    sheet.pop("view", None)
    (sheet_dir / "sheet.yaml").write_text(yaml.dump(sheet, sort_keys=False))

    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    assert app._visibility_field is None


def test_tui_renders_log_field_in_table(sheet_dir):
    """Log fields should render as count + latest text."""
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    from shapes.sheets.src.fields import parse_fields
    fields = parse_fields(app.sheet)
    field_map = {f.name: f for f in fields}

    import json
    log_value = json.dumps([
        {"ts": "2026-05-01T14:00:00Z", "by": "alex", "text": "sent application"},
        {"ts": "2026-05-02T10:00:00Z", "by": "a", "text": "got viewing invite"},
    ])

    result = app._format_cell_value(log_value, field_map["activity"])
    assert "2" in result
    assert "viewing" in result


def test_tui_renders_empty_log_field(sheet_dir):
    app = SheetsApp(sheet_dir, api_url="http://127.0.0.1:4200")
    from shapes.sheets.src.fields import parse_fields
    fields = parse_fields(app.sheet)
    field_map = {f.name: f for f in fields}

    result = app._format_cell_value("", field_map["activity"])
    assert result == ""

    result2 = app._format_cell_value(None, field_map["activity"])
    assert result2 == ""
