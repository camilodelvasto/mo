"""Tests for capability-first dispatcher routing."""
import json
import yaml
import pytest


@pytest.fixture
def dispatch_corpus(tmp_path):
    """Corpus with a shape that declares a 'serve' capability via adapter."""
    shape_dir = tmp_path / "shapes" / "testshape"
    shape_dir.mkdir(parents=True)
    commands_dir = shape_dir / "commands"
    commands_dir.mkdir()

    manifest = {
        "name": "testshape",
        "version": "0.1.0",
        "type": "service",
        "description": "Test shape for dispatcher",
        "capabilities": {
            "serve": [{"adapter": "commands/serve.py"}],
            "custom": [{"adapter": "commands/custom.py"}],
        },
        "schemas": {"extends": [], "defines": [], "deposits_to": "content/schema/"},
        "permissions": {
            "filesystem": {"read": ["content/"], "write": []},
            "network": "none",
            "subprocess": "none",
        },
    }
    (shape_dir / "shape.manifest.yaml").write_text(yaml.dump(manifest, sort_keys=False))

    # Write adapter files with run() functions
    (commands_dir / "serve.py").write_text(
        "def run(corpus_root, instance, args):\n"
        "    pass\n"
    )
    (commands_dir / "custom.py").write_text(
        "def run(corpus_root, instance, args):\n"
        "    pass\n"
    )

    corpus = {
        "v": 1,
        "name": "test",
        "shapes": {
            "testshape": {"shape": "testshape", "version": "0.1.0", "local": True},
        },
    }
    (tmp_path / "moui.json").write_text(json.dumps(corpus))

    return tmp_path


def test_shape_has_capability_true(dispatch_corpus, monkeypatch):
    """Shape with declared serve capability should be detected."""
    import sys
    monkeypatch.chdir(dispatch_corpus)
    sys.path.insert(0, str(dispatch_corpus))

    from cli.moui import _shape_has_capability
    assert _shape_has_capability(dispatch_corpus, "testshape", "serve") is True
    assert _shape_has_capability(dispatch_corpus, "testshape", "custom") is True


def test_shape_has_capability_false(dispatch_corpus, monkeypatch):
    """Shape without a capability for the verb should return False."""
    import sys
    monkeypatch.chdir(dispatch_corpus)
    sys.path.insert(0, str(dispatch_corpus))

    from cli.moui import _shape_has_capability
    assert _shape_has_capability(dispatch_corpus, "testshape", "build") is False
    assert _shape_has_capability(dispatch_corpus, "testshape", "nonexistent") is False


def test_non_renderer_serve_delegates_to_capability(dispatch_corpus, monkeypatch):
    """Generic serve handler delegates to shape capability for non-renderer types."""
    import sys
    monkeypatch.chdir(dispatch_corpus)
    sys.path.insert(0, str(dispatch_corpus))

    from cli.moui import main
    # testshape is type "service", so generic serve handler should delegate
    # to the shape's own serve adapter (which is a no-op).
    # Create a dummy content file so resolve_content_path doesn't fail.
    content = dispatch_corpus / "somepath.yaml"
    content.write_text("dummy: true")
    main(["testshape", "serve", str(content)])


def test_custom_verb_routes_to_capability(dispatch_corpus, monkeypatch):
    """Verbs not in HANDLERS route through capability system."""
    import sys
    monkeypatch.chdir(dispatch_corpus)
    sys.path.insert(0, str(dispatch_corpus))

    from cli.moui import main
    # "custom" is not in HANDLERS, should go directly to capability adapter
    main(["testshape", "custom", "somearg"])


def test_generic_handler_fallback(dispatch_corpus, monkeypatch):
    """When shape has no capability, should fall through to HANDLERS."""
    import sys
    monkeypatch.chdir(dispatch_corpus)
    sys.path.insert(0, str(dispatch_corpus))

    from cli.moui import _shape_has_capability
    # testshape doesn't declare build, so it should fall through
    assert _shape_has_capability(dispatch_corpus, "testshape", "build") is False
