"""Tests for the deck export capability."""
import json
from pathlib import Path

import pytest
import yaml

PROTO = Path(__file__).resolve().parent.parent


def test_shape_manifest_with_dependencies_validates():
    """A manifest with a dependencies block should pass schema validation."""
    import jsonschema

    schema = json.loads((PROTO / "schema" / "shape.v1.json").read_text())
    manifest = yaml.safe_load((PROTO / "shapes" / "deck" / "shape.manifest.yaml").read_text())
    jsonschema.validate(manifest, schema)


def test_check_capability_deps_core_installed():
    """Core deps (pyyaml, jsonschema) should report as installed."""
    from cli.deps import check_capability_deps

    manifest = yaml.safe_load((PROTO / "shapes" / "deck" / "shape.manifest.yaml").read_text())
    missing = check_capability_deps(manifest, "core")
    assert missing == []


def test_check_capability_deps_missing_capability():
    """A capability with no deps entry returns empty list — no deps needed."""
    from cli.deps import check_capability_deps

    manifest = {"dependencies": {"python": {"core": ["pyyaml>=6.0"]}}}
    missing = check_capability_deps(manifest, "render")
    assert missing == []


def test_check_capability_deps_detects_missing():
    """A package that is not installed should appear in missing list."""
    from cli.deps import check_capability_deps

    manifest = {"dependencies": {"python": {"export.fake": ["nonexistent-pkg-abc>=1.0"]}}}
    missing = check_capability_deps(manifest, "export.fake")
    assert missing == ["nonexistent-pkg-abc>=1.0"]


def test_derive_export_path():
    """Export path follows same rule as build path but under exports/."""
    from shapes.deck.exporters.build import derive_export_path

    corpus = Path("/corpus")
    content = corpus / "content" / "business" / "sensata" / "pitch.yaml"
    result = derive_export_path(content, "deck", corpus)
    assert result == corpus / ".corpus" / "shapes" / "deck" / "exports" / "business" / "sensata" / "pitch"


def test_derive_export_path_nested():
    """Deeply nested content paths preserve full hierarchy."""
    from shapes.deck.exporters.build import derive_export_path

    corpus = Path("/corpus")
    content = corpus / "content" / "personal" / "talks" / "pycon.yaml"
    result = derive_export_path(content, "deck", corpus)
    assert result == corpus / ".corpus" / "shapes" / "deck" / "exports" / "personal" / "talks" / "pycon"


def test_pdf_exporter_has_export_function():
    """The PDF exporter module must expose an export() function."""
    from shapes.deck.exporters import pdf
    assert callable(getattr(pdf, "export", None))


def test_pdf_export_produces_file(tmp_path):
    """PDF export on the example deck produces a .pdf file.

    Requires Playwright + Chromium. Skip if not installed.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")

    from shapes.deck.exporters.pdf import export

    corpus_root = PROTO
    content_path = corpus_root / "content" / "example" / "philosophy-deck.yaml"
    if not content_path.exists():
        pytest.skip("example content not found")

    export_dir = tmp_path / "exports" / "example" / "philosophy-deck"
    export_dir.mkdir(parents=True)
    output = export_dir / "philosophy-deck.pdf"

    shape_path = corpus_root / "shapes" / "deck"
    result = export(content_path, shape_path, corpus_root, output)

    assert result.exists()
    assert result.suffix == ".pdf"
    assert result.stat().st_size > 0


def test_pptx_exporter_has_export_function():
    """The PPTX exporter module must expose an export() function."""
    from shapes.deck.exporters import pptx
    assert callable(getattr(pptx, "export", None))


def test_pptx_export_produces_file(tmp_path):
    """PPTX export on the example deck produces a .pptx file."""
    try:
        import pptx as _  # noqa: F401
    except ImportError:
        pytest.skip("python-pptx not installed")

    from shapes.deck.exporters.pptx import export

    corpus_root = PROTO
    content_path = corpus_root / "content" / "example" / "philosophy-deck.yaml"
    if not content_path.exists():
        pytest.skip("example content not found")

    export_dir = tmp_path / "exports" / "example" / "philosophy-deck"
    export_dir.mkdir(parents=True)
    output = export_dir / "philosophy-deck.pptx"

    shape_path = corpus_root / "shapes" / "deck"
    result = export(content_path, shape_path, corpus_root, output)

    assert result.exists()
    assert result.suffix == ".pptx"
    assert result.stat().st_size > 0


def test_pptx_export_slide_count(tmp_path):
    """PPTX output has the same number of slides as the source YAML."""
    try:
        import pptx as pptx_lib
    except ImportError:
        pytest.skip("python-pptx not installed")

    from shapes.deck.exporters.pptx import export

    corpus_root = PROTO
    content_path = corpus_root / "content" / "example" / "philosophy-deck.yaml"
    if not content_path.exists():
        pytest.skip("example content not found")

    content_data = yaml.safe_load(content_path.read_text())
    expected_count = len(content_data.get("slides", []))

    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    output = export_dir / "test.pptx"

    export(content_path, corpus_root / "shapes" / "deck", corpus_root, output)

    prs = pptx_lib.Presentation(str(output))
    assert len(prs.slides) == expected_count


def test_cli_export_routing(tmp_path, monkeypatch):
    """mo deck export <path> --format pptx routes to the PPTX exporter."""
    try:
        import pptx as _  # noqa: F401
    except ImportError:
        pytest.skip("python-pptx not installed")

    corpus_root = PROTO
    content_path = corpus_root / "content" / "example" / "philosophy-deck.yaml"
    if not content_path.exists():
        pytest.skip("example content not found")

    monkeypatch.chdir(corpus_root)

    from cli.moui import main
    main(["deck", "export", str(content_path), "--format", "pptx"])

    from shapes.deck.exporters.build import derive_export_path
    export_dir = derive_export_path(content_path, "deck", corpus_root)
    pptx_file = export_dir / (content_path.stem + ".pptx")
    assert pptx_file.exists()
