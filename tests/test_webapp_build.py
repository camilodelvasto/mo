"""The webapp shape: a folder declares its build; the shape runs it and returns the output."""
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent


def _load():
    path = ROOT / "shapes" / "webapp" / "exporters" / "build.py"
    spec = importlib.util.spec_from_file_location("webapp_build", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


webapp = _load()

# A build that writes out/index.html, run with this interpreter: no node needed.
WRITE_INDEX = [sys.executable, "-c",
               "import pathlib; p = pathlib.Path('out'); p.mkdir(); (p / 'index.html').write_text('ok')"]

SETTINGS = {"encrypted": False, "mnemonic": None, "rotate": False,
            "service_worker": False, "crawlable": "none"}


def _app(tmp_path, **override):
    declared = {"instance": "webapp", "version": "0.1.0", "schema": "webapp.v1.json",
                "build": [WRITE_INDEX], "out": "out", **override}
    app = tmp_path / "app"
    app.mkdir()
    (app / "webapp.yaml").write_text(yaml.safe_dump(declared))
    return app


def _build(app, **settings):
    return webapp.build(app, "webapp", ROOT, **{**SETTINGS, **settings})


def test_builds_and_returns_the_output_folder(tmp_path):
    app = _app(tmp_path)
    out, mnemonic = _build(app)
    assert out == app / "out"
    assert (out / "index.html").read_text() == "ok"
    assert mnemonic is None


def test_commands_run_in_order_inside_the_folder(tmp_path):
    first = [sys.executable, "-c", "open('order', 'w').write('a')"]
    second = [sys.executable, "-c", "open('order', 'a').write('b')"]
    app = _app(tmp_path, build=[first, second, WRITE_INDEX])
    _build(app)
    assert (app / "order").read_text() == "ab"


def test_missing_declaration_throws(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    with pytest.raises(webapp.WebappError, match="webapp.yaml"):
        _build(app)


@pytest.mark.parametrize("change", [
    {"build": None},
    {"out": None},
    {"build": []},
    {"build": [[]]},
    {"extra": 1},
    {"instance": "deck"},
])
def test_invalid_declaration_throws(tmp_path, change):
    app = _app(tmp_path)
    declared = yaml.safe_load((app / "webapp.yaml").read_text())
    for key, value in change.items():
        if value is None:
            del declared[key]
        else:
            declared[key] = value
    (app / "webapp.yaml").write_text(yaml.safe_dump(declared))
    with pytest.raises(webapp.WebappError, match="webapp.yaml"):
        _build(app)


def test_failing_command_throws_with_command_exit_code_and_output(tmp_path):
    fail = [sys.executable, "-c", "import sys; print('broken here'); sys.exit(3)"]
    app = _app(tmp_path, build=[fail, WRITE_INDEX])
    with pytest.raises(webapp.WebappError) as e:
        _build(app)
    assert "exit 3" in str(e.value)
    assert "broken here" in str(e.value)
    assert not (app / "out").exists()


def test_missing_command_throws(tmp_path):
    app = _app(tmp_path, build=[["no-such-command-xyz"]])
    with pytest.raises(webapp.WebappError, match="no-such-command-xyz"):
        _build(app)


def test_output_without_index_throws(tmp_path):
    app = _app(tmp_path, build=[[sys.executable, "-c", "import os; os.mkdir('out')"]])
    with pytest.raises(webapp.WebappError, match="index.html"):
        _build(app)


@pytest.mark.parametrize("setting", [
    {"encrypted": True},
    {"mnemonic": "abandon about"},
    {"rotate": True},
    {"service_worker": True},
    {"crawlable": "thin"},
    {"crawlable": "full"},
])
def test_settings_a_webapp_cannot_honor_throw(tmp_path, setting):
    app = _app(tmp_path)
    with pytest.raises(webapp.WebappError, match=next(iter(setting))):
        _build(app, **setting)
    assert not (app / "out").exists()


def test_build_takes_every_setting_explicitly(tmp_path):
    app = _app(tmp_path)
    with pytest.raises(TypeError):
        webapp.build(app, "webapp", ROOT)


@pytest.mark.parametrize("out", [".", "..", "../elsewhere"])
def test_output_outside_the_folder_throws(tmp_path, out):
    app = _app(tmp_path, out=out)
    with pytest.raises(webapp.WebappError, match="inside the webapp"):
        _build(app)


def test_stale_output_throws(tmp_path):
    app = _app(tmp_path, build=[[sys.executable, "-c", "pass"]])
    (app / "out").mkdir()
    (app / "out" / "index.html").write_text("old")
    import os
    os.utime(app / "out" / "index.html", (0, 0))
    with pytest.raises(webapp.WebappError, match="not written by this build"):
        _build(app)
