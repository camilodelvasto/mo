# tests/test_corpus_tui_facets_build.py
from shapes.corpus.renderer.tui.facets import facet_nodes

PAYLOAD = {"facets": [
    {"key": "status", "values": [
        {"value": "all", "count": 3}, {"value": "pending", "count": 1}, {"value": "done", "count": 2}]},
    {"key": "tipo_documento", "values": [
        {"value": "informe", "count": 1}, {"value": "datos primarios cualitativos", "count": 2}]}]}


def test_facet_nodes_categories_with_labelled_leaves_and_selection_data():
    label_map = {"status": "Status", "pending": "pending", "tipo_documento": "Type"}
    def lab(k):
        return label_map.get(k, k)
    nodes = facet_nodes(PAYLOAD, lab)
    assert nodes[0]["label"] == "Status"
    assert nodes[0]["leaves"][0] == {
        "label": "all", "count": 3, "select": ("status", "all")}
    assert nodes[0]["leaves"][1]["select"] == ("status", "pending")
    assert nodes[1]["label"] == "Type"
    assert nodes[1]["leaves"][0] == {
        "label": "informe", "count": 1, "select": ("tipo_documento", "informe")}
    assert nodes[1]["leaves"][1]["select"] == (
        "tipo_documento", "datos primarios cualitativos")
