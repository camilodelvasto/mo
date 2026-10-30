# tests/test_corpus_tui_client_facets.py
import pathlib, tempfile, yaml, pytest
from shapes.corpus.renderer.tui.client import embed_client
from shapes.corpus.engine import sidecar


def _corpus(tmp):
    d = pathlib.Path(tmp) / "c"; (d / "derived").mkdir(parents=True)
    (d / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    flow = {"id": "t", "version": 1,
            "entrypoints": [{"id": "g", "area": "dropbox/general"}],
            "pipeline": [{"id": "classify", "fields": {
                "tipo_documento": {"type": "enum",
                    "values": ["informe", "datos primarios cualitativos"], "by": "model"}}}]}
    (d / "flow.yaml").write_text(yaml.safe_dump(flow))
    pair = d / "corpus" / "bbbbbbbbbbbb"; pair.mkdir(parents=True)
    sidecar.write(pair / "meta.yaml", {
        "doc_id": "bbbbbbbbbbbb", "flow": {"id": "t", "version": 1, "hash": "sha256:0"},
        "status": "complete",
        "stages": [{"id": "received", "hash": "sha256:0", "fields": {}},
                   {"id": "classify", "fields": {"tipo_documento": "datos primarios cualitativos"}}]})
    return d


@pytest.mark.asyncio
async def test_client_facets_and_field_value_filter():
    with tempfile.TemporaryDirectory() as tmp:
        client, _ = embed_client(_corpus(tmp))
        try:
            facets = await client.facets()
            assert facets["facets"][0]["key"] == "status"
            page = await client.catalogue(field="tipo_documento",
                                          value="datos primarios cualitativos")
            assert [r["doc_id"] for r in page["rows"]] == ["bbbbbbbbbbbb"]
        finally:
            await client.aclose()
