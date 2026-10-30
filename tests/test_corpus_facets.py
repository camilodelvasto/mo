# tests/test_corpus_facets.py
import json
import pathlib
import tempfile

from shapes.corpus.service.cache import Cache, _enum_fields

FLOW = {
    "id": "t", "version": 1,
    "pipeline": [{"id": "classify", "fields": {
        "tipo_documento": {"type": "enum", "values": ["informe", "datos primarios cualitativos"], "by": "model"},
        "audiencia": {"type": "enum", "values": ["Todas", "Jovenes"], "by": "model"},
        "tema": {"type": "string", "by": "model"}}}]}


def _cache(tmp):
    corpus = pathlib.Path(tmp) / "c"; (corpus / "derived").mkdir(parents=True)
    return Cache(corpus, FLOW)


def test_enum_fields_are_the_typed_enums_in_declaration_order():
    assert _enum_fields(FLOW) == [
        ("tipo_documento", ["informe", "datos primarios cualitativos"]),
        ("audiencia", ["Todas", "Jovenes"])]
    # `tema` (type: string) is NOT an enum facet.


def test_facets_status_first_then_present_enum_values_in_declared_order():
    with tempfile.TemporaryDirectory() as tmp:
        cache = _cache(tmp)
        cache.db.execute("REPLACE INTO rows VALUES (?,?,?,?,?,?,?,?)",
            ("aaa", "complete", 0, 0, 0, 0, 0, json.dumps(
                {"doc_id": "aaa", "status": "complete",
                 "cells": {"tipo_documento": {"value": "informe"},
                           "audiencia": {"value": "Todas"}}})))
        cache.db.execute("REPLACE INTO rows VALUES (?,?,?,?,?,?,?,?)",
            ("bbb", "parked@classify", 0, 1, 0, 0, 0, json.dumps(
                {"doc_id": "bbb", "status": "parked@classify",
                 "cells": {"tipo_documento": {"value": "datos primarios cualitativos"}}})))
        cache.db.commit()
        out = cache.facets()
        assert out["facets"][0]["key"] == "status"
        assert out["facets"][0]["values"] == [
            {"value": "all", "count": 2}, {"value": "pending", "count": 1}, {"value": "done", "count": 1}]
        tipo = next(f for f in out["facets"] if f["key"] == "tipo_documento")
        assert tipo["values"] == [
            {"value": "informe", "count": 1}, {"value": "datos primarios cualitativos", "count": 1}]
        aud = next(f for f in out["facets"] if f["key"] == "audiencia")
        assert aud["values"] == [{"value": "Todas", "count": 1}]   # 'Jovenes' absent → omitted
        assert [f["key"] for f in out["facets"]] == ["status", "tipo_documento", "audiencia"]
