import json
import pytest
from shapes.corpus.builtins import REGISTRY
from shapes.corpus.builtins import chunk_ast, passthrough, stamp, wrap_md
from shapes.corpus.builtins import rename, strip_media
from shapes.corpus.engine.errors import ContractError, StageFailure


def test_registry_matches_manifest_builtins():
    assert set(REGISTRY) == {
        "engine.stamp", "engine.passthrough", "engine.wrap-md", "engine.chunk-ast",
        "engine.strip-media", "engine.rename",
    }


def test_stamp_reads_intrinsics_never_alters(tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("hello corpus")
    result = stamp.run(tmp_path, {"id": "stamp"}, f)
    assert result["output"] is None
    fields = result["fields"]
    assert fields["source_name"] == "note.txt"
    assert fields["mime"] == "text/plain"
    assert fields["size"] == 12
    assert fields["hash"].startswith("sha256:")


def test_stamp_unknown_type_fails_loud(tmp_path):
    f = tmp_path / "blob.zzznope"
    f.write_bytes(b"\x00\x01")
    with pytest.raises(StageFailure):
        stamp.run(tmp_path, {"id": "stamp"}, f)


def test_passthrough_copies_markdown(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("# title\n\nbody\n")
    result = passthrough.run(tmp_path, {"id": "normalize"}, f)
    assert result["output"].name == "transcript.md"
    assert result["output"].read_text() == "# title\n\nbody\n"


def test_wrap_md_wraps_plain_text(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("plain text body")
    result = wrap_md.run(tmp_path, {"id": "normalize"}, f)
    assert result["output"].name == "transcript.md"
    assert "plain text body" in result["output"].read_text()


def test_chunk_ast_respects_boundaries_and_sizes(tmp_path):
    md = tmp_path / "transcript.md"
    md.write_text("# one\n\n" + ("alpha " * 120).strip() + "\n\n# two\n\n" + ("beta " * 120).strip() + "\n")
    stage = {"id": "chunk", "with": {"target_size": 512, "max_size": 1024}}
    result = chunk_ast.run(tmp_path, stage, md)
    chunks = [json.loads(line) for line in result["output"].read_text().splitlines()]
    assert result["output"].name == "chunks.jsonl"
    assert result["meters"]["chunks"] == len(chunks) >= 2
    assert all(len(c["text"]) <= 1024 for c in chunks)
    assert all(set(c) == {"ref", "ast_path", "span", "contiguous", "text"} for c in chunks)
    assert all(c["ref"].startswith("c") for c in chunks)


def test_chunk_ast_refs_unique_per_doc_and_stable(tmp_path):
    # Repeated identical blocks under the same section (legal-page boilerplate)
    # must not collide: downstream keys by ref. Re-chunking the same transcript
    # must reproduce the same refs, repeats included.
    md = tmp_path / "transcript.md"
    para = ("boilerplate " * 40).strip()
    md.write_text("# section\n\n" + ("\n\n".join([para] * 3)) + "\n")
    stage = {"id": "chunk", "with": {"target_size": 64, "max_size": 128}}
    first = [json.loads(l) for l in chunk_ast.run(tmp_path, stage, md)["output"].read_text().splitlines()]
    refs = [c["ref"] for c in first]
    assert len(refs) == len(set(refs))
    second = [json.loads(l) for l in chunk_ast.run(tmp_path, stage, md)["output"].read_text().splitlines()]
    assert refs == [c["ref"] for c in second]


def _strip(tmp_path, text):
    t = tmp_path / "transcript.md"
    t.write_text(text)
    return strip_media.run(tmp_path, {"id": "strip-media"}, t)


def test_strip_media_removes_reference_def_blob_keeps_label(tmp_path):
    text = (
        "# Informe\n\nVer la figura [image1] abajo.\n\n"
        "[image1]: <data:image/png;base64,iVBORw0KGgoAAAANSU>\n"
    )
    result = _strip(tmp_path, text)
    out = result["output"].read_text()
    assert "data:image" not in out and "base64" not in out
    assert "[image1]" in out            # body label preserved as placeholder
    assert "# Informe" in out and "Ver la figura" in out
    assert result["meters"]["media_removed"] == 1
    assert result["meters"]["bytes_removed"] > 0


def test_strip_media_inline_image_becomes_alt(tmp_path):
    result = _strip(tmp_path, "texto ![Figura 3](data:image/png;base64,AAAA) fin\n")
    out = result["output"].read_text()
    assert "data:" not in out
    assert "[Figura 3]" in out and "texto" in out and "fin" in out
    assert result["meters"]["media_removed"] == 1


def test_strip_media_inline_image_no_alt_becomes_placeholder(tmp_path):
    result = _strip(tmp_path, "x ![](data:image/png;base64,AAAA) y\n")
    assert "[image]" in result["output"].read_text()


def test_strip_media_html_img_becomes_placeholder(tmp_path):
    result = _strip(tmp_path, '<img src="data:image/png;base64,AAAA" alt="Diagrama">\n')
    out = result["output"].read_text()
    assert "data:" not in out and "[Diagrama]" in out


def test_strip_media_leaves_real_url_images_untouched(tmp_path):
    text = "![logo](https://example.com/logo.png)\n[ref]: <https://example.com/a.png>\n"
    result = _strip(tmp_path, text)
    out = result["output"].read_text()
    assert "https://example.com/logo.png" in out
    assert "https://example.com/a.png" in out
    assert result["meters"]["media_removed"] == 0


def test_strip_media_is_idempotent(tmp_path):
    t = tmp_path / "transcript.md"
    t.write_text("[image1]: <data:image/png;base64,iVBOR>\n\nbody text\n")
    r1 = strip_media.run(tmp_path, {"id": "strip-media"}, t)
    cleaned = r1["output"].read_text()
    r2 = strip_media.run(tmp_path, {"id": "strip-media"}, r1["output"])
    assert r2["output"].read_text() == cleaned          # no further change
    assert r2["meters"]["media_removed"] == 0


def test_strip_media_no_media_is_noop(tmp_path):
    result = _strip(tmp_path, "# title\n\nplain body, no images.\n")
    assert result["meters"]["media_removed"] == 0
    assert "plain body" in result["output"].read_text()


def test_strip_then_chunk_produces_clean_chunks(tmp_path):
    import json
    from shapes.corpus.builtins import chunk_ast
    t = tmp_path / "transcript.md"
    t.write_text(
        "# Informe\n\nTexto real sobre educación.\n\n"
        "[image1]: <data:image/png;base64," + ("A" * 5000) + ">\n"
    )
    strip_media.run(tmp_path, {"id": "strip-media"}, t)
    stage = {"id": "chunk", "with": {"target_size": 512, "max_size": 1024}}
    result = chunk_ast.run(tmp_path, stage, t)
    chunks = [json.loads(line) for line in result["output"].read_text().splitlines()]
    assert chunks, "expected at least one chunk"
    assert all("data:image" not in c["text"] and "base64" not in c["text"] for c in chunks)
    assert any("educación" in c["text"] for c in chunks)


# --- engine.rename ------------------------------------------------------------

def _pair(tmp_path, name="Entrevista Juan Carlos.docx"):
    pair = tmp_path / "3c52c3b63b07"
    pair.mkdir()
    f = pair / name
    f.write_bytes(b"docx bytes")
    return pair, f


def test_rename_to_doc_id_keeps_the_extension(tmp_path):
    pair, f = _pair(tmp_path)
    stage = {"id": "rename", "with": {"to": "${doc_id}"}, "artifact": "original"}
    result = rename.run(pair, stage, f)
    assert result["output"] == pair / "3c52c3b63b07.docx"
    assert result["output"].read_bytes() == b"docx bytes"
    assert not f.exists()
    assert result["fields"] == {}
    assert "Juan" not in str(result)          # the old name leaves no trace


def test_rename_template_prefix(tmp_path):
    pair, f = _pair(tmp_path)
    stage = {"id": "rename", "with": {"to": "entrevista-${doc_id}"}, "artifact": "original"}
    assert rename.run(pair, stage, f)["output"].name == "entrevista-3c52c3b63b07.docx"


def test_rename_is_idempotent(tmp_path):
    pair, f = _pair(tmp_path, name="3c52c3b63b07.docx")
    stage = {"id": "rename", "with": {"to": "${doc_id}"}, "artifact": "original"}
    assert rename.run(pair, stage, f)["output"] == f
    assert f.exists()


def test_rename_requires_to(tmp_path):
    pair, f = _pair(tmp_path)
    with pytest.raises(ContractError):
        rename.run(pair, {"id": "rename", "artifact": "original"}, f)


def test_rename_rejects_unknown_placeholder(tmp_path):
    pair, f = _pair(tmp_path)
    stage = {"id": "rename", "with": {"to": "${source_name}"}, "artifact": "original"}
    with pytest.raises(ContractError):
        rename.run(pair, stage, f)


def test_rename_rejects_path_separators_and_empty_stem(tmp_path):
    pair, f = _pair(tmp_path)
    for to in ("../${doc_id}", "a/b", ""):
        with pytest.raises(ContractError):
            rename.run(pair, {"id": "rename", "with": {"to": to}, "artifact": "original"}, f)


def test_rename_must_declare_artifact_original(tmp_path):
    pair, f = _pair(tmp_path)
    with pytest.raises(ContractError):
        rename.run(pair, {"id": "rename", "with": {"to": "${doc_id}"}}, f)
    with pytest.raises(ContractError):
        rename.run(pair, {"id": "rename", "with": {"to": "${doc_id}"}, "artifact": "transcript"}, f)


def test_rename_fails_on_collision_inside_the_pair(tmp_path):
    pair, f = _pair(tmp_path, name="note.yaml")
    (pair / "meta.yaml").write_text("doc_id: x\n")
    stage = {"id": "rename", "with": {"to": "meta"}, "artifact": "original"}
    with pytest.raises(StageFailure):
        rename.run(pair, stage, f)
    assert f.exists() and (pair / "meta.yaml").read_text() == "doc_id: x\n"


def test_names_originals_reads_the_flow():
    assert rename.names_originals({"pipeline": [{"id": "rename", "uses": "engine.rename"}]})
    assert not rename.names_originals({"pipeline": [{"id": "stamp", "uses": "engine.stamp"}]})
    assert not rename.names_originals({"pipeline": [
        {"id": "normalize", "uses": {"dispatch_on": "mime", "routes": {"text/plain": "engine.wrap-md"}}}]})
