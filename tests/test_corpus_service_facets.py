# tests/test_corpus_service_facets.py
import pathlib, tempfile, yaml
from fastapi.testclient import TestClient
from shapes.corpus.service.app import create_app
from shapes.corpus.engine import sidecar


def _corpus(tmp):
    d = pathlib.Path(tmp) / "c"; (d / "derived").mkdir(parents=True)
    (d / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    flow = {"id": "t", "version": 1,
            "entrypoints": [{"id": "g", "area": "dropbox/general"}],
            "pipeline": [{"id": "classify", "fields": {
                "tipo_documento": {"type": "enum",
                    "values": ["informe", "datos primarios cualitativos"], "by": "model"},
                "tema": {"type": "string", "by": "model"}}}]}
    (d / "flow.yaml").write_text(yaml.safe_dump(flow))
    for did, tipo in [("aaaaaaaaaaaa", "informe"),
                      ("bbbbbbbbbbbb", "datos primarios cualitativos")]:
        pair = d / "corpus" / did; pair.mkdir(parents=True)
        sidecar.write(pair / "meta.yaml", {
            "doc_id": did, "flow": {"id": "t", "version": 1, "hash": "sha256:0"},
            "status": "complete",
            "stages": [{"id": "received", "hash": "sha256:0", "fields": {}},
                       {"id": "classify", "fields": {"tipo_documento": tipo}}]})
    return d


def test_facets_endpoint_returns_status_and_enum_facets():
    with tempfile.TemporaryDirectory() as tmp:
        client = TestClient(create_app(_corpus(tmp)))
        body = client.get("/facets").json()
        assert body["facets"][0]["key"] == "status"
        tipo = next(f for f in body["facets"] if f["key"] == "tipo_documento")
        assert {v["value"]: v["count"] for v in tipo["values"]} == {
            "informe": 1, "datos primarios cualitativos": 1}


def test_catalogue_field_value_filters_on_a_value_with_spaces():
    with tempfile.TemporaryDirectory() as tmp:
        client = TestClient(create_app(_corpus(tmp)))
        r = client.get("/catalogue",
                       params={"field": "tipo_documento",
                               "value": "datos primarios cualitativos"})
        assert r.status_code == 200
        rows = r.json()["rows"]
        assert [x["doc_id"] for x in rows] == ["bbbbbbbbbbbb"]


def test_catalogue_status_pending_and_done_lenses():
    with tempfile.TemporaryDirectory() as tmp:
        d = _corpus(tmp)
        pair = d / "corpus" / "aaaaaaaaaaaa"
        sidecar.write(pair / "meta.yaml", {
            "doc_id": "aaaaaaaaaaaa", "flow": {"id": "t", "version": 1, "hash": "sha256:0"},
            "status": "parked@classify",
            "stages": [{"id": "received", "hash": "sha256:0", "fields": {}}]})
        client = TestClient(create_app(d))
        pend = client.get("/catalogue", params={"lens": "pending"}).json()["rows"]
        done = client.get("/catalogue", params={"lens": "done"}).json()["rows"]
        assert [x["doc_id"] for x in pend] == ["aaaaaaaaaaaa"]
        assert [x["doc_id"] for x in done] == ["bbbbbbbbbbbb"]
