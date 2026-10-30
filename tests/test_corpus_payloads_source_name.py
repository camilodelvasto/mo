from shapes.corpus.service import payloads


def test_build_row_surfaces_source_name_from_stamp():
    doc = {"doc_id": "d1", "status": "complete", "stages": [
        {"id": "stamp", "fields": {"source_name": "Voté_por_Petro.txt"}},
        {"id": "characterize", "fields": {"tema": "algo sin el apellido"}}]}
    row = payloads.build_row(doc, {"tema"}, [])
    assert row["source_name"] == "Voté_por_Petro.txt"
    # the term is NOT in any declared cell — proving source_name is the only carrier
    cell_text = " ".join(str(c["value"]) for c in row["cells"].values()).lower()
    assert "petro" not in cell_text


def test_build_row_omits_source_name_when_absent():
    doc = {"doc_id": "d2", "status": "complete", "stages": [
        {"id": "characterize", "fields": {"tema": "algo"}}]}
    row = payloads.build_row(doc, {"tema"}, [])
    assert "source_name" not in row          # omit, never null / empty string
