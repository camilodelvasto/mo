import pytest

from shapes.corpus.access import filter as flt
from shapes.corpus.access.errors import FilterError

FLOW = {
    "fields": {
        "tipo": {"type": "enum", "values": ["informe", "datos sintéticos"], "by": "model"},
        "visibility": {"type": "enum", "values": ["general", "private"], "by": "operator"},
        "tags": {"type": "set", "by": "operator"},
    },
    "pipeline": [],
}
PROJ = {
    "d1": {"tipo": "informe", "visibility": "general", "tags": ["a", "b"]},
    "d2": {"tipo": "datos sintéticos", "visibility": "private", "tags": ["b"]},
    "d3": {"tipo": "informe", "visibility": "general", "tags": []},
}


def test_none_matches_all():
    assert flt.doc_ids_for(None, FLOW, PROJ) is None


def test_scalar_enum_equality():
    assert flt.doc_ids_for("tipo == informe", FLOW, PROJ) == {"d1", "d3"}


def test_value_with_spaces():
    assert flt.doc_ids_for("tipo == datos sintéticos", FLOW, PROJ) == {"d2"}


def test_not_equal_and_has():
    got = flt.doc_ids_for("visibility != private AND tags has a", FLOW, PROJ)
    assert got == {"d1"}


def test_or_and_parens_and_not():
    got = flt.doc_ids_for("tipo == informe AND (tags has b OR NOT visibility == private)",
                          FLOW, PROJ)
    assert got == {"d1", "d3"}


def test_in_membership():
    assert flt.doc_ids_for("tipo in [informe]", FLOW, PROJ) == {"d1", "d3"}


def test_undeclared_field_throws():
    with pytest.raises(FilterError, match="not declared"):
        flt.doc_ids_for("bogus == x", FLOW, PROJ)


def test_invalid_enum_value_throws():
    with pytest.raises(FilterError, match="not in"):
        flt.doc_ids_for("tipo == nope", FLOW, PROJ)


def test_has_on_scalar_throws():
    with pytest.raises(FilterError, match="set"):
        flt.doc_ids_for("tipo has informe", FLOW, PROJ)


def test_in_on_set_field_throws():
    with pytest.raises(FilterError, match="set"):
        flt.doc_ids_for("tags in [a]", FLOW, PROJ)


def test_scalar_eq_on_set_field_throws():
    with pytest.raises(FilterError, match="set"):
        flt.doc_ids_for("tags == a", FLOW, PROJ)
